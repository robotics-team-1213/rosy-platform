"""D-391 3: the site-host preflight stops a mismatched cert, TXT host or Caddy host before start."""

import datetime
import importlib.util
import ipaddress
import json
import sys
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy/site/site_preflight.py"
SITE_DIR = ROOT / "deploy/site"
HOST = "fixture-site.local"


def _module():
    spec = importlib.util.spec_from_file_location("rosy_site_preflight", PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _name(common):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def _cert(subject, issuer_name, issuer_key, public_key, *, ca, san=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(_name(issuer_name))
               .public_key(public_key).serial_number(x509.random_serial_number())
               .not_valid_before(now - datetime.timedelta(days=1))
               .not_valid_after(now + datetime.timedelta(days=30)))
    if ca is not None:
        builder = builder.add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName(san), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


def _pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _chain(dns=(HOST,), ips=(), leaf_ca=False):
    """Throwaway CA and leaf made at test time; no key ever reaches disk."""
    ca_key, leaf_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    ca = _cert("fixture-ca", "fixture-ca", ca_key, ca_key.public_key(), ca=True)
    san = [x509.DNSName(n) for n in dns] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    leaf = _cert("fixture-leaf", "fixture-ca", ca_key, leaf_key.public_key(), ca=leaf_ca, san=san)
    return _pem(leaf), _pem(ca)


@pytest.fixture
def site(tmp_path):
    """A consistent site: fullchain, env file, the shipped units and Caddyfile."""
    leaf, ca = _chain()
    cert = tmp_path / "site.crt"
    cert.write_text(leaf + ca, encoding="ascii")
    env = tmp_path / ".env"
    env.write_text(f"ROSY_SITE_TLS_HOST={HOST}\nROSY_SITE_HTTPS_PORT=8443\n", encoding="utf-8")
    return {"tmp": tmp_path, "cert": cert, "env": env, "leaf": leaf, "ca": ca}


def _argv(site, *, tls_host=HOST, caddyfile=None, units=("overhead", "fleet")):
    argv = ["--site-cert", str(site["cert"]), "--env-file", str(site["env"]),
            "--caddyfile", str(caddyfile or SITE_DIR / "Caddyfile")]
    if tls_host is not None:
        argv += ["--tls-host", tls_host]
    for name in units:
        argv += ["--unit", str(SITE_DIR / f"rosy-{name}-advertise.service")]
    return argv


def _run(site, *extra, **kwargs):
    return _module().main(_argv(site, **kwargs) + list(extra))


def _failed(capsys):
    out = capsys.readouterr().out
    return [line for line in out.splitlines() if line.startswith("FAIL")], out


def test_consistent_site_passes(site, capsys):
    assert _run(site) == 0
    fails, out = _failed(capsys)
    assert not fails and "PASS" in out


def test_leaf_only_cert_is_refused_with_fullchain_hint(site, capsys):
    site["cert"].write_text(site["leaf"], encoding="ascii")
    assert _run(site) != 0
    fails, _ = _failed(capsys)
    assert any("fullchain" in line and "cat site.crt site-ca.crt" in line for line in fails)


def test_leaf_followed_by_another_leaf_is_refused(site, capsys):
    other_leaf, _ = _chain()
    site["cert"].write_text(site["leaf"] + other_leaf, encoding="ascii")
    assert _run(site) != 0
    assert any("CA" in line for line in _failed(capsys)[0])


def test_ca_first_order_is_refused(site, capsys):
    site["cert"].write_text(site["ca"] + site["leaf"], encoding="ascii")
    assert _run(site) != 0
    assert any("fullchain" in line for line in _failed(capsys)[0])


def test_leaf_that_is_itself_a_ca_is_refused(site, capsys):
    leaf, ca = _chain(leaf_ca=True)
    site["cert"].write_text(leaf + ca, encoding="ascii")
    assert _run(site) != 0
    assert any("leaf" in line for line in _failed(capsys)[0])


def test_unparseable_or_missing_cert_fails_without_traceback(site, capsys):
    site["cert"].write_text("not a certificate", encoding="ascii")
    assert _run(site) != 0
    assert _failed(capsys)[0]
    site["cert"].unlink()
    assert _run(site) != 0
    assert _failed(capsys)[0]


def test_san_without_tls_host_is_refused(site, capsys):
    leaf, ca = _chain(dns=("other-site.local",))
    site["cert"].write_text(leaf + ca, encoding="ascii")
    assert _run(site) != 0
    assert any("SAN" in line and HOST in line for line in _failed(capsys)[0])


def test_san_match_is_case_insensitive(site):
    leaf, ca = _chain(dns=("Fixture-Site.LOCAL",))
    site["cert"].write_text(leaf + ca, encoding="ascii")
    assert _run(site) == 0


def test_wildcard_san_does_not_satisfy_tls_host(site, capsys):
    leaf, ca = _chain(dns=("*.local",))
    site["cert"].write_text(leaf + ca, encoding="ascii")
    assert _run(site) != 0
    assert any("SAN" in line for line in _failed(capsys)[0])


def test_ip_san_is_neither_required_nor_checked(site):
    assert _run(site) == 0  # fixture leaf has no IP SAN
    leaf, ca = _chain(ips=("192.0.2.77",))
    site["cert"].write_text(leaf + ca, encoding="ascii")
    assert _run(site) == 0  # a stale IP SAN is not a failure either


@pytest.mark.parametrize("bad", ["192.168.1.20", "fixture-site.example.com", "fixture-site",
                                 "fixture-site.local:8443"])
def test_tls_host_must_be_a_local_name(site, capsys, bad):
    assert _run(site, tls_host=bad) != 0
    assert any("tls_host" in line and ".local" in line for line in _failed(capsys)[0])


def test_ip_tls_host_names_the_ip_reason(site, capsys):
    assert _run(site, tls_host="192.168.1.20") != 0
    assert any("IP" in line for line in _failed(capsys)[0])


def test_unit_publishing_a_different_tls_host_is_refused(site, capsys):
    site["env"].write_text("ROSY_SITE_TLS_HOST=stale-site.local\n", encoding="utf-8")
    assert _run(site) != 0
    assert any("TXT" in line and "stale-site.local" in line for line in _failed(capsys)[0])


def test_unit_with_empty_tls_host_is_refused(site, capsys):
    site["env"].write_text("ROSY_SITE_HTTPS_PORT=8443\n", encoding="utf-8")
    assert _run(site) != 0
    assert any("TXT" in line for line in _failed(capsys)[0])


def test_env_file_value_is_the_default_configured_tls_host(site, monkeypatch):
    monkeypatch.delenv("ROSY_SITE_TLS_HOST", raising=False)
    assert _run(site, tls_host=None, units=("overhead",)) == 0


def test_env_variable_supplies_tls_host(site, monkeypatch):
    site["env"].write_text("ROSY_SITE_HTTPS_PORT=8443\n", encoding="utf-8")
    monkeypatch.setenv("ROSY_SITE_TLS_HOST", HOST)
    assert _run(site, tls_host=None, units=("overhead",)) != 0  # unit reads the env file, not the shell
    site["env"].write_text(f"ROSY_SITE_TLS_HOST={HOST}\n", encoding="utf-8")
    assert _run(site, tls_host=None, units=("overhead",)) == 0


def test_no_unit_publishing_tls_host_is_refused(site, capsys):
    assert _run(site, units=("fleet",)) != 0
    assert any("TXT" in line for line in _failed(capsys)[0])


def _caddy(site, text):
    path = site["tmp"] / "Caddyfile"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("address", [f"{HOST.upper()}:8443", f"https://{HOST}:8443", HOST])
def test_caddy_address_naming_tls_host_passes(site, address):
    path = _caddy(site, f"{{\n\tadmin localhost:2019\n}}\n\n{address} {{\n\ttls /a /b\n}}\n")
    assert _run(site, caddyfile=path) == 0


def test_shipped_caddyfile_port_only_address_passes(site):
    assert _run(site, caddyfile=SITE_DIR / "Caddyfile") == 0


def test_caddy_address_naming_another_host_is_refused(site, capsys):
    path = _caddy(site, "other-site.local:8443 {\n\ttls /a /b\n}\n")
    assert _run(site, caddyfile=path) != 0
    assert any("Caddy" in line and "other-site.local" in line for line in _failed(capsys)[0])


def test_caddy_ip_address_is_refused(site, capsys):
    path = _caddy(site, "192.168.1.20:8443 {\n}\n")
    assert _run(site, caddyfile=path) != 0
    assert any("Caddy" in line for line in _failed(capsys)[0])


def test_caddy_without_site_block_is_refused(site, capsys):
    path = _caddy(site, "# nothing here\n")
    assert _run(site, caddyfile=path) != 0
    assert any("Caddy" in line for line in _failed(capsys)[0])


def test_every_failure_has_reason_and_fix_hint(site, capsys):
    site["cert"].write_text(site["leaf"], encoding="ascii")
    site["env"].write_text("ROSY_SITE_TLS_HOST=stale-site.local\n", encoding="utf-8")
    assert _run(site, "--json") != 0
    report = json.loads(capsys.readouterr().out)
    failed = [c for c in report["checks"] if not c["ok"]]
    assert report["ok"] is False and failed
    assert all(c["reason"] and c["fix"] and c["id"] for c in failed)


def test_json_report_lists_every_check(site, capsys):
    assert _run(site, "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert {c["id"] for c in report["checks"]} >= {
        "site_cert_fullchain", "leaf_san_tls_host", "tls_host_local", "txt_tls_host", "caddy_host"}


def test_help_says_ip_sans_are_not_checked(capsys):
    with pytest.raises(SystemExit):
        _module().main(["--help"])
    assert "IP SAN" in capsys.readouterr().out


def test_shipped_unit_uses_the_env_name_the_preflight_reads():
    overhead = (SITE_DIR / "rosy-overhead-advertise.service").read_text(encoding="utf-8")
    assert "${ROSY_SITE_TLS_HOST}" in overhead and "--tls-host" in overhead


def test_vendored_ca_check_agrees_with_core_common_on_site_link_vectors():
    sys.path.insert(0, str(ROOT / "src/contracts/foundation"))
    try:
        from core_common.protocol import site_link
    finally:
        sys.path.pop(0)
    vector = json.loads((ROOT / "test/fixtures/protocol/site-link.v1.json").read_text(encoding="utf-8"))
    module = _module()
    compared = 0
    for case in vector["cases"]:
        ca_pem = case["record"].get("ca_pem")
        assert module.ca_pem_reason(ca_pem) == site_link._ca_pem_reason(ca_pem), case["id"]
        expect = case["expect"]
        if expect["valid"] or expect["reason"] in ("bad_ca_pem", "leaf_not_ca"):
            assert module.ca_pem_reason(ca_pem) == expect.get("reason"), case["id"]
            compared += 1
    assert compared >= 5


# --- review fixes: systemd unit forms, env file syntax, every Caddy site block ---

def test_unit_continuation_prefix_and_bare_dollar_var_expand_like_systemd(tmp_path):
    unit = tmp_path / "rosy-overhead-advertise.service"
    unit.write_text("[Service]\nEnvironment=H=" + HOST + "\n"
                    "ExecStart=-/usr/bin/python3 /opt/rosy/site/fleet-mdns.py publish \\n"
                    "  --role overhead --tls-host $H\n", encoding="utf-8")
    assert _module().published_tls_host(unit, {}) == (True, HOST)


def test_an_empty_execstart_resets_the_command(tmp_path):
    unit = tmp_path / "rosy-overhead-advertise.service"
    unit.write_text("[Service]\nExecStart=/x publish --role overhead --tls-host other.local\n"
                    "ExecStart=\n", encoding="utf-8")
    assert _module().published_tls_host(unit, {}) == (False, None)


def test_env_file_strips_export_and_only_matching_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text('export ROSY_SITE_TLS_HOST="' + HOST + '"\nODD=\'y"\n', encoding="utf-8")
    values = _module().read_env_file(env)
    assert values["ROSY_SITE_TLS_HOST"] == HOST
    assert values["ODD"] == "'y\""


def test_every_top_level_caddy_site_block_is_checked_and_snippets_are_skipped():
    text = "{\n admin off\n}\n(snip) {\n x\n}\n" + HOST + ":8443 {\n}\nother.local {\n}\n"
    assert _module().caddy_site_hosts(text) == [HOST, "other.local"]


# --- D-341 pairing consistency -------------------------------------------------------------

OVERLAY_ARG = "-f /opt/rosy/candidate/deploy/site/compose.pairing.yaml"
ON = "ROSY_SITE_PAIRING=1\n"


def _pairing_site(site, *, unit_env="", site_env="", compose_arg="", secrets=True,
                  token="sync-token-value"):
    tmp = site["tmp"]
    site["env"].write_text(f"ROSY_SITE_TLS_HOST={HOST}\nROSY_SITE_HTTPS_PORT=8443\n{unit_env}",
                           encoding="utf-8")
    site_env_file = tmp / "site.env"
    site_env_file.write_text(f"{site_env}ROSY_SITE_PAIRING_COMPOSE={compose_arg}\n", encoding="utf-8")
    secrets_dir = tmp / "secrets"
    secrets_dir.mkdir(exist_ok=True)
    if secrets:
        for name in ("registry_token", "phone_ingress_token", "fleet_sighting_token",
                     "discovery_token", "vision_preview_secret"):
            (secrets_dir / name).write_text(f"other-{name}\n", encoding="utf-8")
        (secrets_dir / "pairing_sync_token").write_text(token + "\n", encoding="utf-8")
    return ["--site-env", str(site_env_file), "--secrets-dir", str(secrets_dir)]


def _pairing_run(site, extra, capsys):
    code = _module().main(_argv(site) + extra)
    fails, out = _failed(capsys)
    return code, fails, out


def test_pairing_off_by_default_passes_and_says_so(site, capsys):
    code, fails, out = _pairing_run(site, _pairing_site(site), capsys)
    assert code == 0 and not fails
    assert "PASS pairing_consistent" in out and "pairing off" in out


def test_pairing_fully_enabled_passes(site, capsys):
    extra = _pairing_site(site, unit_env=ON, site_env=ON, compose_arg=OVERLAY_ARG)
    code, fails, out = _pairing_run(site, extra, capsys)
    assert code == 0 and not fails, out
    assert "PASS pairing_consistent" in out and "pairing on" in out


@pytest.mark.parametrize("unit_env,site_env,compose_arg,why", [
    (ON, "", OVERLAY_ARG, "disagree"),                  # Fleet side not enabled
    ("", ON, OVERLAY_ARG, "disagree"),                  # Fleet on, TXT side off
    (ON, ON, "", "compose.pairing.yaml"),               # switch without the overlay
    ("", "", OVERLAY_ARG, "compose.pairing.yaml"),      # overlay without the switch
    ("ROSY_SITE_PAIRING=yes\n", "ROSY_SITE_PAIRING=yes\n", OVERLAY_ARG, "use 1"),
])
def test_pairing_inconsistency_is_refused_with_fix(site, capsys, unit_env, site_env, compose_arg, why):
    extra = _pairing_site(site, unit_env=unit_env, site_env=site_env, compose_arg=compose_arg)
    code, fails, _ = _pairing_run(site, extra, capsys)
    assert code != 0
    line = next(line for line in fails if "pairing_consistent" in line)
    assert why in line and "| fix:" in line


def test_unit_that_advertises_pair_while_off_or_omits_it_while_on_is_refused(site, capsys, tmp_path):
    extra = _pairing_site(site, unit_env=ON, site_env=ON, compose_arg=OVERLAY_ARG)
    unit = tmp_path / "rosy-overhead-advertise.service"
    unit.write_text("[Service]\nExecStart=/x publish --role overhead --tls-host fixture-site.local\n",
                    encoding="utf-8")
    argv = ["--site-cert", str(site["cert"]), "--env-file", str(site["env"]), "--tls-host", HOST,
            "--caddyfile", str(SITE_DIR / "Caddyfile"), "--unit", str(unit), *extra]
    assert _module().main(argv) != 0
    fails, _ = _failed(capsys)
    assert any("does not advertise pair=rosy-pair/1" in line for line in fails)


def test_enabled_pairing_needs_a_distinct_sync_token(site, capsys):
    on = dict(unit_env=ON, site_env=ON, compose_arg=OVERLAY_ARG)
    code, fails, _ = _pairing_run(site, _pairing_site(site, secrets=False, **on), capsys)
    assert code != 0 and any("pairing_sync_token" in line for line in fails)
    code, fails, _ = _pairing_run(site, _pairing_site(site, token="other-discovery_token", **on), capsys)
    assert code != 0 and any("distinct" in line for line in fails)


def test_shipped_units_wire_the_pairing_switch():
    unit = (SITE_DIR / "rosy-overhead-advertise.service").read_text(encoding="utf-8")
    assert "Environment=ROSY_SITE_PAIRING=0" in unit and "--pair=${ROSY_SITE_PAIRING}" in unit
    stack = (SITE_DIR / "rosy-site-stack.service").read_text(encoding="utf-8")
    # unbraced $VAR is zero words when empty, so "off" adds nothing to up and down
    assert stack.count(" $ROSY_SITE_PAIRING_COMPOSE ") == 2
