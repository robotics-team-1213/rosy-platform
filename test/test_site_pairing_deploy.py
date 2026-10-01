"""D-341 camera pairing wiring in deploy/site: off by default, one overlay turns it on."""

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "deploy/site"
SYNC_ENV = "ROSY_SITE_PAIRING_SYNC_TOKEN"
OTHER_TOKEN_SECRETS = {"registry_token", "phone_ingress_token", "fleet_sighting_token",
                       "discovery_token", "vision_preview_secret", "robot_credential_key"}


def _load(name):
    return yaml.safe_load((SITE / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def base():
    return _load("compose.yaml")


@pytest.fixture(scope="module")
def overlay():
    return _load("compose.pairing.yaml")


def _paths(service):
    return json.loads(service["environment"]["ROSY_CREDENTIAL_PATHS"])


def _flags(command):
    return {word: command[i + 1] for i, word in enumerate(command[:-1]) if word.startswith("--")}


def test_base_compose_has_no_pairing_so_default_behaviour_is_unchanged(base):
    text = (SITE / "compose.yaml").read_text(encoding="utf-8")
    assert "pairing" not in text and SYNC_ENV not in text
    for service in ("fleet", "vision"):
        assert not [w for w in base["services"][service]["command"] if "pairing" in str(w)]


def test_overlay_only_touches_fleet_and_vision(overlay):
    assert set(overlay) == {"services", "secrets"}
    assert set(overlay["services"]) == {"fleet", "vision"}


@pytest.mark.parametrize("name", ["fleet", "vision"])
def test_overlay_command_is_the_base_command_plus_pairing_flags(base, overlay, name):
    """Compose replaces `command` wholesale, so the overlay repeats it; this pins them together."""
    base_cmd, cmd = base["services"][name]["command"], overlay["services"][name]["command"]
    assert cmd[:len(base_cmd)] == base_cmd
    assert all("pairing" in w or w.startswith(("https://", "/run/secrets/", "ROSY_", "${"))
               for w in cmd[len(base_cmd):])


@pytest.mark.parametrize("name", ["fleet", "vision"])
def test_overlay_credential_paths_are_the_base_paths_plus_the_sync_token(base, overlay, name):
    base_paths, paths = _paths(base["services"][name]), _paths(overlay["services"][name])
    assert paths == {**base_paths, SYNC_ENV: "/run/secrets/pairing_sync_token"}
    assert overlay["services"][name]["secrets"] == ["pairing_sync_token"]


def test_fleet_enables_pairing_with_the_site_ca_and_tls_host(overlay):
    flags = _flags(overlay["services"]["fleet"]["command"])
    assert flags["--pairing-ca"] == "/run/secrets/site_ca"
    assert flags["--pairing-tls-host"] == "${ROSY_SITE_TLS_HOST:?set ROSY_SITE_TLS_HOST}"
    assert flags["--pairing-sync-token-env"] == SYNC_ENV


def test_vision_syncs_over_https_with_the_site_ca(overlay):
    flags = _flags(overlay["services"]["vision"]["command"])
    assert flags["--pairing-sync-url"] == "https://fleet:8090"
    assert flags["--pairing-sync-ca"] == "/run/secrets/site_ca"
    assert flags["--pairing-sync-token-env"] == SYNC_ENV
    assert "site_ca" in _load("compose.yaml")["services"]["vision"]["secrets"]


def test_sync_token_is_its_own_secret_file_not_shared_with_any_other_credential(base, overlay):
    """D-302 style: a distinct secret name, distinct file, mounted only in Fleet and Vision."""
    sync_file = overlay["secrets"]["pairing_sync_token"]["file"]
    assert sync_file.endswith("/pairing_sync_token")
    assert "pairing_sync_token" not in base["secrets"]
    others = {v["file"] for v in base["secrets"].values()}
    assert sync_file not in others
    assert "pairing_sync_token" not in OTHER_TOKEN_SECRETS
    for name in ("fleet", "vision"):
        paths = _paths(overlay["services"][name])
        users = [env for env, path in paths.items() if path == "/run/secrets/pairing_sync_token"]
        assert users == [SYNC_ENV]
    assert "proxy" not in overlay["services"]


def test_pairing_template_is_a_placeholder_and_the_example_names_both_credential_kinds():
    template = (SITE / "pairing-sync-token.template.txt").read_text(encoding="utf-8")
    assert template.startswith("<replace-with-") and len(template.strip().splitlines()) == 1
    discovery = (SITE / "discovery-token.template.txt").read_text(encoding="utf-8")
    assert template != discovery
    cameras = (SITE / "site-cameras.yaml.example").read_text(encoding="utf-8")
    assert "credential: static" in cameras and "credential: paired" in cameras


def test_env_example_declares_pairing_off_in_its_own_block():
    text = (SITE / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^ROSY_SITE_PAIRING=$", text, re.M)
    assert re.search(r"^ROSY_SITE_PAIRING_COMPOSE=$", text, re.M)
    assert "compose.pairing.yaml" in text


def test_candidate_ships_the_overlay_and_template():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bc", SITE / "build_candidate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {"compose.pairing.yaml", "pairing-sync-token.template.txt"} <= set(module.DEPLOY_FILES)

