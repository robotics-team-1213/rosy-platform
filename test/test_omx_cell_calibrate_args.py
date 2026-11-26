"""--remeasure-map: a supervised remap on request, refused outside auto --only remap (2026-11-26)."""
import argparse
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_calibrate_args as ca  # noqa: E402
import cell_job_spec  # noqa: E402


def args(**kw):
    base = dict(step="auto", only=["remap", "regions"], remeasure_map=True, remeasure_surface=None, surface_clear=False,
                plan_only=False, replay_frames=None, targets=[], verify=False, route=None, cad_image_evidence=None,
                obstacle_mm=None)
    return argparse.Namespace(**{**base, **kw})


def test_remeasure_map_is_only_a_supervised_auto_remap():
    assert ca.argument_error(args()) is None
    for bad in ({"step": "check"}, {"only": None}, {"only": ["surface"]}, {"plan_only": True},
                {"targets": ["belt:0.1,0.2"]}, {"verify": True}, {"replay_frames": Path("x")}):
        assert ca.argument_error(args(**bad)) == "--remeasure-map requires auto --only remap"
    assert ca.argument_error(args(remeasure_map=False, obstacle_mm=-1.0)).startswith("--obstacle-mm")


def test_remeasure_adds_the_remap_only_when_check_left_it_out():
    assert ca.with_remeasure([], True) == ["remap"]
    assert ca.with_remeasure(["regions"], True) == ["remap", "regions"]
    assert ca.with_remeasure(["remap", "regions"], True) == ["remap", "regions"]
    assert ca.with_remeasure([], False) == []


def test_the_remap_job_passes_remeasure_only_when_asked(tmp_path):
    (tmp_path / "cell-arm-s.json").write_text("{}")
    job = cell_job_spec.JOBS["remap"]
    base = {"arm": "arm_s", "config": "cell-arm-s.json", "person_at_switch": True}
    assert "--remeasure-map" not in cell_job_spec.build_argv(job, base, tmp_path)
    assert "--remeasure-map" in cell_job_spec.build_argv(job, {**base, "remeasure": True}, tmp_path)
    with pytest.raises(ValueError):
        cell_job_spec.build_argv(job, {**base, "remeasure": "yes"}, tmp_path)
