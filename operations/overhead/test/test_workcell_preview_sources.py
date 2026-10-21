"""Workcell cameras join direct ingest without becoming calibrated map sources."""

import asyncio
import hashlib
import time

import pytest
import yaml

from rosy_vision import cli
from test_vision_cli import SYNC_FLAGS, _configs


def test_manifest_environment_default_and_explicit_cli_precedence(tmp_path, monkeypatch):
    configured = tmp_path / "configured.yaml"
    monkeypatch.setenv("ROSY_WORKCELL_OBSERVATIONS", str(configured))
    assert cli.parse_args(["vision"]).workcell_observations == configured
    other = tmp_path / "explicit.yaml"
    assert cli.parse_args(["vision", "--workcell-observations", str(other)]).workcell_observations == other
    monkeypatch.setenv("ROSY_WORKCELL_OBSERVATIONS", "")
    with pytest.raises(SystemExit):
        cli.parse_args(["vision"])


@pytest.fixture
def manifest(tmp_path):
    data = {
        "schema": "rosy.workcell-observations/1",
        "workcells": [{
            "workcell_id": "bench", "label": "Dual arm bench",
            "arms": [{
                "source_id": "arm_left", "arm_id": "left", "label": "Left arm",
                "board_id": "board-left", "joint_topic": "/omx_commissioning/left/joint_states",
                "joint_names": ["joint1"], "token_env": "ROSY_ARM_LEFT",
                "credential_sha256": hashlib.sha256(b"left-arm-token").hexdigest(),
            }],
            "cameras": [{
                "source_id": "bench_overhead", "label": "Bench overhead", "role": "overhead",
                "arm_id": None, "image_topic": "/bench/image_raw",
                "device_path": "/dev/v4l/by-id/bench-camera", "token_env": "ROSY_CAMERA_BENCH",
                "credential_sha256": hashlib.sha256(b"bench-camera-token").hexdigest(),
            }, {
                "source_id": "left_wrist", "label": "Left wrist", "role": "wrist",
                "arm_id": "left", "image_topic": "/left/image_raw",
                "device_path": "/dev/v4l/by-id/wrist-camera", "token_env": "ROSY_CAMERA_WRIST",
                "credential_sha256": hashlib.sha256(b"wrist-camera-token").hexdigest(),
            }],
        }],
    }
    path = tmp_path / "workcell-observations.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path, data, {"ROSY_CAMERA_BENCH": "bench-camera-token", "ROSY_CAMERA_WRIST": "wrist-camera-token"}


def _args(path, *extra):
    return cli.parse_args(["vision", "--workcell-observations", str(path), *extra])


def test_preview_only_ingest_resolves_camera_secrets_without_arm_credentials(manifest):
    path, _, env = manifest
    ingest, sync = cli._vision_ingest(_args(path), [], environ=env)
    assert ingest.source_tokens == {"bench_overhead": "bench-camera-token", "left_wrist": "wrist-camera-token"}
    assert ingest.paired is None
    assert sync is None
    assert ingest.map_paint is None


def test_preview_and_calibrated_and_paired_sources_share_ingest(manifest, tmp_path):
    path, _, env = manifest
    configs, calibrated_env = _configs(tmp_path)
    ingest, sync = cli._vision_ingest(_args(path, *SYNC_FLAGS), configs, environ=env | calibrated_env)
    assert ingest.source_tokens == {
        "bench_static": "phone-bench", "bench_overhead": "bench-camera-token", "left_wrist": "wrist-camera-token",
    }
    assert ingest.paired.sources == {"ceiling_north"}
    assert sync["token"] == calibrated_env["ROSY_PAIRING_SYNC"]
    assert [config.camera.source_id for config in configs] == ["bench_static", "ceiling_north"]


@pytest.mark.parametrize("source_id", ["bench_static", "ceiling_north"])
def test_preview_source_collision_refuses_start_before_overwriting_credentials(manifest, tmp_path, source_id):
    path, data, env = manifest
    data["workcells"][0]["cameras"][0]["source_id"] = source_id
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    configs, calibrated_env = _configs(tmp_path)
    with pytest.raises(ValueError, match="source|collision|duplicate"):
        cli._vision_ingest(_args(path, *SYNC_FLAGS), configs, environ=env | calibrated_env)


@pytest.mark.parametrize("secret", [
    "ROSY_PHONE_BENCH", "ROSY_FLEET_BENCH", "ROSY_FLEET_NORTH", "ROSY_PAIRING_SYNC",
    "ROSY_VISION_PREVIEW_SECRET", "ROSY_CAMERA_WRIST",
])
def test_preview_camera_token_cannot_reuse_any_other_vision_secret(manifest, tmp_path, secret):
    path, data, env = manifest
    configs, calibrated_env = _configs(tmp_path)
    env |= calibrated_env | {"ROSY_VISION_PREVIEW_SECRET": "preview-" + "x" * 32}
    env["ROSY_CAMERA_BENCH"] = env[secret]
    data["workcells"][0]["cameras"][0]["credential_sha256"] = hashlib.sha256(env[secret].encode()).hexdigest()
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="differ|unique|reuse|manifest"):
        cli._vision_ingest(_args(path, *SYNC_FLAGS), configs, environ=env)


@pytest.mark.parametrize("camera_env", ["ROSY_CAMERA_BENCH", "ROSY_CAMERA_WRIST"])
def test_camera_raw_token_must_match_its_declared_fingerprint(manifest, camera_env):
    path, _, env = manifest
    env[camera_env] = "wrong-camera-secret"
    with pytest.raises(ValueError) as caught:
        cli._vision_ingest(_args(path), [], environ=env)
    assert "wrong-camera-secret" not in str(caught.value)


@pytest.mark.parametrize("secret", [
    "ROSY_PHONE_BENCH", "ROSY_FLEET_BENCH", "ROSY_FLEET_NORTH",
    "ROSY_PAIRING_SYNC", "ROSY_VISION_PREVIEW_SECRET",
])
def test_arm_fingerprint_cannot_reuse_a_known_vision_secret_without_arm_env(manifest, tmp_path, secret):
    path, data, env = manifest
    configs, calibrated_env = _configs(tmp_path)
    env |= calibrated_env | {"ROSY_VISION_PREVIEW_SECRET": "preview-" + "x" * 32}
    data["workcells"][0]["arms"][0]["credential_sha256"] = hashlib.sha256(env[secret].encode()).hexdigest()
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert "ROSY_ARM_LEFT" not in env
    with pytest.raises(ValueError):
        cli._vision_ingest(_args(path, *SYNC_FLAGS), configs, environ=env)


def test_future_paired_credential_cannot_reuse_arm_fingerprint_without_arm_env(manifest, tmp_path):
    path, _, env = manifest
    configs, calibrated_env = _configs(tmp_path)
    assert "ROSY_ARM_LEFT" not in env
    ingest, _ = cli._vision_ingest(_args(path, *SYNC_FLAGS), configs, environ=env | calibrated_env)
    digest = hashlib.sha256(b"left-arm-token").digest()
    ingest.paired.replace_rows([("ceiling_north", digest, "reused-arm", time.time() + 3600)])
    assert ingest.paired.check("ceiling_north", digest) == ("unknown", None)


def test_preview_camera_token_is_required_without_exposing_credentials(manifest):
    path, _, env = manifest
    del env["ROSY_CAMERA_WRIST"]
    with pytest.raises(ValueError) as caught:
        cli._vision_ingest(_args(path), [], environ=env)
    assert "ROSY_CAMERA_WRIST" in str(caught.value)
    assert "bench-camera-token" not in str(caught.value)


@pytest.mark.parametrize("invalid", ["unknown_field", "oversized_source", "invalid_topic", "invalid_arm"])
def test_preview_loader_uses_the_strict_shared_manifest(manifest, invalid):
    path, data, env = manifest
    camera = data["workcells"][0]["cameras"][0]
    if invalid == "unknown_field":
        camera["map_id"] = "invented-map"
    elif invalid == "oversized_source":
        camera["source_id"] = "x" * 33
    elif invalid == "invalid_topic":
        camera["image_topic"] = "/commands/image_raw"
    else:
        camera["arm_id"] = "missing"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError):
        cli._vision_ingest(_args(path), [], environ=env)


@pytest.mark.parametrize("secret", [
    "ROSY_CAMERA_BENCH", "ROSY_CAMERA_WRIST", "ROSY_PHONE_BENCH", "ROSY_FLEET_BENCH",
    "ROSY_FLEET_NORTH", "ROSY_PAIRING_SYNC", "ROSY_VISION_PREVIEW_SECRET",
])
def test_dynamic_paired_credential_cannot_reuse_another_vision_bearer(manifest, tmp_path, secret):
    path, _, env = manifest
    configs, calibrated_env = _configs(tmp_path)
    env |= calibrated_env | {"ROSY_VISION_PREVIEW_SECRET": "preview-" + "x" * 32}
    ingest, _ = cli._vision_ingest(_args(path, *SYNC_FLAGS), configs, environ=env)
    digest = hashlib.sha256(env[secret].encode("utf-8")).digest()
    ingest.paired.replace_rows([("ceiling_north", digest, "issued-camera", time.time() + 3600)])
    assert ingest.paired.check("ceiling_north", digest)[0] != "ok"


def test_reserved_paired_digest_rejects_its_source_and_keeps_other_sources():
    from rosy_vision.pairing_sync import PairedCredentials

    reserved = hashlib.sha256(b"preview-camera-token").digest()
    good = hashlib.sha256(b"issued-phone-token").digest()
    credentials = PairedCredentials(["north", "south"], forbidden_digests={reserved})
    credentials.replace_rows([
        ("north", good, "north-good", time.time() + 3600),
        ("north", reserved, "north-reused", time.time() + 3600),
        ("south", good, "south-good", time.time() + 3600),
        ("unconfigured", good, "unknown", time.time() + 3600),
    ])
    assert credentials.available()
    assert credentials.check("north", reserved) == ("unknown", None)
    assert credentials.check("north", good) == ("unknown", None)
    assert credentials.check("south", good) == ("ok", "south-good")
    assert credentials.check("unconfigured", good) == ("unknown", None)


def test_paired_digest_guard_is_optional_for_existing_callers():
    from rosy_vision.pairing_sync import PairedCredentials

    digest = hashlib.sha256(b"issued-phone-token").digest()
    credentials = PairedCredentials(["north"])
    credentials.replace_rows([("north", digest, "issued", time.time() + 3600)])
    assert credentials.check("north", digest) == ("ok", "issued")


@pytest.mark.parametrize("combined", [False, True])
def test_pipeline_starts_without_building_workers_or_trackers_for_preview_sources(
        manifest, tmp_path, monkeypatch, combined):
    path, _, env = manifest
    argv = ["vision", "--workcell-observations", str(path), "--track"]
    if combined:
        _, calibrated_env = _configs(tmp_path, paired=False)
        env |= calibrated_env
        argv += ["--config", str(tmp_path / "site-cameras.yaml")]
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    started = []
    workers = []
    trackers = []
    real_worker, real_tracker = cli.VisionWorker, cli.TrackWorker

    def worker(**kwargs):
        instance = real_worker(**kwargs)
        workers.append(instance)
        return instance

    def tracker(**kwargs):
        instance = real_tracker(**kwargs)
        trackers.append(instance)
        return instance

    class Listener:
        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def start(ingest, *args, **kwargs):
        started.append(ingest)
        return Listener()

    class StopPipeline(Exception):
        pass

    async def stop_after_first_iteration(_):
        raise StopPipeline

    monkeypatch.setattr(cli.IngestServer, "start", start)
    monkeypatch.setattr(cli, "VisionWorker", worker)
    monkeypatch.setattr(cli, "TrackWorker", tracker)
    monkeypatch.setattr(cli.asyncio, "sleep", stop_after_first_iteration)
    with pytest.raises(StopPipeline):
        asyncio.run(cli._run_vision(cli.parse_args(argv)))
    assert set(started[0].source_tokens) == ({"bench_overhead", "left_wrist", "bench_static"}
                                                   if combined else {"bench_overhead", "left_wrist"})
    assert [worker.source_id for worker in workers] == (["bench_static"] if combined else [])
    assert len(trackers) == (1 if combined else 0)
