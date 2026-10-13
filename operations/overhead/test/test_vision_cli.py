from rosy_vision.cli import parse_args


def test_vision_command_requires_explicit_camera_config_and_defaults_to_site_ingress():
    args = parse_args(["vision", "--config", "site-cameras.yaml"])

    assert args.command == "vision"
    assert args.config.name == "site-cameras.yaml"
    assert (args.host, args.port) == ("0.0.0.0", 8095)


import pytest
import yaml
from rosy_vision.cli import _vision_ingest
from rosy_vision.vision_config import load_vision_sources


def _configs(tmp_path, *, paired=True):
    row = {
        "source_id": "ceiling_north", "token_env": "ROSY_FLEET_NORTH",
        "fleet_base_url": "https://fleet:8090", "robot_ids": ["rosy_01"], "map_id": "site-v1",
        "calibration_revision": "cal-v3", "processor_revision": "aruco-v1",
        "corner_marker_ids": [30, 31, 32, 33], "corner_world_m": [[0, 0], [4, 0], [4, 2], [0, 2]],
        "robot_markers": {"rosy_01": 7},
    }
    static = {**row, "source_id": "bench_static", "token_env": "ROSY_FLEET_BENCH",
              "phone_token_env": "ROSY_PHONE_BENCH"}
    rows = [static] + ([{**row, "credential": "paired"}] if paired else [])
    path = tmp_path / "site-cameras.yaml"
    path.write_text(yaml.safe_dump({"sources": rows}), encoding="utf-8")
    env = {"ROSY_FLEET_NORTH": "vision-north", "ROSY_FLEET_BENCH": "vision-bench",
           "ROSY_PHONE_BENCH": "phone-bench", "ROSY_PAIRING_SYNC": "sync-" + "secret-1"}
    return load_vision_sources(path, environ=env), env


def _args(*extra):
    return parse_args(["vision", "--config", "site-cameras.yaml", *extra])


SYNC_FLAGS = ("--pairing-sync-url", "https://fleet:8090",
              "--pairing-sync-token-env", "ROSY_PAIRING_SYNC")


def test_paired_sources_get_a_digest_view_and_static_ones_keep_their_token(tmp_path):
    configs, env = _configs(tmp_path)
    ingest, sync = _vision_ingest(_args(*SYNC_FLAGS), configs, environ=env)
    assert ingest.source_tokens == {"bench_static": "phone-bench"}
    assert ingest.paired.sources == {"ceiling_north"}
    assert sync == {"url": "https://fleet:8090", "token": "sync-" + "secret-1", "ca_file": None}


def test_paired_sources_refuse_start_without_the_sync_settings(tmp_path):
    configs, env = _configs(tmp_path)
    with pytest.raises(ValueError, match="pairing-sync"):
        _vision_ingest(_args(), configs, environ=env)


def test_sync_settings_without_a_paired_source_refuse_start(tmp_path):
    configs, env = _configs(tmp_path, paired=False)
    with pytest.raises(ValueError, match="paired"):
        _vision_ingest(_args(*SYNC_FLAGS), configs, environ=env)


@pytest.mark.parametrize("clash", ["ROSY_PHONE_BENCH", "ROSY_FLEET_NORTH", "preview"])
def test_sync_token_differs_from_every_vision_secret(tmp_path, clash):
    configs, env = _configs(tmp_path)
    if clash == "preview":
        env["ROSY_VISION_PREVIEW_SECRET"] = env["ROSY_PAIRING_SYNC"]
    else:
        env["ROSY_PAIRING_SYNC"] = env[clash]
    with pytest.raises(ValueError, match="differ"):
        _vision_ingest(_args(*SYNC_FLAGS), configs, environ=env)


def test_preview_secret_check_tolerates_paired_sources_without_a_phone_token(tmp_path):
    configs, env = _configs(tmp_path)
    env["ROSY_VISION_PREVIEW_SECRET"] = "preview-" + "x" * 32
    ingest, _ = _vision_ingest(_args(*SYNC_FLAGS), configs, environ=env)
    assert ingest.preview_signer is not None


def test_vision_track_flag_is_off_by_default():
    assert parse_args(["vision", "--config", "site-cameras.yaml"]).track is False
    assert parse_args(["vision", "--config", "site-cameras.yaml", "--track"]).track is True
