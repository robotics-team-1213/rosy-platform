"""The site HTTPS port is scoped by interface name, and a dead bind address stops the start."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy/site/site-firewall.py"


def _module():
    spec = importlib.util.spec_from_file_location("rosy_site_firewall", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeIptables:
    """`iptables -S/-N/-F/-A/-I/-D` over chains held as `-S` text lines."""

    def __init__(self, chains=None):
        self.chains = chains if chains is not None else {"DOCKER-USER": ["-A DOCKER-USER -j RETURN"]}
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        assert argv[0] in ("iptables", "ip6tables") and argv[1] == "-w"
        op, chain, rest = argv[2], argv[3], argv[4:]
        if op == "-S":
            if chain not in self.chains:
                return 1, ""
            return 0, "\n".join([f"-N {chain}", *self.chains[chain]]) + "\n"
        if op == "-N":
            if chain in self.chains:
                return 1, ""
            self.chains[chain] = []
        elif op == "-F":
            self.chains[chain] = []
        elif op == "-A":
            self.chains[chain].append(" ".join(["-A", chain, *rest]))
        elif op == "-I":
            self.chains[chain].insert(int(rest[0]) - 1, " ".join(["-A", chain, *rest[1:]]))
        elif op == "-D":
            self.chains[chain].remove(" ".join(["-A", chain, *rest]))
        return 0, ""


def _plan(module, **env):
    values = {"ROSY_SITE_BIND_ADDRESS": "0.0.0.0", "ROSY_SITE_LAN_IFACE": "wlan0", **env}
    return module.site_plan(values, assigned=lambda address: False)


def test_lan_rules_match_the_interface_name_and_the_published_port_only():
    module = _module()
    plan = _plan(module, ROSY_SITE_HTTPS_PORT="9443", ROSY_SITE_LAN_IFACE="wlan0, eth0")
    text = [" ".join(command) for command in module.fresh_commands(plan)]
    assert text == [
        "iptables -w -N ROSY-SITE-INGRESS",
        "iptables -w -F ROSY-SITE-INGRESS",
        "iptables -w -A ROSY-SITE-INGRESS -i wlan0 -j RETURN",
        "iptables -w -A ROSY-SITE-INGRESS -i eth0 -j RETURN",
        "iptables -w -A ROSY-SITE-INGRESS -j DROP",
        "iptables -w -I DOCKER-USER 1 -p tcp -m conntrack --ctstate DNAT --ctdir ORIGINAL "
        "--ctorigdstport 9443 -j ROSY-SITE-INGRESS",
    ]
    # Never an address or subnet: the LAN may renumber (2026-10-01 192.168.1.0/24 -> 10.16.36.0/24).
    assert not any(flag in line.split() for line in text for flag in ("-s", "-d", "--src", "--dst"))


def test_ipv6_wildcard_uses_ip6tables():
    module = _module()
    plan = _plan(module, ROSY_SITE_BIND_ADDRESS="::")
    assert {command[0] for command in module.fresh_commands(plan)} == {"ip6tables"}


def test_apply_is_idempotent_and_check_passes_after_it():
    module = _module()
    plan = _plan(module)
    fake = FakeIptables()
    first = module.apply(plan, run=fake)
    assert [command[2] for command in first] == ["-N", "-F", "-A", "-A", "-I"]
    assert fake.chains["DOCKER-USER"][0].endswith("--ctorigdstport 8443 -j ROSY-SITE-INGRESS")
    assert fake.chains["ROSY-SITE-INGRESS"] == ["-A ROSY-SITE-INGRESS -i wlan0 -j RETURN",
                                                "-A ROSY-SITE-INGRESS -j DROP"]
    assert module.apply(plan, run=fake) == []
    module.check(plan, run=fake)


def test_apply_replaces_a_changed_interface_and_an_old_port_jump():
    module = _module()
    fake = FakeIptables()
    module.apply(_plan(module, ROSY_SITE_LAN_IFACE="eth0", ROSY_SITE_HTTPS_PORT="8443"), run=fake)
    plan = _plan(module, ROSY_SITE_LAN_IFACE="wlan0", ROSY_SITE_HTTPS_PORT="9443")
    module.apply(plan, run=fake)
    jumps = [line for line in fake.chains["DOCKER-USER"] if line.endswith("-j ROSY-SITE-INGRESS")]
    assert len(jumps) == 1 and "--ctorigdstport 9443" in jumps[0]
    assert fake.chains["ROSY-SITE-INGRESS"][0] == "-A ROSY-SITE-INGRESS -i wlan0 -j RETURN"
    module.check(plan, run=fake)


@pytest.mark.parametrize("damage", ["no_chain", "wrong_iface", "no_jump", "jump_after_return"])
def test_check_refuses_a_missing_or_ineffective_filter(damage):
    module = _module()
    plan = _plan(module)
    fake = FakeIptables()
    module.apply(plan, run=fake)
    if damage == "no_chain":
        del fake.chains["ROSY-SITE-INGRESS"]
    elif damage == "wrong_iface":
        fake.chains["ROSY-SITE-INGRESS"][0] = "-A ROSY-SITE-INGRESS -i eth9 -j RETURN"
    elif damage == "no_jump":
        fake.chains["DOCKER-USER"].pop(0)
    else:
        fake.chains["DOCKER-USER"].append(fake.chains["DOCKER-USER"].pop(0))
    with pytest.raises(RuntimeError, match="rosy-site-firewall.service"):
        module.check(plan, run=fake)


def test_missing_docker_user_chain_is_an_error_not_an_open_port():
    module = _module()
    with pytest.raises(RuntimeError, match="DOCKER-USER"):
        module.apply(_plan(module), run=FakeIptables(chains={}))


def test_loopback_bind_needs_no_interface_and_touches_no_rules():
    module = _module()
    for bind in ("", "127.0.0.1", "::1"):
        plan = module.site_plan({"ROSY_SITE_BIND_ADDRESS": bind}, assigned=lambda address: False)
        assert plan["mode"] == "loopback"
        fake = FakeIptables(chains={})
        assert module.apply(plan, run=fake) == [] and fake.calls == []
        module.check(plan, run=fake)


@pytest.mark.parametrize("env, reason", [
    ({"ROSY_SITE_BIND_ADDRESS": "0.0.0.0"}, "ROSY_SITE_LAN_IFACE is empty"),
    ({"ROSY_SITE_BIND_ADDRESS": "site-pc.local"}, "not an IP address"),
    ({"ROSY_SITE_BIND_ADDRESS": "0.0.0.0", "ROSY_SITE_LAN_IFACE": "wlan0 -j ACCEPT"},
     "invalid interface name"),
    ({"ROSY_SITE_BIND_ADDRESS": "0.0.0.0", "ROSY_SITE_LAN_IFACE": "wlan0",
      "ROSY_SITE_HTTPS_PORT": "70000"}, "not a TCP port"),
])
def test_preflight_rejects_configs_that_cannot_be_scoped(env, reason):
    module = _module()
    with pytest.raises(module.ConfigError, match=reason):
        module.site_plan(env, assigned=lambda address: True)


def test_preflight_refuses_a_literal_ip_the_host_no_longer_has():
    module = _module()
    env = {"ROSY_SITE_BIND_ADDRESS": "192.168.1.50", "ROSY_SITE_LAN_IFACE": "wlan0"}
    with pytest.raises(module.ConfigError, match="not assigned on this host.*0.0.0.0"):
        module.site_plan(env, assigned=lambda address: False)
    assert module.site_plan(env, assigned=lambda address: True)["mode"] == "address"


def test_address_probe_reports_an_address_this_host_does_not_own():
    # 192.0.2.0/24 is TEST-NET-1 (RFC 5737); no host is configured with it.
    assert _module().address_assigned("192.0.2.123") is False


def test_cli_dry_run_prints_rules_and_preflight_exits_2(tmp_path, capsys):
    module = _module()
    env = tmp_path / "site.env"
    env.write_text("# site\nROSY_SITE_BIND_ADDRESS=0.0.0.0\nROSY_SITE_HTTPS_PORT=8443\n"
                   "ROSY_SITE_LAN_IFACE='wlan0'\n", encoding="utf-8")
    assert module.main(["apply", "--env-file", str(env), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "-i wlan0 -j RETURN" in out and "--ctorigdstport 8443" in out
    env.write_text("ROSY_SITE_BIND_ADDRESS=192.0.2.123\nROSY_SITE_LAN_IFACE=wlan0\n",
                   encoding="utf-8")
    assert module.main(["check", "--env-file", str(env)]) == 2
    assert "not assigned on this host" in capsys.readouterr().err


def test_units_apply_after_docker_and_check_before_compose():
    firewall = (ROOT / "deploy/site/rosy-site-firewall.service").read_text(encoding="utf-8")
    stack = (ROOT / "deploy/site/rosy-site-stack.service").read_text(encoding="utf-8")
    assert "After=docker.service" in firewall and "PartOf=docker.service" in firewall
    assert "Before=rosy-site-stack.service" in firewall and "WantedBy=docker.service" in firewall
    assert "site-firewall.py apply --env-file /etc/rosy/site/site.env" in firewall
    check = stack.index("ExecStartPre=/usr/bin/python3 /opt/rosy/candidate/deploy/site/"
                        "site-firewall.py check --env-file /etc/rosy/site/site.env")
    assert check < stack.index("ExecStart=/usr/bin/docker compose")


def test_compose_and_env_never_require_a_lan_ip():
    import ipaddress
    import re

    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")
    env = (ROOT / "deploy/site/.env.example").read_text(encoding="utf-8")
    assert '- "${ROSY_SITE_BIND_ADDRESS:-127.0.0.1}:${ROSY_SITE_HTTPS_PORT:-8443}:8443"' in compose
    assert "ROSY_SITE_BIND_ADDRESS:?" not in compose
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
    assert "rosy-site-firewall.service" in lan and "DOCKER-USER" in lan and "--dry-run" in lan
    assert "needs no IP SAN" in lan
    assert "to the interface address" not in readme and "approved interface address" not in readme
    assert "ROSY_SITE_DISCOVERY_URL=" not in readme  # the bridge reads tls_host + port from site.env
    assert "ROSY_SITE_BIND_ADDRESS=0.0.0.0" in runbook and "ROSY_SITE_LAN_IFACE" in runbook
    assert "rosy-site-firewall.service" in runbook and "검색기 끊김" in runbook
