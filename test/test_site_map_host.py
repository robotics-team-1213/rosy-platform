"""Site map host half tests on a fake tree without touching systemd or host filesystem."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/native"))
import site_map_host as host  # noqa: E402

RUNTIME = "ROSY_RUNTIME_MODE=hardware\nROSY_NAVIGATION_BACKEND=slam\nROSY_MAP=/var/lib/rosy/maps/site.yaml\n"


def _pgm(width=8, height=6, *, comment=True, fill=254):
    hdr = f"P5\n# rosy map bundle: site_v1\n{width} {height}\n255\n" if comment else f"P5\n{width} {height}\n255\n"
    return hdr.encode("ascii") + bytes([fill]) * (width * height)


class FakeOps:
    def __init__(self, root: Path, *, fail=None, active_after_restart=True, active_sequence=None) -> None:
        self.root, self.fail, self.active_after_restart = root, fail, active_after_restart
        self.active_sequence = list(active_sequence) if active_sequence is not None else None
        self.calls, self.commits, self.spawned = [], [], []
        self.units: set[str] = set()
        self.t, self.boot = 2000.0, "boot-site"

    def run(self, *argv, timeout=120):
        self.calls.append(argv)
        failed = self.fail is not None and self.fail in " ".join(map(str, argv))
        if not failed and argv[:2] == ("systemctl", "restart"):
            become_active = (
                self.active_sequence.pop(0) if self.active_sequence is not None else self.active_after_restart
            )
            if become_active:
                self.units.add(argv[2])
            else:
                self.units.discard(argv[2])
        return subprocess.CompletedProcess(argv, 1 if failed else 0, "", "restart failed" if failed else "")

    def now(self):
        return self.t

    def wall(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds

    def boot_id(self):
        return self.boot

    def spawn(self, action, *arguments):
        self.spawned.append((action, *arguments))
        return subprocess.CompletedProcess([], 0, "", "")

    def active(self, unit):
        return unit in self.units

    def commit(self, root, new, old):
        assert (root / host.RUNTIME).read_bytes() == old
        self.commits.append(new)
        (root / host.RUNTIME).write_bytes(new)


def _spool(root: Path, pgm_bytes=None, version=3, **meta):
    content = _pgm() if pgm_bytes is None else pgm_bytes
    folder = root / host.SPOOL
    folder.mkdir(parents=True, exist_ok=True)
    (folder / host.SPOOL_IMAGE).write_bytes(content)
    doc = {
        "map_id": "site-a",
        "version": version,
        "resolution": 0.05,
        "origin": [-1.0, -0.5, 0.0],
        "occupied_thresh": 0.65,
        "free_thresh": 0.196,
        "grid_id": "occupancy:deadbeef1234",
        "source": "rosy_45+rosy_46",
        "sha256": hashlib.sha256(content).hexdigest(),
        **meta,
    }
    (folder / host.SPOOL_META).write_text(json.dumps(doc), encoding="utf-8")


def _stopped(root: Path, ops: FakeOps, *, zero_for=2.5, goal_active=False, age=0.5, boot=None):
    (root / host.STOP_EVIDENCE).parent.mkdir(parents=True, exist_ok=True)
    (root / host.STOP_EVIDENCE).write_text(json.dumps({
        "written_at": ops.t - age,
        "zero_since": None if zero_for is None else ops.t - age - zero_for,
        "goal_active": goal_active,
        "boot_id": boot or ops.boot,
    }), encoding="utf-8")


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "etc/rosy").mkdir(parents=True)
    (tmp_path / host.RUNTIME).write_text(RUNTIME, encoding="utf-8")
    (tmp_path / host.MAPS).mkdir(parents=True, exist_ok=True)
    (tmp_path / host.MAPS / "site.yaml").write_text("original: true\n", encoding="utf-8")
    return tmp_path


def test_stage_accepts_comment_bearing_pgm_and_preserves_site_yaml(tree):
    ops = FakeOps(tree)
    _spool(tree, pgm_bytes=_pgm(comment=True))
    staged = host.stage_site_map(tree, ops)
    assert staged["staged"] == "site_site-a_v3"
    assert staged["yaml"] == "/var/lib/rosy/maps/site_site-a_v3.yaml"
    assert (tree / host.MAPS / "site_site-a_v3.pgm").is_file()
    assert (tree / host.MAPS / "site_site-a_v3.manifest.json").is_file()
    assert (tree / host.MAPS / "site.yaml").read_text(encoding="utf-8") == "original: true\n"


@pytest.mark.parametrize("bad", [
    {"sha256": "0" * 64},
    {"origin": [-1.0, -0.5, 0.25]},
    {"free_thresh": 0.25},
])
def test_stage_refuses_bad_metadata_or_sha(tree, bad):
    ops = FakeOps(tree)
    _spool(tree, **bad)
    with pytest.raises(ValueError):
        host.stage_site_map(tree, ops)


def test_stage_refuses_overwriting_live_map(tree):
    ops = FakeOps(tree)
    (tree / host.RUNTIME).write_text(
        RUNTIME.replace("site.yaml", "site_site-a_v3.yaml"), encoding="utf-8",
    )
    _spool(tree, pgm_bytes=_pgm(fill=205), version=3)
    with pytest.raises(ValueError, match="running navigation"):
        host.stage_site_map(tree, ops)


def test_activate_enforces_stop_evidence_then_commits_and_rolls_back(tree):
    ops = FakeOps(tree)
    _spool(tree)
    host.stage_site_map(tree, ops)

    with pytest.raises(ValueError, match="stopped"):
        host.request_activate(tree, ops)

    _stopped(tree, ops, goal_active=True)
    with pytest.raises(ValueError):
        host.request_activate(tree, ops)

    _stopped(tree, ops, zero_for=1.0)
    with pytest.raises(ValueError):
        host.request_activate(tree, ops)

    _stopped(tree, ops, zero_for=2.5)
    res = host.request_activate(tree, ops)
    assert res["phase"] == "ACTIVATING"
    assert ops.spawned == [("activate",)]

    host.activate_site_map(tree, ops)
    status = host.site_map_status(tree, ops)
    assert status["phase"] == "ACTIVE"
    assert status["backend"] == "localization"
    assert status["map"] == "/var/lib/rosy/maps/site_site-a_v3.yaml"
    assert b"ROSY_ENABLE_LOC_ASSIST=true" in (tree / host.RUNTIME).read_bytes()

    # First restart leaves navigation inactive; rollback restart succeeds -> ROLLED_BACK
    fail_ops = FakeOps(tree, active_sequence=[False, True])
    _spool(tree, pgm_bytes=_pgm(fill=205), version=4)
    host.stage_site_map(tree, fail_ops)
    _stopped(tree, fail_ops, zero_for=3.0)
    host.request_activate(tree, fail_ops)
    host.activate_site_map(tree, fail_ops)
    rolled = host.site_map_status(tree, fail_ops)
    assert rolled["phase"] == "ROLLED_BACK"
    assert rolled["map"] == "/var/lib/rosy/maps/site_site-a_v3.yaml"

    # Rollback failure to restore active unit reports FAILED and refuses non-hardware mode
    dead_ops = FakeOps(tree, active_after_restart=False)
    _spool(tree, pgm_bytes=_pgm(fill=205), version=5)
    host.stage_site_map(tree, dead_ops)
    _stopped(tree, dead_ops, zero_for=3.0)
    host.request_activate(tree, dead_ops)
    host.activate_site_map(tree, dead_ops)
    assert host.site_map_status(tree, dead_ops)["phase"] == "FAILED"

    (tree / host.RUNTIME).write_text(RUNTIME.replace("hardware", "motor"), encoding="utf-8")
    with pytest.raises(ValueError, match="ROSY_RUNTIME_MODE=hardware"):
        host.request_activate(tree, FakeOps(tree))
