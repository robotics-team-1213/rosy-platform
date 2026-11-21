"""D-1064: the opt-in Account LAN alias exposes only the browser login, on the existing port."""
import copy
import json
import re
from pathlib import Path

import pytest
import yaml

from deploy.site import site_update_io
from deploy.site.build_candidate import DEPLOY_FILES
from test_site_account_https import account_config
from test_site_candidate_verifier import _load_verifier
from test_site_firewall import _module

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "deploy/site"
WEB = ROOT / "applications/fleet/web"
LAN_FILES = ("compose.account-lan.yaml", "Caddyfile.account-lan", "rosy-mdns-alias@.service", "account-lan-cert.sh")
ALLOWED_GET = {
    "/console/login",
    "/console/assets/fleet-document.css", "/console/assets/password-login.css",
    "/console/assets/login-page.js", "/console/assets/password-login.js",
    "/console/assets/login-return.js", "/console/assets/account-permissions.js",
    "/common/*",
    "/api/fleet/auth/connection", "/api/fleet/auth/session", "/api/fleet/auth/authorize",
}
ALLOWED_POST = {"/api/fleet/auth/login", "/api/fleet/auth/change-password"}
# Called by login-page.js/password-login.js but kept tailnet-only on purpose (D-1064).
TAILNET_ONLY = {"/api/fleet/auth/access-requests", "/api/fleet/auth/logout"}


def _overlay():
    return yaml.safe_load((SITE / "compose.account-lan.yaml").read_text(encoding="utf-8"))


def _caddy():
    return (SITE / "Caddyfile.account-lan").read_text(encoding="utf-8")


def _matcher(text, name):
    block = re.search(r"@" + name + r" \{\n(.*?)\n\t\}", text, re.S).group(1)
    lines = [line.strip() for line in block.splitlines() if line.strip() and not line.strip().startswith("#")]
    methods = [line.split()[1:] for line in lines if line.startswith("method ")]
    paths = {word for line in lines if line.startswith("path ") for word in line.split()[1:]}
    assert all(line.startswith(("method ", "path ")) for line in lines)
    return methods, paths


def test_overlay_adds_only_a_host_block_and_its_certificate_to_the_proxy():
    overlay = _overlay()
    assert set(overlay) == {"services"} and set(overlay["services"]) == {"proxy"}
    proxy = overlay["services"]["proxy"]
    assert set(proxy) == {"labels", "environment", "volumes"}  # no ports, networks or new service
    assert proxy["labels"] == {"org.rosy.site-account-lan-caddy-sha256": "unbuilt"}
    assert proxy["environment"] == {"ROSY_ACCOUNT_LAN_HOST": "${ROSY_ACCOUNT_LAN_HOST:?set ROSY_ACCOUNT_LAN_HOST}"}
    mounts = {m["target"]: m for m in proxy["volumes"]}
    assert set(mounts) == {"/etc/caddy/account/lan.caddy", "/run/rosy-account-lan-tls"}
    assert mounts["/etc/caddy/account/lan.caddy"]["source"] == "./Caddyfile.account-lan"
    assert mounts["/run/rosy-account-lan-tls"]["source"] == "/etc/rosy/account-lan-tls"
    for mount in mounts.values():
        assert mount["type"] == "bind" and mount["read_only"] is True
        assert mount["bind"] == {"create_host_path": False}
    # The base Caddyfile imports this directory at top level, before the catch-all site block.
    assert "import /etc/caddy/account/*.caddy" in (SITE / "Caddyfile").read_text(encoding="utf-8")


def test_firewall_plan_is_unchanged_by_the_lan_overlay():
    module = _module()
    base = account_config()
    merged = copy.deepcopy(base)
    lan = _overlay()["services"]["proxy"]
    merged["services"]["proxy"]["volumes"] += [dict(m) for m in lan["volumes"]]
    merged["services"]["proxy"]["environment"]["ROSY_ACCOUNT_LAN_HOST"] = "account-lan.example.local"
    before, after = module.compose_settings(base), module.compose_settings(merged)
    assert after == before
    assert after["port"] == 8443 and after["account"]["ifaces"] == ["tailscale0"]
    assert module.site_plan(after, exists=lambda name: True) == module.site_plan(before, exists=lambda name: True)


def test_lan_host_block_allows_exactly_the_login_paths_and_404s_the_rest():
    text = _caddy()
    sites = re.findall(r"^(\S.*) \{$", text, re.M)
    assert sites == ["(rosy_account_lan_upstream)", "https://{$ROSY_ACCOUNT_LAN_HOST}:{$ROSY_SITE_HTTPS_PORT}"]
    assert ":443" not in text
    assert "tls /run/rosy-account-lan-tls/account-lan.crt /run/rosy-account-lan-tls/account-lan.key" in text
    assert _matcher(text, "login_read") == ([["GET"]], ALLOWED_GET)
    assert _matcher(text, "login_write") == ([["POST"]], ALLOWED_POST)
    assert set(re.findall(r"^\t@(\w+)", text, re.M)) == {"login_read", "login_write"}
    handles = re.findall(r"^\thandle(.*)\{$", text, re.M)
    assert handles == [" @login_read ", " @login_write ", " "]
    assert text.rstrip().endswith("handle {\n\t\trespond 404\n\t}\n}")
    assert set(re.findall(r"reverse_proxy (\S+)", text)) == {"https://account:8098"}
    assert "fleet:" not in text and "header_up -X-Rosy-Lan-Camera" in text


def test_allowed_api_paths_are_real_account_routes_and_admin_backchannel_stay_closed():
    routes = set()
    for path in (ROOT / "operations/account/rosy_account").glob("*.py"):
        routes |= set(re.findall(r"@app\.(?:get|post)\(['\"](/api/fleet/auth/[a-z-]+)['\"]", path.read_text(encoding="utf-8")))
    allowed = {p for p in ALLOWED_GET | ALLOWED_POST if p.startswith("/api/")}
    assert allowed <= routes
    closed = {"/api/fleet/auth/" + n for n in ("token", "introspect", "userinfo", "apps", "revoke", "keys",
                                                  "setup", "clients", "accounts")}
    assert closed <= routes | {"/api/fleet/auth/clients", "/api/fleet/auth/accounts"}
    assert not closed & allowed and not TAILNET_ONLY & allowed


def test_login_page_and_its_modules_need_nothing_outside_the_allowlist():
    registry = json.loads((WEB / "assets.json").read_text(encoding="utf-8"))["assets"]
    html = (WEB / "login.html").read_text(encoding="utf-8")
    pending = [u for u in re.findall(r'(?:src|href)="(/console/assets/[^"]+)"', html)]
    seen, api = set(), set()
    while pending:
        url = pending.pop()
        if url in seen:
            continue
        seen.add(url)
        assert url in ALLOWED_GET, url
        if url.endswith(".js"):
            source = (WEB / registry[url.rsplit("/", 1)[1]]["path"]).read_text(encoding="utf-8")
            pending += re.findall(r"from '(/console/assets/[^']+)'", source)
            api |= set(re.findall(r"'(/api/fleet/auth/[a-z-]+)", source))
    assert "/console/assets/account-permissions.js" in seen  # transitive import of password-login.js
    assert re.findall(r'(?:src|href)="(/[^"#]+)"', html)  # sanity: the page names its assets
    for url in re.findall(r'(?:src|href)="(/common/[^"]+)"', html):
        assert url.startswith("/common/")
    assert api - {"/api/fleet/auth/authorize"} <= (ALLOWED_GET | ALLOWED_POST | TAILNET_ONLY)
    assert {"/api/fleet/auth/connection", "/api/fleet/auth/session", "/api/fleet/auth/login",
            "/api/fleet/auth/change-password"} <= api


def test_mdns_alias_is_a_repo_template_on_the_lan_interface():
    unit = (SITE / "rosy-mdns-alias@.service").read_text(encoding="utf-8")
    assert "EnvironmentFile=/etc/rosy/site/site.env" in unit
    assert "Requires=avahi-daemon.service" in unit and "Restart=always" in unit
    [start] = [line for line in unit.splitlines() if line.startswith("ExecStart=")]
    assert start.endswith("rosy-mdns-alias ${ROSY_SITE_LAN_IFACE} %i")
    assert 'exec /usr/bin/avahi-publish -a -R "$$2" "$$addr"' in start
    assert 'tailscale*) exit 1' in start  # never advertise the tailnet address on the LAN
    assert not re.search(r"\d+\.\d+\.\d+\.\d+|\.local\b(?!\.service)", start)  # no literal host or address


def test_certificate_script_issues_a_strict_leaf_where_caddy_reads_it():
    script = (SITE / "account-lan-cert.sh").read_text(encoding="utf-8")
    assert "out=/etc/rosy/account-lan-tls" in script
    assert '"$out/account-lan.key"' in script and '"$out/account-lan.crt"' in script
    assert "openssl verify -x509_strict -purpose sslserver -verify_hostname" in script
    assert "subjectAltName = DNS:$host" in script and "CA:FALSE" in script
    assert "install -d -o 10001 -g 10001 -m 0700" in script
    assert "BEGIN" not in script  # no key material in the repository


def test_candidate_ships_the_group_and_old_candidates_stay_valid():
    verifier = _load_verifier()
    assert set(LAN_FILES) <= set(DEPLOY_FILES) and set(LAN_FILES) <= set(verifier.REQUIRED_DEPLOYMENT_FILES)
    assert set(verifier.ACCOUNT_LAN_FILES) == set(LAN_FILES)
    build = (SITE / "build_candidate.py").read_text(encoding="utf-8")
    assert '("compose.account-lan.yaml", "Caddyfile.account-lan", "org.rosy.site-account-lan-caddy-sha256")' in build


@pytest.mark.parametrize("overlay, allowed", [
    ("compose.account.yaml compose.account-lan.yaml", True),
    ("compose.pairing.yaml compose.workcell.yaml compose.control-unit.yaml compose.control-unit-remote.yaml "
     "compose.monitoring.yaml compose.account.yaml compose.account-lan.yaml", True),
    ("compose.account-lan.yaml", False),
    ("compose.account-lan.yaml compose.account.yaml", False),
])
def test_updater_accepts_the_lan_overlay_only_after_account(overlay, allowed):
    words = " ".join(f"-f /opt/rosy/candidate/deploy/site/{name}" for name in overlay.split())
    env = {"ROSY_SITE_PAIRING_COMPOSE": words}
    if allowed:
        assert site_update_io.allowed_overlays(env) == words.split()
    else:
        with pytest.raises(site_update_io.Refused):
            site_update_io.allowed_overlays(env)
