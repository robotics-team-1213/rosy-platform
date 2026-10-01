"""The site HTTPS port is scoped by interface name ahead of Docker, and a dead bind stops the start."""

import importlib.util
import ipaddress
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy/site/site-firewall.py"


def _module():
    spec = importlib.util.spec_from_file_location("rosy_site_firewall", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(bind="0.0.0.0", port="8443", lan_iface="wlan0", allow="", tls_host="site-pc.local"):
    """`docker compose config --format json` as Compose renders the site file."""
    ports = [{"mode": "ingress", "target": 8443, "published": port, "protocol": "tcp"}]
    if bind is not None:
        ports[0]["host_ip"] = bind
    return {"services": {"proxy": {"ports": ports}},
            "x-rosy-site": {"lan_iface": lan_iface, "allow_literal_bind": allow, "tls_host": tls_host},
            "secrets": {"site_cert": {"file": "/s/site.crt"}, "site_key": {"file": "/s/site.key"},
                        "site_ca": {"file": "/s/site-ca.crt"}}}


class FakeHost:
    """`docker compose config` plus `iptables -t mangle` and `iptables-restore --noflush`."""

    def __init__(self, config=None, chains=None, engine="28.3.0"):
        self.config = config or _config()
        self.engine = engine
        self.chains = chains if chains is not None else {"PREROUTING": []}
        self.calls = []

    def __call__(self, argv, stdin=None):
        self.calls.append((argv, stdin))
        if argv[:2] == ["docker", "compose"]:
            return 0, json.dumps(self.config), ""
        if argv[:2] == ["docker", "version"]:
            return (0, self.engine + "\n", "") if self.engine else (1, "", "Cannot connect")
        if argv[0] == "iptables-restore":
            assert argv[1:] == ["-w", "--noflush"]
            lines = stdin.splitlines()
            assert lines[0] == "*mangle" and lines[-1] == "COMMIT"
            for line in lines[1:-1]:
                if line.startswith(":"):
                    self.chains[line[1:].split()[0]] = []  # declaring a chain flushes it
                else:
                    self.chains[line.split()[1]].append(line)
            return 0, "", ""
        assert argv[:4] == ["iptables", "-w", "-t", "mangle"]
        op, chain, rest = argv[4], argv[5], argv[6:]
        if op == "-S":
            if chain not in self.chains:
                return 1, "", f"No chain/target/match by that name: {chain}"
            return 0, "\n".join([f"-N {chain}", *self.chains[chain]]) + "\n", ""
        if op == "-I":
            self.chains[chain].insert(int(rest[0]) - 1, " ".join(["-A", chain, *rest[1:]]))
        elif op == "-D":
            self.chains[chain].remove(" ".join(["-A", chain, *rest]))
        return 0, "", ""

    def mutations(self):
        return [argv for argv, _ in self.calls
                if argv[0] == "iptables-restore" or (argv[0] == "iptables" and argv[4] != "-S")]


def _plan(module, **overrides):
    settings = module.compose_settings(_config(**overrides))
    return module.site_plan(settings, assigned=lambda address: False, exists=lambda name: True)


def test_restore_payload_is_one_mangle_transaction_by_interface_name():
    module = _module()
    plan = _plan(module, lan_iface="wlan0, eth0")
    assert module.restore_payload(plan["ifaces"]) == (
        "*mangle\n"
        ":ROSY-SITE-INGRESS - [0:0]\n"
        "-A ROSY-SITE-INGRESS -i lo -j RETURN\n"
        "-A ROSY-SITE-INGRESS -i wlan0 -j RETURN\n"
        "-A ROSY-SITE-INGRESS -i eth0 -j RETURN\n"
        "-A ROSY-SITE-INGRESS -m addrtype --dst-type LOCAL -j DROP\n"
        "-A ROSY-SITE-INGRESS -i br+ -j RETURN\n"
        "-A ROSY-SITE-INGRESS -i docker0 -j RETURN\n"
        "-A ROSY-SITE-INGRESS -j DROP\n"
        "COMMIT\n")
    assert module.jump_rules(8443) == {
        ("8443", False): ["-p", "tcp", "--dport", "8443", "-j", "ROSY-SITE-INGRESS"]}
    # A different published port adds the container port, for packets routed to a container IP.
    assert module.jump_rules(9443) == {
        ("9443", False): ["-p", "tcp", "--dport", "9443", "-j", "ROSY-SITE-INGRESS"],
        ("8443", True): ["-p", "tcp", "--dport", "8443", "-m", "addrtype", "!", "--dst-type", "LOCAL",
                         "-j", "ROSY-SITE-INGRESS"]}
    # Never an address or subnet: the LAN may renumber (2026-10-01 192.168.1.0/24 -> 10.16.36.0/24).
    rules = [token for rule in module.chain_rules(plan["ifaces"]) for token in rule]
    assert not {"-s", "-d", "--src", "--dst"} & set(rules)


def test_apply_installs_chain_then_jump_and_is_idempotent():
    module = _module()
    plan = _plan(module)
    host = FakeHost()
    first = module.apply(plan, run=host)
    assert first == ["iptables-restore -w --noflush",
                     "iptables -w -t mangle -I PREROUTING 1 -p tcp --dport 8443 -j ROSY-SITE-INGRESS"]
    assert host.chains["ROSY-SITE-INGRESS"] == module.chain_listing(["wlan0"])[1:]
    before = len(host.calls)
    assert module.apply(plan, run=host) == []
    assert all(argv[4] == "-S" for argv, _ in host.calls[before:])  # only reads the second time
    module.check(plan, run=host)


def test_apply_replaces_a_changed_interface_atomically_and_moves_the_port():
    module = _module()
    host = FakeHost()
    module.apply(_plan(module, lan_iface="eth0"), run=host)
    plan = _plan(module, lan_iface="wlan0", port="9443")
    before = len(host.calls)
    module.apply(plan, run=host)
    changes = [argv for argv, _ in host.calls[before:] if argv[0] == "iptables-restore"
               or argv[4] in ("-I", "-D")]
    assert [argv[0] if argv[0] == "iptables-restore" else argv[4] for argv in changes] == \
        ["iptables-restore", "-I", "-I", "-D"]  # new jumps before the old one goes: no open gap
    assert sorted(line for line in host.chains["PREROUTING"] if line.endswith("ROSY-SITE-INGRESS")) == [
        "-A PREROUTING -p tcp --dport 8443 -m addrtype ! --dst-type LOCAL -j ROSY-SITE-INGRESS",
        "-A PREROUTING -p tcp --dport 9443 -j ROSY-SITE-INGRESS"]
    assert module.apply(plan, run=host) == []
    module.check(plan, run=host)


@pytest.mark.parametrize("damage", ["no_chain", "wrong_iface", "no_jump", "jump_after_accept",
                                    "no_container_port_jump", "no_final_drop"])
def test_check_refuses_a_missing_or_bypassed_filter(damage):
    module = _module()
    plan = _plan(module, port="9443")
    host = FakeHost()
    module.apply(plan, run=host)
    if damage == "no_chain":
        del host.chains["ROSY-SITE-INGRESS"]
    elif damage == "wrong_iface":
        host.chains["ROSY-SITE-INGRESS"][1] = "-A ROSY-SITE-INGRESS -i eth9 -j RETURN"
    elif damage == "no_jump":
        host.chains["PREROUTING"].clear()
    elif damage == "jump_after_accept":
        host.chains["PREROUTING"].insert(0, "-A PREROUTING -j ACCEPT")
    elif damage == "no_container_port_jump":
        host.chains["PREROUTING"] = [line for line in host.chains["PREROUTING"] if "--dst-type" not in line]
    else:
        host.chains["ROSY-SITE-INGRESS"].pop()
    with pytest.raises(RuntimeError, match="rosy-site-firewall.service"):
        module.check(plan, run=host)


def test_failed_restore_is_an_error_and_installs_no_jump():
    module = _module()

    class Broken(FakeHost):
        def __call__(self, argv, stdin=None):
            if argv[0] == "iptables-restore":
                self.calls.append((argv, stdin))
                return 1, "", "iptables-restore: line 4 failed"
            return super().__call__(argv, stdin)

    host = Broken()
    with pytest.raises(RuntimeError, match="line 4 failed"):
        module.apply(_plan(module), run=host)
    assert host.chains["PREROUTING"] == []


def test_loopback_bind_needs_no_interface_and_touches_no_rules():
    module = _module()
    for bind in ("127.0.0.1", "::1"):
        plan = _plan(module, bind=bind, lan_iface="")
        assert plan["mode"] == "loopback"
        host = FakeHost(chains={})
        assert module.apply(plan, run=host) == [] and host.calls == []
        module.check(plan, run=host)


@pytest.mark.parametrize("overrides, reason", [
    ({"lan_iface": ""}, "ROSY_SITE_LAN_IFACE is empty"),
    ({"bind": "::"}, "not supported: the LAN filter and robot discovery are IPv4"),
    ({"bind": None}, "every IPv4 and IPv6 address"),
    ({"bind": "site-pc.local"}, "not an IP address"),
    ({"lan_iface": "wlan0 -j ACCEPT"}, "invalid interface name"),
    ({"lan_iface": "lo"}, "invalid interface name"),
])
def test_preflight_rejects_configs_that_cannot_be_scoped(overrides, reason):
    module = _module()
    with pytest.raises(module.ConfigError, match=reason):
        _plan(module, **overrides)


def test_literal_ip_bind_needs_the_host_address_and_an_explicit_opt_in():
    module = _module()
    settings = module.compose_settings(_config(bind="192.168.1.50"))
    with pytest.raises(module.ConfigError, match="not assigned on this host.*0.0.0.0"):
        module.site_plan(settings, assigned=lambda address: False, exists=lambda name: True)
    with pytest.raises(module.ConfigError, match="ROSY_SITE_ALLOW_LITERAL_BIND=1"):
        module.site_plan(settings, assigned=lambda address: True, exists=lambda name: True)
    allowed = module.compose_settings(_config(bind="192.168.1.50", allow="1"))
    assert module.site_plan(allowed, assigned=lambda address: True,
                            exists=lambda name: True)["mode"] == "address"


def test_missing_interface_warns_and_names_the_bridge_case():
    module = _module()
    settings = module.compose_settings(_config(lan_iface="wlan0,wlp+"))
    plan = module.site_plan(settings, assigned=lambda address: False, exists=lambda name: False)
    assert len(plan["warnings"]) == 1 and "wlan0" in plan["warnings"][0] and "br0" in plan["warnings"][0]


def test_address_probe_reports_an_address_this_host_does_not_own():
    # 192.0.2.0/24 is TEST-NET-1 (RFC 5737); no host is configured with it.
    assert _module().address_assigned("192.0.2.123") is False


def test_address_probe_surfaces_other_socket_errors(monkeypatch):
    import errno
    import socket

    module = _module()

    class Refusing(socket.socket):
        def bind(self, address):
            raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(module.socket, "socket", Refusing)
    with pytest.raises(module.ConfigError, match="cannot tell whether .* Permission denied"):
        module.address_assigned("192.0.2.123")


@pytest.mark.parametrize("engine, warned", [("27.5.1", True), ("28.0.4", False), ("", False)])
def test_check_warns_on_docker_engine_older_than_28(tmp_path, capsys, engine, warned):
    module = _module()
    env = tmp_path / "site.env"
    env.write_text("ROSY_SITE_BIND_ADDRESS=0.0.0.0\n", encoding="utf-8")
    host = FakeHost(engine=engine)
    module.apply(_plan(module), run=host)
    assert module.main(["check", "--env-file", str(env)], run=host) == 0
    assert ("older than 28" in capsys.readouterr().err) is warned


@pytest.mark.parametrize("line", ["export ROSY_SITE_BIND_ADDRESS=0.0.0.0", "rosy_site_lan_iface=wlan0",
                                  "ROSY SITE=1", "just words"])
def test_env_lines_systemd_and_compose_would_read_differently_exit_2(tmp_path, capsys, line):
    module = _module()
    env = tmp_path / "site.env"
    env.write_text(f"# site\nROSY_SITE_HTTPS_PORT=8443\n{line}\n", encoding="utf-8")
    assert module.main(["check", "--env-file", str(env)], run=FakeHost()) == 2
    assert "not a plain KEY=VALUE line" in capsys.readouterr().err


def test_bind_comes_from_compose_not_from_reading_the_env_file(tmp_path, capsys):
    """Compose resolves `${VAR}` and inline comments; the check sees what Compose binds."""
    module = _module()
    env = tmp_path / "site.env"
    env.write_text("BIND=0.0.0.0\nROSY_SITE_BIND_ADDRESS=${BIND}\nROSY_SITE_LAN_IFACE=  # none yet\n",
                   encoding="utf-8")
    host = FakeHost(config=_config(bind="0.0.0.0", lan_iface=""))
    assert module.main(["check", "--env-file", str(env), "--compose-file", "c.yaml"], run=host) == 2
    assert "ROSY_SITE_LAN_IFACE is empty" in capsys.readouterr().err
    argv = host.calls[0][0]
    assert argv[:2] == ["docker", "compose"] and argv[-3:] == ["config", "--format", "json"]
    assert argv[argv.index("--env-file") + 1] == str(env) and argv[argv.index("-f") + 1] == "c.yaml"


def test_real_compose_resolves_export_comments_and_interpolation(tmp_path):
    """The same env through the real Compose CLI, when Docker is installed (no daemon needed)."""
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed")
    module = _module()
    env = tmp_path / "site.env"
    dirs = "".join(f"{key}={tmp_path}\n" for key in ("ROSY_SITE_CONFIG_DIR", "ROSY_SITE_SECRETS_DIR"))
    env.write_text(dirs + "BASE=9\nROSY_SITE_HTTPS_PORT=${BASE}443\n"
                   "ROSY_SITE_BIND_ADDRESS=0.0.0.0 # LAN\n"
                   "ROSY_SITE_LAN_IFACE=wlan0 # Wi-Fi\nROSY_SITE_TLS_HOST=site-pc.local\n",
                   encoding="utf-8")
    probe = subprocess.run(["docker", "compose", "version"], capture_output=True, check=False)
    if probe.returncode != 0:
        pytest.skip("docker compose plugin not installed")
    settings = module.compose_settings(module.compose_config(
        env, ROOT / "deploy/site/compose.yaml", "rosy-fw-test", module._run))
    assert (settings["bind"], settings["port"], settings["lan_iface"], settings["tls_host"]) == \
        ("0.0.0.0", 9443, "wlan0", "site-pc.local")


def test_cli_dry_run_prints_the_restore_payload_and_writes_nothing(tmp_path, capsys):
    module = _module()
    env = tmp_path / "site.env"
    env.write_text("ROSY_SITE_BIND_ADDRESS=0.0.0.0\n", encoding="utf-8")
    public = tmp_path / "run/site-public.env"
    host = FakeHost()
    assert module.main(["apply", "--dry-run", "--env-file", str(env), "--public-env", str(public)],
                       run=host) == 0
    out = capsys.readouterr().out
    assert ":ROSY-SITE-INGRESS - [0:0]" in out and "-i wlan0 -j RETURN" in out
    assert "-I PREROUTING 1 -p tcp --dport 8443 -j ROSY-SITE-INGRESS" in out
    assert "-i docker0 -j RETURN" in out and "-A ROSY-SITE-INGRESS -j DROP" in out
    assert host.mutations() == [] and not public.exists()


def test_apply_writes_only_the_public_values_for_the_host_units(tmp_path):
    module = _module()
    env = tmp_path / "site.env"
    env.write_text("ROSY_SITE_BIND_ADDRESS=127.0.0.1\n", encoding="utf-8")
    public = tmp_path / "run/site-public.env"
    host = FakeHost(config=_config(bind="127.0.0.1", port="9443", lan_iface=""))
    assert module.main(["apply", "--env-file", str(env), "--public-env", str(public)], run=host) == 0
    assert public.read_text(encoding="utf-8") == \
        "ROSY_SITE_TLS_HOST=site-pc.local\nROSY_SITE_HTTPS_PORT=9443\n"


def test_strict_certificate_check_accepts_the_profile_and_names_the_failure(tmp_path):
    from test_site_mdns_bridge import _site_pki

    module = _module()
    ca = _site_pki(tmp_path, "site-pc.local")
    module.verify_site_certificate(tmp_path / "site.crt", tmp_path / "site.key", ca, "site-pc.local")
    with pytest.raises(module.ConfigError, match="fails strict verification for other-pc.local"):
        module.verify_site_certificate(tmp_path / "site.crt", tmp_path / "site.key", ca,
                                       "other-pc.local")
    loose = tmp_path / "loose"
    loose.mkdir()
    loose_ca = _site_pki(loose, "site-pc.local", strict=False)
    with pytest.raises(module.ConfigError, match="fails strict verification"):
        module.verify_site_certificate(loose / "site.crt", loose / "site.key", loose_ca,
                                       "site-pc.local")


def test_units_filter_before_docker_fail_closed_and_recheck():
    site = ROOT / "deploy/site"
    firewall = (site / "rosy-site-firewall.service").read_text(encoding="utf-8")
    failclosed = (site / "rosy-site-firewall-failclosed.service").read_text(encoding="utf-8")
    check = (site / "rosy-site-firewall-check.service").read_text(encoding="utf-8")
    timer = (site / "rosy-site-firewall-check.timer").read_text(encoding="utf-8")
    stack = (site / "rosy-site-stack.service").read_text(encoding="utf-8")
    assert "Before=docker.service rosy-site-stack.service" in firewall
    assert "After=network-pre.target" in firewall and "PartOf=" not in firewall
    assert "Type=oneshot" in firewall and "RemainAfterExit=yes" in firewall
    assert "WantedBy=multi-user.target docker.service" in firewall
    assert "OnFailure=rosy-site-firewall-failclosed.service" in firewall
    assert "OnFailure=rosy-site-firewall-failclosed.service" in check
    assert "site-firewall.py apply --env-file /etc/rosy/site/site.env" in firewall
    assert "site-firewall.py check --env-file /etc/rosy/site/site.env" in check
    project = re.search(r"--project-name (\S+)", stack).group(1)
    assert f"Environment=ROSY_SITE_PROJECT={project}" in failclosed  # same project the stack uses
    assert ("docker ps -q --filter label=com.docker.compose.project=$${ROSY_SITE_PROJECT} "
            "--filter label=com.docker.compose.service=proxy | xargs -r docker stop") in failclosed
    assert "docker compose" not in failclosed and "site.env" not in failclosed
    assert "After=docker.service" in failclosed
    assert "Unit=rosy-site-firewall-check.service" in timer and "OnUnitInactiveSec=5min" in timer
    preflight = stack.index("ExecStartPre=/usr/bin/python3 /opt/rosy/candidate/deploy/site/"
                            "site-firewall.py check --verify-certs --env-file /etc/rosy/site/site.env")
    assert preflight < stack.index("ExecStart=/usr/bin/docker compose")
    assert "After=rosy-site-firewall.service" in stack


def test_compose_and_env_never_require_a_lan_ip():
    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")
    env = (ROOT / "deploy/site/.env.example").read_text(encoding="utf-8")
    assert '- "${ROSY_SITE_BIND_ADDRESS:-127.0.0.1}:${ROSY_SITE_HTTPS_PORT:-8443}:8443"' in compose
    assert "ROSY_SITE_BIND_ADDRESS:?" not in compose
    assert 'lan_iface: "${ROSY_SITE_LAN_IFACE:-}"' in compose
    settings = dict(line.split("=", 1) for line in env.splitlines() if line and not line.startswith("#"))
    assert settings["ROSY_SITE_BIND_ADDRESS"] == "127.0.0.1"
    assert settings["ROSY_SITE_LAN_IFACE"] == ""
    for text in (compose, env):
        for literal in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
            ip = ipaddress.ip_address(literal)
            assert ip.is_loopback or ip.is_unspecified, literal


def test_lan_docs_bind_the_wildcard_and_scope_by_interface():
    readme = (ROOT / "deploy/site/README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/deployment/site-ceiling-camera-console-runbook.md").read_text(encoding="utf-8")
    lan = readme[readme.index("## LAN access"):readme.index("## Contract path")]
    assert "| `ROSY_SITE_BIND_ADDRESS` | `127.0.0.1` (default) | `0.0.0.0` |" in lan
    assert "mangle" in lan and "iptables-restore" in lan and "--dry-run" in lan
    assert "DOCKER-USER" not in readme and "br0" in lan and "needs no IP SAN" in lan
    assert "### Upgrading from a literal-IP bind" in lan
    assert "### Site certificate profile" in readme and "openssl verify -x509_strict" in readme
    assert "Docker Engine 28" in lan and "### Recovering after the port was closed" in lan
    assert "systemctl restart rosy-site-stack" in lan
    assert "/etc/rosy/site/.env" not in readme
    assert "to the interface address" not in readme and "approved interface address" not in readme
    assert "ROSY_SITE_DISCOVERY_URL=" not in readme
    assert "ROSY_SITE_BIND_ADDRESS=0.0.0.0" in runbook and "ROSY_SITE_LAN_IFACE" in runbook
    assert "rosy-site-firewall.service" in runbook and "검색기 끊김" in runbook
