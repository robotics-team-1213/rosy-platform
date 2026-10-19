"""Account HTTPS preserves site discovery and independently filters tailnet ingress."""
import pytest

from test_site_firewall import FakeHost, _config, _module


def account_config():
    config = _config()
    config["x-rosy-site"]["account_https"] = "1"
    config["services"]["proxy"]["ports"].append({
        "host_ip": "0.0.0.0", "published": "443", "target": 443, "protocol": "tcp",
    })
    config["services"]["proxy"]["environment"] = {"ROSY_ACCOUNT_HTTPS_HOST": "account.example.com"}
    config["services"]["proxy"]["volumes"] = [{
        "type": "bind", "source": "/etc/rosy/account-tls",
        "target": "/run/rosy-account-tls", "read_only": True,
        "bind": {"create_host_path": False},
    }]
    return config


def test_account_ingress_keeps_primary_discovery_and_both_filters(tmp_path):
    module = _module()
    config = account_config()
    settings = module.compose_settings(config)
    plan = module.site_plan(settings, exists=lambda name: True)
    host = FakeHost(config)
    module.apply(plan, host)
    module.check(plan, host)
    assert "-A ROSY-ACCOUNT-INGRESS -i tailscale0 -j RETURN" in host.chains["ROSY-ACCOUNT-INGRESS"]
    assert not any("wlan0" in row for row in host.chains["ROSY-ACCOUNT-INGRESS"])
    assert any("--dport 8443 -j ROSY-SITE-INGRESS" in row for row in host.chains["PREROUTING"])
    assert any("--dport 443 -j ROSY-ACCOUNT-INGRESS" in row for row in host.chains["PREROUTING"])
    module.write_public_env(settings, tmp_path / "public.env")
    assert "ROSY_SITE_HTTPS_PORT=8443\n" in (tmp_path / "public.env").read_text()
    module.apply(plan, host)
    module.check(plan, host)
    primary = module.site_plan(module.compose_settings(_config()), exists=lambda name: True)
    module.apply(primary, host)
    module.check(primary, host)
    assert not any("ROSY-ACCOUNT-INGRESS" in row for row in host.chains["PREROUTING"])


@pytest.mark.parametrize("change", ["disabled", "extra", "literal", "target", "hostname",
                                    "missing_mount", "writable_mount", "wrong_type",
                                    "wrong_source", "duplicate_mount"])
def test_account_ingress_refuses_ambiguous_or_unprotected_config(change):
    config = account_config()
    proxy = config["services"]["proxy"]
    if change == "disabled":
        del config["x-rosy-site"]["account_https"]
    elif change == "extra":
        proxy["ports"].append({"host_ip": "0.0.0.0", "published": "9443", "target": 9443})
    elif change == "literal":
        proxy["ports"][1]["host_ip"] = "192.0.2.1"
    elif change == "target":
        proxy["ports"][1]["target"] = 8443
    elif change == "hostname":
        proxy["environment"]["ROSY_ACCOUNT_HTTPS_HOST"] = ""
    elif change == "missing_mount":
        proxy["volumes"] = []
    elif change == "writable_mount":
        proxy["volumes"][0]["read_only"] = False
    elif change == "wrong_type":
        proxy["volumes"][0]["type"] = "volume"
    elif change == "wrong_source":
        proxy["volumes"][0]["source"] = "/other/tls"
    elif change == "duplicate_mount":
        proxy["volumes"].append(dict(proxy["volumes"][0]))
    with pytest.raises(ValueError):
        _module().compose_settings(config)


def test_missing_account_filter_fails_periodic_check():
    module = _module()
    config = account_config()
    plan = module.site_plan(module.compose_settings(config), exists=lambda name: True)
    host = FakeHost(config)
    module.apply(plan, host)
    host.chains["ROSY-ACCOUNT-INGRESS"] = []
    with pytest.raises(RuntimeError, match="ROSY-ACCOUNT-INGRESS"):
        module.check(plan, host)


def test_normalized_tcp_jumps_are_stable_and_wrong_chain_is_repaired():
    module = _module()
    config = account_config()
    plan = module.site_plan(module.compose_settings(config), exists=lambda name: True)
    host = FakeHost(config)
    module.apply(plan, host)
    host.chains["PREROUTING"] = [row.replace("-p tcp ", "-p tcp -m tcp ")
                                  for row in host.chains["PREROUTING"]]
    module.check(plan, host)
    assert module.apply(plan, host) == []
    host.chains["PREROUTING"] = [row.replace("--dport 443 -j ROSY-ACCOUNT-INGRESS",
                                                "--dport 443 -j ROSY-SITE-INGRESS")
                                  for row in host.chains["PREROUTING"]]
    with pytest.raises(RuntimeError):
        module.check(plan, host)
    module.apply(plan, host)
    module.check(plan, host)


@pytest.mark.parametrize("bind", ["0.0.0.0", "127.0.0.1"])
def test_disabling_account_keeps_live_listener_protected_until_stopped(bind):
    module = _module()
    config = account_config()
    config["services"]["proxy"]["ports"][0]["host_ip"] = bind
    host = FakeHost(config)
    plan = module.site_plan(module.compose_settings(config), exists=lambda name: True)
    module.apply(plan, host)
    primary = module.site_plan(module.compose_settings(_config(bind=bind)), exists=lambda name: True)
    before = {chain: list(rows) for chain, rows in host.chains.items()}
    host.published443 = True
    with pytest.raises(RuntimeError, match="stop the Account proxy"):
        module.apply(primary, host)
    assert host.chains == before
    host.published443 = False
    module.apply(primary, host)
    module.check(primary, host)
    assert not any("ROSY-ACCOUNT-INGRESS" in row for row in host.chains["PREROUTING"])


def test_preflight_checks_frontend_system_trust_without_replacing_backend_ca(tmp_path, monkeypatch):
    module = _module()
    config = account_config()
    host = FakeHost(config)
    module.apply(module.site_plan(module.compose_settings(config), exists=lambda name: True), host)
    calls = []
    monkeypatch.setattr(module, "verify_site_certificate", lambda *args: calls.append(args))
    env = tmp_path / "site.env"
    env.write_text("")
    assert module.main(["check", "--verify-certs", "--env-file", str(env)], run=host) == 0
    assert str(calls[0][2]) == "/s/site-ca.crt"
    assert calls[1][2:] == (None, "account.example.com")
