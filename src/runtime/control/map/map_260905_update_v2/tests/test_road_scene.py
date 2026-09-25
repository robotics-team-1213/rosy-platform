from pathlib import Path
import importlib.util
import copy

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_road_scene", ROOT / "scripts" / "build_road_scene.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_semantic_road_scene_assets_exist():
    assert (ROOT / "semantic" / "road_scene.yaml").is_file()
    assert (ROOT / "worlds" / "map_260905_traffic.world").is_file()
    assert (ROOT / "review" / "map_260905_traffic.png").is_file()


def test_builder_exposes_fail_closed_scene_validation():
    assert callable(getattr(BUILDER, "validate_scene", None))


def _scene():
    return yaml.safe_load((ROOT / "semantic" / "road_scene.yaml").read_text(encoding="utf-8"))


def test_scene_identity_is_revision_bound_for_runtime_policy():
    scene = _scene()
    assert scene["map_id"] == "map_260905_update_v2"
    assert scene["scene_revision"] == "road-scene-v1"


def test_scene_rejects_duplicate_ids_across_feature_types():
    scene = _scene()
    scene["stop_lines"][0]["id"] = scene["lanes"][0]["id"]

    with pytest.raises(ValueError, match="duplicate semantic feature id"):
        BUILDER.validate_scene(scene)


def test_scene_rejects_signal_references_to_unknown_features():
    scene = copy.deepcopy(_scene())
    scene["traffic_signals"][0]["controlled_stop_line_id"] = "missing"

    with pytest.raises(ValueError, match="unknown stop line"):
        BUILDER.validate_scene(scene)


def test_generated_world_binds_source_and_semantic_hashes():
    world = (ROOT / "worlds" / "map_260905_traffic.world").read_text(encoding="utf-8")
    source_hash = BUILDER.hashlib.sha256(BUILDER.canonical_text_bytes(
        ROOT / "worlds" / "map_260905.world")).hexdigest()
    semantic_hash = BUILDER.hashlib.sha256(BUILDER.canonical_text_bytes(
        ROOT / "semantic" / "road_scene.yaml")).hexdigest()

    assert f"source_world_sha256={source_hash}" in world
    assert f"road_scene_sha256={semantic_hash}" in world


def test_manifest_covers_semantic_source_and_generated_assets():
    manifest = (ROOT / "MANIFEST.sha256").read_text(encoding="utf-8")
    paths = (
        "semantic/road_scene.yaml",
        "scripts/build_road_scene.py",
        "worlds/map_260905_traffic.world",
        "review/map_260905_traffic.png",
    )
    for relative in paths:
        path = ROOT / relative
        content = (
            path.read_bytes()
            if path.suffix == ".png"
            else BUILDER.canonical_text_bytes(path)
        )
        digest = BUILDER.hashlib.sha256(content).hexdigest()
        assert f"{digest}  {relative}" in manifest
