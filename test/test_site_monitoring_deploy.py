"""D-936: opt-in Monitoring runs beside the site stack, independent of Fleet and unpublished."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "deploy/site"


def _overlay():
    return yaml.safe_load((SITE / "compose.monitoring.yaml").read_text(encoding="utf-8"))


def test_monitoring_service_is_hardened_unpublished_and_reuses_the_fleet_image():
    overlay = _overlay()
    assert overlay["x-rosy-site"] == {"monitoring": "1"}
    assert set(overlay["services"]) == {"monitoring", "proxy"}
    service = overlay["services"]["monitoring"]
    assert service["image"] == "rosy-site-fleet:${ROSY_SITE_IMAGE_TAG:-local}"
    assert "ports" not in service and "entrypoint" not in service and "depends_on" not in service
    assert service["networks"] == ["site_backend"]
    assert service["read_only"] is True and service["cap_drop"] == ["ALL"]
    assert set(service["cap_add"]) == {"SETUID", "SETGID"}  # secret_exec drops to uid 10001
    assert "no-new-privileges:true" in service["security_opt"]
    command = service["command"]
    assert command[:4] == ["--", "python3", "-m", "rosy.monitoring"]
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert command[command.index("--state-dir") + 1] == "/var/lib/rosy-monitoring"
    environment = service["environment"]
    assert "fleet" not in environment["PYTHONPATH"]
    credential_paths = json.loads(environment["ROSY_CREDENTIAL_PATHS"])
    assert set(credential_paths) == {"MONITORING_SITE_READ", "MONITORING_FLEET_UPSTREAM"}
    binds = [v for v in service["volumes"] if isinstance(v, dict)]
    assert all(v["type"] == "bind" and v["read_only"] and not v["bind"]["create_host_path"] for v in binds)
    assert {Path(p).parent.as_posix() for p in credential_paths.values()} == {"/run/rosy-monitoring-secrets"}
    assert "/var/lib/rosy-host-guard:/var/lib/rosy-host-guard:ro" in service["volumes"]
    assert "/var/lib/rosy-host-state:/var/lib/rosy-host-state:ro" in service["volumes"]
    assert "monitoring_state:/var/lib/rosy-monitoring" in service["volumes"]


def test_proxy_only_gains_the_signed_route_file_and_never_waits_for_monitoring():
    proxy = _overlay()["services"]["proxy"]
    assert set(proxy) == {"labels", "volumes"}
    assert proxy["labels"] == {"org.rosy.site-monitoring-caddy-sha256": "unbuilt"}
    [mount] = proxy["volumes"]
    assert mount["source"] == "./Caddyfile.monitoring" and mount["read_only"] is True
    assert re.fullmatch(r"/etc/caddy/monitoring/[a-z]+\.caddy", mount["target"])


def test_routes_are_imported_inside_the_site_before_the_fleet_catch_all():
    caddy = (SITE / "Caddyfile").read_text(encoding="utf-8")
    route = caddy.index("route {")
    imported = caddy.index("import /etc/caddy/monitoring/*.caddy")
    assert route < imported < caddy.index("reverse_proxy https://fleet:")
    routes = (SITE / "Caddyfile.monitoring").read_text(encoding="utf-8")
    for line in ("redir /monitoring /monitoring/ 308", "handle_path /monitoring/* {",
                 "handle /api/monitoring/* {", "handle /monitoring-health {", "rewrite * /health"):
        assert line in routes
    assert set(re.findall(r"reverse_proxy (\S+)", routes)) == {"monitoring:8786"}
    assert "header_up" not in routes  # the reader key passes through, nothing is added


def test_fleet_image_carries_monitoring_without_putting_it_on_fleets_import_path():
    dockerfile = (SITE / "Dockerfile.fleet").read_text(encoding="utf-8")
    fleet_path = re.search(r"PYTHONPATH=(\S+)", dockerfile).group(1)
    assert "monitoring" not in fleet_path
    assert "COPY operations/monitoring/src/ /opt/rosy/src/operations/monitoring/" in dockerfile
    assert "-m rosy.monitoring.web_assets" in dockerfile and "--output /opt/rosy/monitoring-web" in dockerfile
    assert "install -d -o 10001 -g 10001 -m 0700 /var/lib/rosy-monitoring" in dockerfile
    ignore = (SITE / "Dockerfile.fleet.dockerignore").read_text(encoding="utf-8").splitlines()
    assert {"!operations/monitoring/src/**", "!applications/monitoring/web/**", "!shared/web/**"} <= set(ignore)


def test_compose_renders_monitoring_only_with_its_overlay(tmp_path):
    docker = shutil.which("docker")
    if docker is None or subprocess.run([docker, "compose", "version"], capture_output=True).returncode:
        pytest.skip("Docker Compose CLI is required for interpolation acceptance")
    base = tmp_path / "base.yaml"
    base.write_text("services:\n  proxy:\n    image: example.invalid/proxy:unused\n"
                    "networks:\n  site_backend:\n    internal: true\n"
                    "secrets:\n  site_ca:\n    file: /dev/null\n", encoding="utf-8")
    shutil.copy(SITE / "Caddyfile.monitoring", tmp_path / "Caddyfile.monitoring")
    overlay = tmp_path / "compose.monitoring.yaml"
    shutil.copy(SITE / "compose.monitoring.yaml", overlay)
    env_file = tmp_path / "site.env"
    site_env = {"ROSY_SITE_MONITORING_CONFIG": tmp_path / "monitoring.yaml",
                "ROSY_SITE_MONITORING_SECRETS_DIR": tmp_path / "keys", "ROSY_SITE_IMAGE_TAG": "a" * 40}
    env_file.write_text("".join(f"{k}={v}\n" for k, v in site_env.items()), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ROSY_")}

    def services(*files):
        args = [docker, "compose", "--env-file", str(env_file), *files, "config", "--format", "json"]
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)["services"]
    assert set(services("-f", str(base))) == {"proxy"}
    rendered = services("-f", str(base), "-f", str(overlay))
    assert set(rendered) == {"proxy", "monitoring"}
    assert rendered["monitoring"]["image"] == "rosy-site-fleet:" + "a" * 40
    assert not rendered["monitoring"].get("ports")
