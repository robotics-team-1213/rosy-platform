"""D-344 §12 addendum 2026-10-03: the bench tool writes an overlay launch will load, outside the release."""

import math
import os
from types import SimpleNamespace

import pytest
import yaml

from control.ir_overlay import NODE_KEY, usable_operator_overlay
from control.line_observer_overrides import main

PROFILE = "/opt/rosy/current/install/share/pinky_pro/config/camera_nominal.yaml"


@pytest.fixture(autouse=True)
def profile_installed(monkeypatch):
    """PROFILE is the robot path; pretend the release installed it on this host."""
    real = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda path: path == PROFILE or real(path))


def _run_log():
    calls = []
    return calls, lambda cmd, check: calls.append(cmd) or SimpleNamespace(returncode=0)


def test_apply_writes_a_loadable_keep_nominal_overlay_and_restarts_only_the_camera(tmp_path):
    target = tmp_path / "line_observer_overrides.yaml"
    calls, run = _run_log()
    assert main(["--path", str(target), "apply", "--profile", PROFILE,
                 "--pitch-deg", "11.2", "--height-m", "0.059"], run=run) == 0
    assert usable_operator_overlay(str(target))[0] == str(target)
    params = yaml.safe_load(target.read_text(encoding="utf-8"))[NODE_KEY]["ros__parameters"]
    assert params["camera_lane_mode"] == "keep" and params["camera_ground_source"] == "NOMINAL"
    assert params["allow_nominal_ground"] is True and params["debug_overlay"] is True
    assert params["nominal_camera_profile_path"] == PROFILE
    assert math.isclose(params["camera_pitch_rad_override"], math.radians(11.2))
    assert params["camera_height_m_override"] == 0.059
    assert calls == [["systemctl", "restart", "rosy-camera"]]


def test_apply_without_geometry_leaves_the_record_or_urdf_nominal_in_charge(tmp_path):
    target = tmp_path / "o.yaml"
    assert main(["--path", str(target), "apply", "--profile", PROFILE, "--no-restart"]) == 0
    params = yaml.safe_load(target.read_text(encoding="utf-8"))[NODE_KEY]["ros__parameters"]
    assert "camera_pitch_rad_override" not in params and "camera_height_m_override" not in params


def test_apply_refuses_what_launch_would_skip_and_keeps_the_old_file(tmp_path, capsys):
    target = tmp_path / "o.yaml"
    calls, run = _run_log()
    assert main(["--path", str(target), "apply", "--profile", PROFILE, "--no-restart"]) == 0
    before = target.read_text(encoding="utf-8")
    for argv in (["--profile", PROFILE, "--height-m", "59"],        # mm, not m
                 ["--profile", PROFILE, "--mode", "route_a"],
                 []):                                               # NOMINAL without a profile
        assert main(["--path", str(target), "apply", *argv], run=run) == 1
    assert target.read_text(encoding="utf-8") == before and calls == []
    assert list(tmp_path.iterdir()) == [target]                     # no temp file left
    assert "camera_height_m_override" in capsys.readouterr().err


def test_clear_removes_the_overlay_and_restarts(tmp_path):
    target = tmp_path / "o.yaml"
    main(["--path", str(target), "apply", "--profile", PROFILE, "--no-restart"])
    calls, run = _run_log()
    assert main(["--path", str(target), "clear"], run=run) == 0
    assert not target.exists() and calls == [["systemctl", "restart", "rosy-camera"]]
    assert main(["--path", str(target), "clear", "--no-restart"]) == 0


def test_show_reports_whether_launch_would_load_it(tmp_path, capsys):
    target = tmp_path / "o.yaml"
    main(["--path", str(target), "show"])
    assert "absent" in capsys.readouterr().out
    main(["--path", str(target), "apply", "--profile", PROFILE, "--no-restart"])
    capsys.readouterr()
    main(["--path", str(target), "show"])
    assert "loaded" in capsys.readouterr().out


def test_apply_refuses_a_profile_that_is_not_an_existing_file(tmp_path, capsys):
    target = tmp_path / "o.yaml"
    missing = "/opt/rosy/current/install/share/pinky_pro/config/missing.yaml"
    assert main(["--path", str(target), "apply", "--profile", missing, "--no-restart"]) == 1
    assert not target.exists() and "not an existing file" in capsys.readouterr().err
