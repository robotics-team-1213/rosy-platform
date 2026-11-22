"""Tests for shared Design 2 canonical start spec, envelope branch checks, and data_gate integration."""
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "contracts" / "learning" / "src"))
sys.path.insert(0, str(ROOT / "learning" / "curation" / "omx"))
sys.path.insert(0, str(ROOT / "learning" / "curation" / "omx" / "test"))

from rosy.contracts.learning import omx_canonical as oc  # noqa: E402


def test_builtin_design2_spec_validates_and_hashes_deterministically(tmp_path):
    spec, sha1, src = oc.load_canonical_spec()
    assert src == "builtin"
    assert len(sha1) == 64 and all(c in "0123456789abcdef" for c in sha1)
    assert oc.canonical_spec_sha256(spec) == sha1
    assert spec["design"] == "design2_idle_home_active_canonical"
    assert spec["sim_jaw_open"] == 0.5907 and spec["open_gap_m"] == 0.042

    spec_file = tmp_path / "canonical.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")
    loaded, sha2, src2 = oc.load_canonical_spec(spec_file)
    assert src2 == "configured" and sha2 == sha1 and loaded == spec


@pytest.mark.parametrize("mutator,match", [
    (lambda s: s["real_entry_bridge"].__setitem__("folded_tol_norm", 5.0), "folded_tol_norm"),
    (lambda s: s["real_entry_bridge"]["phases"][0].__setitem__("joints", ["shoulder_pan", "elbow_flex", "wrist_flex"]), "phase 1"),
    (lambda s: s["real_entry_bridge"]["phases"][1].__setitem__("joints", ["shoulder_pan", "wrist_roll", "wrist_flex"]), "phase 2"),
    (lambda s: s.__setitem__("start_jitter_rad", 0.15), "data_gate limit"),
    (lambda s: s.__setitem__("camera_angle_jitter_deg", 4), "camera_angle_jitter_deg"),
])
def test_validate_canonical_spec_rejects_broken_bridge_or_gate_overflow(mutator, match):
    bad = oc.default_canonical_spec()
    mutator(bad)
    with pytest.raises(ValueError, match=match):
        oc.validate_canonical_spec(bad)


def test_load_canonical_spec_rejects_symlink_or_oversize(tmp_path):
    target = tmp_path / "real.json"
    target.write_text(json.dumps(oc.default_canonical_spec()), encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="non-symlink"):
        oc.load_canonical_spec(link)

    big = tmp_path / "big.json"
    big.write_bytes(b" " * (262145))
    with pytest.raises(ValueError, match="bounded"):
        oc.load_canonical_spec(big)


def test_envelope_and_wrist_roll_warning_surfaces_intermediate_branch():
    lib = {
        "chunks": {
            "home": [[0.8, -62.2, 53.1, 51.6, 45.2, 48.8]],
            "carry": [
                [6.0, -55.0, 46.5, 49.0, 40.0, 55.78],
                [25.0, -15.0, 12.0, 55.0, -33.32, 50.0],
            ],
        }
    }
    env = oc.canonical_envelope_from_library(lib)
    assert env.home_roll == 45.2

    clean = oc.evaluate_chunk_envelope([[6.0, -55.0, 46.5, 49.0, 40.0, 55.78]], env)
    assert clean["strict_ok"] is True and clean["margin_ok"] is True
    assert "wrist_roll_warning" in clean and clean["wrist_roll_warning"] is None

    # Opposite 180-deg twin (~ -54.8 -> -33.32) is accepted within +/-45 deg,
    # while sweeping through the middle (~ +13 or -12.9) MUST raise wrist_roll_warning.
    swept = oc.evaluate_chunk_envelope([[6.0, -55.0, 46.5, 49.0, 13.0, 55.78]], env)
    assert swept["strict_ok"] is True and swept["margin_ok"] is True
    assert swept["wrist_roll_warning"] is not None and "lies between" in swept["wrist_roll_warning"]

    oor = oc.evaluate_chunk_envelope([[6.0, -66.5, 46.5, 49.0, -12.9, 55.78]], env)
    assert oor["strict_ok"] is False and oor["margin_ok"] is False
    assert oor["strict_oor"][0]["name"] == "shoulder_lift"
    assert oor["wrist_roll_warning"] is not None


def test_data_gate_records_canonical_distance_and_spec_hash_without_weakening(tmp_path):
    np = pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    pytest.importorskip("av")
    import data_gate as dg
    import test_data_gate as tdg

    spec, sha, _ = oc.load_canonical_spec()
    root = tdg.make(tmp_path / "canon-ds", state0=spec["canonical_start"]["arm_b"]["sim_rad"])
    receipt = dg.gate(root, "arm_b", {"kind": "sim", "layout": "random"}, canonical_spec=spec)
    assert receipt["counts"] == {"pass": 1, "review": 0, "reject": 0}
    assert receipt["canonical_spec_sha256"] == sha
    measured = receipt["episodes"][0]["measured"]
    assert measured["start_from_home_rad"] < dg.LIMITS["home_review_rad"]
    assert measured["start_from_canonical_rad"] == 0.0
    assert dg.check_receipt(root) == [0]


def test_omx_recording_todo_geometry_validation_and_priority():
    from rosy.contracts.learning import omx_recording_todo as rt

    assert len(rt.SLOTS) == 18
    assert rt.SLOT_BY_ID["ship-h1r2-l0"]["legacy_slot"] == "S01"
    assert rt.SLOT_BY_ID["ship-h1r0-l2"]["goal_index_h1"] == 2
    assert rt.SLOT_BY_ID["ship-h2r0-l0"]["goal_index_h1"] is None

    unconf = rt.build_recording_todo(None, source_state="unconfigured")
    assert unconf["inventory_status"] == "unconfigured" and unconf["cards"] == []
    assert unconf["real_evidence"] is False and unconf["policy_activation"] is False

    manifest = {
        "schema": rt.CURATED_MANIFEST_SCHEMA,
        "curated_version": "omx-real-v1",
        "hf_repo": "robotteam/rosy-omx-data",
        "hf_revision": "abcdef1234567890",
        "datasets": [
            {
                "dataset_id": "psy-right-l0-s03",
                "arm": "arm_a", "direction": "load", "bay": "ship-h1",
                "slot_id": "ship-h1r0-l0", "split_role": "train",
                "pick_pan_std_rad": 0.04,
                "episodes": {"raw_total": 5, "curated_total": 5},
                "wrist_roll_branch": {"branch": "positive_canonical"},
                "data_gate": {"goal_scope": "h1", "admissible": True, "counts": {"pass": 5, "review": 0, "reject": 0}, "dataset_reject": []},
            },
            {
                "dataset_id": "psy-left-l1-s01",
                "arm": "arm_b", "direction": "load", "bay": "ship-h1",
                "slot_id": "ship-h1r2-l1", "split_role": "train",
                "episodes": {"raw_total": 10, "curated_total": 10},
                "wrist_roll_branch": {"branch": "negative_raw"},
                "data_gate": {"goal_scope": "h1", "admissible": True, "counts": {"pass": 10, "review": 0, "reject": 0}, "dataset_reject": []},
            },
            {
                "dataset_id": "psy-left-s06-holdout",
                "arm": "arm_b", "direction": "load", "bay": "ship-h2",
                "slot_id": "ship-h2r0-l2", "split_role": "eval_holdout",
                "episodes": {"raw_total": 8, "curated_total": 8},
                "wrist_roll_branch": {"branch": "negative_raw"},
                "data_gate": {"goal_scope": "h2", "admissible": True, "counts": {"pass": 8, "review": 0, "reject": 0}, "dataset_reject": []},
            },
        ],
    }
    inv = rt.derive_inventory_from_manifest(manifest, manifest_sha256="a" * 64)
    todo = rt.build_recording_todo(inv, source_state="watch_root")
    assert todo["inventory_status"] == "ready"
    by_id = {c["card_id"]: c for c in todo["cards"]}
    assert todo["cards"][0]["card_id"] == "arm_b-ship-h1-l0" and todo["cards"][0]["priority"] == "p1"
    assert by_id["arm_a-ship-h1-l0"]["priority"] == "p2" and "near_fixed_layout" in by_id["arm_a-ship-h1-l0"]["warnings"]
    assert "negative_wrist_branch" in by_id["arm_b-ship-h1-l1"]["warnings"]
    assert by_id["arm_b-ship-h2-l2"]["holdout_episodes"] == 8 and by_id["arm_b-ship-h2-l2"]["episodes_pass"] == 0

    with pytest.raises(ValueError, match="slot_id mismatches bay"):
        rt.validate_manifest({**manifest, "datasets": [{**manifest["datasets"][0], "bay": "ship-h2"}]})
    with pytest.raises(ValueError, match="non-negative int"):
        rt.validate_inventory({**inv, "slots": [{**inv["slots"][0], "episodes_pass": -1}]})
