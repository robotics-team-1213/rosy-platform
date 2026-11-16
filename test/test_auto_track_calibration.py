"""Tests for deploy/site/rosy-auto-track-calibration stability gate and credential handling."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy/site/rosy-auto-track-calibration"


def _load_module():
    loader = importlib.machinery.SourceFileLoader("rosy_auto_track_calibration_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _shifted_corners(mod, dx: float, dy: float = 0.0) -> list[list[float]]:
    return [[round(cx + dx, 6), round(cy + dy, 6)] for cx, cy in mod.CORNERS_M]


def test_script_has_no_sqlite_or_account_db_access():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "sqlite3" not in src
    assert "account.sqlite3" not in src
    assert "mint_operator_token" not in src


def test_noisy_series_never_approves():
    mod = _load_module()
    noisy = [
        _shifted_corners(mod, 0.04),
        _shifted_corners(mod, 0.38),
        _shifted_corners(mod, 0.05),
        _shifted_corners(mod, 0.04),
        _shifted_corners(mod, 0.05),
    ]
    res = mod.decide(noisy, now=100_000.0)
    assert res["decision"] == "hold"
    assert res["reason"] == "unstable_series"
    assert res["spread"] > mod.STABLE_SPREAD_M


def test_insufficient_samples_holds():
    mod = _load_module()
    short = [_shifted_corners(mod, 0.05) for _ in range(4)]
    res = mod.decide(short, now=100_000.0)
    assert res["decision"] == "hold"
    assert res["reason"].startswith("insufficient_samples:")


def test_small_drift_holds():
    mod = _load_module()
    stable_small = [_shifted_corners(mod, 0.005 + i * 0.0005) for i in range(5)]
    res = mod.decide(stable_small, place_diff_m=0.004, now=100_000.0)
    assert res["decision"] == "hold"
    assert res["reason"] == "within_threshold"
    assert res["drift"] <= mod.DRIFT_THRESHOLD_M
    assert res["spread"] <= mod.STABLE_SPREAD_M


def test_stable_drifted_series_approves_once_and_rate_limits():
    mod = _load_module()
    stable_drifted = [_shifted_corners(mod, 0.030 + i * 0.001) for i in range(5)]
    first = mod.decide(stable_drifted, now=100_000.0, last_approved_at=None)
    assert first["decision"] == "approve"
    assert first["reason"] == "drift_exceeded"
    assert first["spread"] <= mod.STABLE_SPREAD_M
    assert first["drift"] > mod.DRIFT_THRESHOLD_M

    assert mod.MIN_APPROVAL_INTERVAL_S == 600
    second = mod.decide(stable_drifted, now=100_000.0 + 300.0, last_approved_at=100_000.0)
    assert second["decision"] == "hold"
    assert second["reason"] == "rate_limited"

    forced = mod.decide(stable_drifted, now=100_000.0 + 300.0, last_approved_at=100_000.0, force=True)
    assert forced["decision"] == "approve"
    assert forced["reason"] == "forced"

    after_cooldown = mod.decide(
        stable_drifted,
        now=100_000.0 + mod.MIN_APPROVAL_INTERVAL_S + 1.0,
        last_approved_at=100_000.0,
    )
    assert after_cooldown["decision"] == "approve"


def test_missing_token_file_logs_no_credential_and_never_writes(tmp_path, monkeypatch, capsys):
    mod = _load_module()
    monkeypatch.setenv("ROSY_AUTO_CALIBRATION_TOKEN_FILE", str(tmp_path / "missing.token"))
    monkeypatch.setattr(mod, "STATE_FILE", tmp_path / "state.json")

    def boom(*_args, **_kwargs):
        raise AssertionError("network/container call must not happen without credential")

    monkeypatch.setattr(mod, "run_vision_solve", boom)
    monkeypatch.setattr(mod, "fetch_fleet_current", boom)
    monkeypatch.setattr(mod, "apply_fleet_update", boom)

    rc = mod.main([])
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out == {"status": "no-credential"}


def test_dry_run_and_mean_approval_in_main(tmp_path, monkeypatch, capsys):
    mod = _load_module()
    token_file = tmp_path / "auto-calibration.token"
    token_file.write_text("secret-bearer-token\n", encoding="utf-8")
    state_file = tmp_path / "state.json"
    monkeypatch.setenv("ROSY_AUTO_CALIBRATION_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(mod, "STATE_FILE", state_file)

    # Identity map_to_image; shifted image_to_map per run (dx = 0.030, 0.032, 0.034, 0.036, 0.038; mean = 0.034).
    ident = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    shifts = [0.030, 0.032, 0.034, 0.036, 0.038]
    idx = {"n": 0}

    def fake_solve():
        dx = shifts[idx["n"]]
        idx["n"] += 1
        return {
            "ok": True,
            "width": 1280,
            "height": 720,
            "frame_seq": 100 + idx["n"],
            "rms_m": 0.002,
            "map_to_image": [1.0, 0.0, -dx, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            "image_to_map": [1.0, 0.0, dx, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            "places": [{"id": "p1", "x": 0.1 + dx, "y": 0.2}],
            "edges": [],
        }

    def fake_current(_token):
        return {
            "cur_cal": {"calibration_revision": 1, "map_to_image": ident},
            "cur_map": {"map": {"places": [{"id": "p1", "x": 0.1, "y": 0.2}]}},
        }

    applied = []

    def fake_apply(_token, solved, *, needs_cal, needs_map):
        applied.append((solved, needs_cal, needs_map))
        return {"cal_updated": True, "calibration_revision": 2, "map_updated": True, "map_version": 2}

    monkeypatch.setattr(mod, "run_vision_solve", fake_solve)
    monkeypatch.setattr(mod, "fetch_fleet_current", fake_current)
    monkeypatch.setattr(mod, "apply_fleet_update", fake_apply)

    for _ in range(4):
        assert mod.main([]) == 0
        line = json.loads(capsys.readouterr().out.strip())
        assert line["decision"] == "hold"
        assert "secret-bearer-token" not in json.dumps(line)

    # 5th run in --dry-run must NOT POST/PUT or mutate state.
    assert mod.main(["--dry-run"]) == 0
    dry_line = json.loads(capsys.readouterr().out.strip())
    assert dry_line["status"] == "dry-run"
    assert dry_line["decision"] == "approve"
    assert applied == []

    # Reset idx to 4 for the real 5th run.
    idx["n"] = 4
    assert mod.main([]) == 0
    upd_line = json.loads(capsys.readouterr().out.strip())
    assert upd_line["status"] == "updated"
    assert upd_line["decision"] == "approve"
    assert len(applied) == 1
    approved_solved, needs_cal, needs_map = applied[0]
    assert needs_cal and needs_map
    # Mean of shifts [0.030..0.038] is 0.034, NOT the last solve (0.038).
    assert abs(approved_solved["map_to_image"][2] - (-0.034)) < 1e-6
    assert abs(approved_solved["places"][0]["x"] - 0.134) < 1e-6


def test_world_261026_auto_handles_glare_split_and_charger_occlusion():
    import sys
    import cv2
    import numpy as np

    vision_dir = str(ROOT / "operations/overhead")
    if vision_dir not in sys.path:
        sys.path.insert(0, vision_dir)
    from rosy_vision.world_261026_auto import _proj, auto_calibrate_and_trace_world_261026

    synth = np.full((720, 1280, 3), 105, dtype=np.uint8)
    m2i_syn = np.array([[380.0, 20.0, 640.0], [-15.0, -380.0, 360.0], [-0.05, 0.02, 1.0]])

    def draw_seg(im, p1, p2, col, thick=7):
        pts = np.array([p1, p2], np.float64)
        p = np.column_stack([pts, np.ones(2)]) @ m2i_syn.T
        uv = np.round(p[:, :2] / p[:, 2:3]).astype(np.int32)
        cv2.line(im, tuple(uv[0]), tuple(uv[1]), col, thick, cv2.LINE_AA)

    for a, b in [
        ((-1.08, -0.588), (1.08, -0.588)),
        ((-0.926, -0.364), (0.926, -0.364)),
        ((-1.10, -0.140), (-0.70, -0.140)),
        ((-0.56, -0.140), (0.18, -0.140)),
        ((0.42, -0.140), (1.10, -0.140)),
        ((-0.69, 0.260), (-0.53, 0.260)),
        ((0.14, 0.260), (0.30, 0.260)),
        ((-1.188, -0.50), (-1.188, -0.22)),
        ((1.188, -0.50), (1.188, -0.22)),
    ]:
        draw_seg(synth, a, b, (240, 240, 240))
    pink_bgr = (180, 130, 245)
    for a, b in [
        ((-0.630, -0.045), (-0.596, 0.025)),
        ((0.258, -0.045), (0.228, 0.025)),
        ((-0.596, 0.025), (0.228, 0.025)),
        ((-0.414, 0.025), (-0.414, 0.520)),
        ((-0.190, 0.025), (-0.190, 0.520)),
        ((0.032, 0.025), (0.032, 0.520)),
    ]:
        draw_seg(synth, a, b, pink_bgr)
    green_bgr = (90, 170, 70)
    for a, b in [
        ((-0.526, 0.260), (-0.526, 0.597)),
        ((0.148, 0.260), (0.148, 0.597)),
        ((-0.526, 0.597), (0.148, 0.597)),
    ]:
        draw_seg(synth, a, b, green_bgr)

    # Simulate ceiling fluorescent glare cutting across bay 3 and C1 charger covering left top green
    draw_seg(synth, (-0.15, 0.30), (0.10, 0.18), (250, 250, 250), thick=16)
    draw_seg(synth, (-0.52, 0.597), (-0.18, 0.597), (105, 105, 105), thick=18)

    fit = auto_calibrate_and_trace_world_261026(synth)
    assert fit is not None
    assert fit["rms_m"] < 0.005
    corners = np.array([[-1.22, -0.61], [1.22, -0.61], [1.22, 0.61], [-1.22, 0.61]])
    err_px = np.max(np.hypot(*(_proj(fit["map_to_image"], corners) - _proj(m2i_syn, corners)).T))
    assert err_px < 4.0

