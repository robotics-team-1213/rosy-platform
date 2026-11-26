"""Signed World image, data placement, and Fleet heartbeat contracts."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
import yaml

from applications.world import bridge_real_fleet, serve
from deploy.site.verify_candidate import CandidateVerificationError, WORLD_DEPLOYMENT_FILES, verify_candidate
from test_site_candidate_verifier import COMMIT, TEST_KEY_ID, _add_monitoring, _write_images_tar, candidate  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "deploy/site"


def test_world_bridge_imports_in_a_fresh_package_process():
    subprocess.run(
        [sys.executable, "-E", "-B", "-c", "from applications.world import bridge_real_fleet"],
        cwd=ROOT,
        check=True,
        timeout=10,
    )


@pytest.mark.parametrize("removed", [(), WORLD_DEPLOYMENT_FILES, (WORLD_DEPLOYMENT_FILES[0],),
                                     (WORLD_DEPLOYMENT_FILES[1],)])
@pytest.mark.parametrize("inspect_images", [False, True])
def test_verifier_recognizes_signed_world_and_legacy_candidates(candidate, removed, inspect_images):
    root, runner, loaded_ids, trusted_key = candidate
    if not removed:
        _add_monitoring(candidate)
    release = root / "release.json"
    manifest = json.loads(release.read_text())
    if not removed:
        archive = root / "images.tar"
        archive_ids = _write_images_tar(archive, services=(*manifest["images"], "world"))
        loaded_ids["world"] = archive_ids["world"][0]
        sbom = root / "sbom/world.spdx"
        sbom.write_text("World SPDX fixture", encoding="utf-8")
        manifest["images"]["world"] = {
            "reference": f"rosy-site-world:{COMMIT}", "image_id": loaded_ids["world"],
            "platform": "linux/amd64", "sbom": "sbom/world.spdx",
            "sbom_sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
        }
        manifest["image_archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    for name in removed:
        del manifest["deployment_file_sha256"][name]
        (root / "deploy/site" / name).unlink()
    release.write_text(json.dumps(manifest), encoding="utf-8")

    def verify():
        return verify_candidate(root, trusted_key_id=TEST_KEY_ID, trusted_public_key=trusted_key,
                                runner=runner, inspect_loaded_images=inspect_images)

    if len(removed) == 1:
        with pytest.raises(CandidateVerificationError, match="required deployment file"):
            verify()
    else:
        summary = verify()
        assert summary["world"] is (not removed)
        assert ("world" in summary["verified_images"]) is (not removed)
        assert ("world" in summary["image_references"]) is (not removed)


def test_world_dockerfile_has_a_restricted_context():
    dockerfile = (SITE / "Dockerfile.world").read_text(encoding="utf-8")
    for line in (
        "FROM python:3.12-slim", "import serve, bridge_real_fleet, world_state, world_env_adapter",
        "USER 10001:10001", 'ENTRYPOINT ["python3", "/opt/rosy/secret_exec.py"]',
        "COPY shared/web/ /opt/rosy/world/web/common/",
    ):
        assert line in dockerfile
    assert (SITE / "Dockerfile.world.dockerignore").read_text(encoding="utf-8").splitlines() == [
        "**", "!deploy/site/secret_exec.py", "!applications/world/*.py", "!applications/world/web/**",
        "!shared/web/**", "!tools/sim/world_env_adapter.py", "**/.pytest_cache", "**/__pycache__",
    ]


def test_world_overlay_is_internal_and_uses_secret_bootstrap():
    services = yaml.safe_load((SITE / "compose.world.yaml").read_text(encoding="utf-8"))["services"]
    _check_services(services, "rosy-site-world:${ROSY_SITE_IMAGE_TAG:-local}")
    assert services["proxy"]["labels"]["org.rosy.site-world-caddy-sha256"] == "unbuilt"
    assert services["proxy"]["volumes"][0]["source"] == "./Caddyfile.world"


def _check_services(services, image):
    for name in ("world", "world-real-bridge"):
        service = services[name]
        assert service["image"] == image
        assert not service.get("ports") and "build" not in service
        assert service["read_only"] and service["cap_drop"] == ["ALL"]
    world = services["world"]
    assert world["entrypoint"] == ["python3", "-B", "/opt/rosy/world/serve.py"]
    assert "--data-dir" in world["command"]
    bridge = services["world-real-bridge"]
    # Compose can render an inherited image entrypoint as null.
    assert bridge.get("entrypoint") is None
    assert bridge["command"][:4] == ["--", "python3", "-B", "/opt/rosy/world/bridge_real_fleet.py"]
    assert set(bridge["cap_add"]) == {"SETUID", "SETGID"}
    assert json.loads(bridge["environment"]["ROSY_CREDENTIAL_PATHS"]) == {
        "ROSY_FLEET_TOKEN": "/run/secrets/world_fleet_viewer_token",
    }
    assert bridge["command"][-2:] == ["--heartbeat-file", "/tmp/bridge.alive"]
    assert "getmtime('/tmp/bridge.alive') < 15" in bridge["healthcheck"]["test"][-1]


def test_compose_renders_world_overlay(tmp_path):
    if not shutil.which("docker") or subprocess.run(
        ["docker", "compose", "version"], capture_output=True,
    ).returncode:
        pytest.skip("Docker Compose unavailable")
    base = tmp_path / "compose.yaml"
    base.write_text(
        yaml.safe_dump({"services": {"fleet": {"image": "test"}, "proxy": {"image": "test"}},
                        "networks": {"site_backend": {}}, "secrets": {"site_ca": {"file": "/dev/null"}}}),
        encoding="utf-8",
    )
    overlay = tmp_path / "compose.world.yaml"
    shutil.copyfile(SITE / overlay.name, overlay)
    result = subprocess.run(
        ["docker", "compose", "-f", str(base), "-f", str(overlay), "config", "--format", "json"],
        env={**os.environ, "ROSY_SITE_IMAGE_TAG": "test", "ROSY_WORLD_BUNDLE_DIR": str(tmp_path),
             "ROSY_SITE_SECRETS_DIR": str(tmp_path)}, check=True, capture_output=True, text=True,
    )
    _check_services(json.loads(result.stdout)["services"], "rosy-site-world:test")


def test_world_serves_web_and_only_mounted_data(tmp_path):
    web, data = tmp_path / "web", tmp_path / "mounted"
    web.mkdir()
    data.mkdir()
    (web / "index.html").write_text("signed frontend", encoding="utf-8")
    (web / "data").mkdir()
    (web / "data/local.txt").write_text("unexpected fallback", encoding="utf-8")
    (data / "public.json").write_text('{"signed_ui":true}', encoding="utf-8")
    (data / "manifest.json").write_text(json.dumps({"inputs": {"site_active.json": {"sha256": "a" * 64}}}))
    (data / "site-map.json").write_text(json.dumps({"sha256": "b" * 64, "version": 3}))
    (data / "factory-timeline.json").write_text('{"run_id":"mounted-replay"}', encoding="utf-8")
    with serve.make_server(web, port=0, data_dir=data) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base, timeout=2) as reply:
                assert reply.read() == b"signed frontend"
            with urlopen(base + "/data/public.json?v=1", timeout=2) as reply:
                assert json.load(reply) == {"signed_ui": True}
            with urlopen(base + "/manifest.json", timeout=2) as reply:
                assert "site_active.json" in json.load(reply)["inputs"]
            with urlopen(base + "/api/worlds", timeout=2) as reply:
                registry = json.load(reply)
                assert any(world["run_id"] == "mounted-replay" for world in registry["worlds"])
                assert registry["canonical"]["site_map_sha256"] == "a" * 64
                assert registry["canonical"]["site_map_body_sha256"] == "b" * 64
                assert registry["canonical"]["site_map_version"] == 3
            for path in ("/data/%2e%2e/index.html", "/data/local.txt"):
                with pytest.raises(HTTPError) as error:
                    urlopen(base + path, timeout=2)
                assert error.value.code == 404
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_world_data_cannot_serve_outside_symlinks(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    try:
        (data / "escape.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with serve.make_server(tmp_path, port=0, data_dir=data) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with pytest.raises(HTTPError) as error:
                urlopen(f"http://127.0.0.1:{server.server_port}/data/escape.txt", timeout=2)
            assert error.value.code == 404
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_bridge_heartbeat_advances_only_when_fleet_responds(tmp_path, monkeypatch):
    heartbeat = tmp_path / "bridge.alive"
    token_file = tmp_path / "token"
    token_file.write_text("file-viewer", encoding="utf-8")
    monkeypatch.setenv("ROSY_FLEET_TOKEN", "injected-viewer")
    monkeypatch.setattr(sys, "argv", [
        "bridge", "--fleet-url", "https://fleet", "--worlds-dir", str(tmp_path),
        "--heartbeat-file", str(heartbeat), "--fleet-token-file", str(token_file), "--once",
    ])
    response = [OSError("unreachable"), {}, {}, OSError("unreachable")]
    tokens = []

    def fetch(url, *, token, **kwargs):
        tokens.append(token)
        result = response.pop(0)
        if isinstance(result, OSError):
            raise result
        return result

    monkeypatch.setattr(bridge_real_fleet, "_fetch_fleet_state", fetch)
    monkeypatch.setattr(bridge_real_fleet, "_fetch_optional", lambda *args: None)
    bridge_real_fleet.main()
    assert not heartbeat.exists()
    bridge_real_fleet.main()
    assert abs(float(heartbeat.read_text()) - time.time()) < 5
    heartbeat.write_text("1\n", encoding="utf-8")
    monkeypatch.delenv("ROSY_FLEET_TOKEN")
    bridge_real_fleet.main()
    fresh = heartbeat.read_bytes()
    assert float(fresh) > 1
    bridge_real_fleet.main()
    assert heartbeat.read_bytes() == fresh
    assert tokens == ["injected-viewer", "injected-viewer", "file-viewer", "file-viewer"]
    monkeypatch.setenv("ROSY_FLEET_TOKEN_FILE", str(token_file))
    assert bridge_real_fleet._read_secret("ROSY_FLEET_TOKEN", "ROSY_FLEET_TOKEN_FILE") == "file-viewer"
