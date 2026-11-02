"""D-963: the control PC reports unregistered USB cameras to Fleet and applies the role Fleet's operator decided."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from core_common.protocol.workcell_observations import UsbCameraDecisions

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
TOP = "/dev/v4l/by-id/rosy-realsense-d435-color"
WRIST = "/dev/v4l/by-path/pci-usb-0:1.3:1.0-video-index0"
NEW = "/dev/v4l/by-path/pci-usb-0:2:1.0-video-index0"
FACTS = {"/dev/video12": {"id": "8086:0b07"}, "/dev/video4": {"id": "04f2:b678"}}
NAMES = {"/dev/video12": [TOP], "/dev/video4": ["/dev/v4l/by-id/usb-LG_Camera_0001-video-index0", NEW]}
REGISTRY = {"schema": "rosy.omx-cameras.v1", "defaults": {}, "cameras": [
    {"role": "top", "device": TOP, "topic": "/top_camera/image_raw", "frame": "top_camera_link", "usb_id": "8086:0b07"},
    {"role": "arm_b_wrist", "device": WRIST, "topic": "/arm_b_wrist_camera/image_raw", "frame": "f",
     "usb_id": "04f2:b678"},
    {"role": "arm_a_wrist", "device": WRIST.replace("1.3", "1.4"), "topic": "/arm_a_wrist_camera/image_raw",
     "frame": "g", "usb_id": "04f2:b678"}]}


@pytest.fixture
def modules(monkeypatch):
    """omx_cameras and usb_camera_report loaded so their default realpath/exists treat /dev names as they are:
    the same code then runs on any host."""
    exists = os.path.exists
    monkeypatch.syspath_prepend(str(OMX))
    loaded = []
    with monkeypatch.context() as patched:
        patched.setattr(os.path, "realpath", lambda p, **k: next((n for n, ns in NAMES.items() if p in ns), p))
        patched.setattr(os.path, "exists", lambda p: str(p) == TOP or (not str(p).startswith("/dev/") and exists(p)))
        for name in ("omx_cameras", "usb_camera_report"):
            spec = importlib.util.spec_from_file_location(name, OMX / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            monkeypatch.setitem(sys.modules, name, module)
            spec.loader.exec_module(module)
            loaded.append(module)
    return loaded


def present(path):
    return path == TOP


def test_report_names_unregistered_cameras_by_key_only(modules):
    cameras, report = modules
    built = report.build_report("one", REGISTRY, FACTS, NAMES, present)
    assert built.roles == ["top", "arm_b_wrist", "arm_a_wrist"]
    assert [(c.key, c.usb_id, c.roles) for c in built.candidates] == [
        (cameras.device_key(NEW), "04f2:b678", ["arm_b_wrist", "arm_a_wrist"])]
    assert "/dev/" not in built.model_dump_json()


def test_cycle_writes_fleet_decisions_atomically_and_a_fleet_error_changes_nothing(modules, tmp_path):
    cameras, report = modules
    registry, decisions = tmp_path / "reg.json", tmp_path / "state" / "decisions.json"
    registry.write_text(json.dumps(REGISTRY))
    key, sent = cameras.device_key(NEW), []

    def post(body):
        sent.append(body)
        return UsbCameraDecisions.model_validate({"decisions": [{"key": key, "role": "front"}]})

    where = dict(registry_path=registry, decisions_path=decisions, facts=lambda: FACTS, names=lambda: NAMES)
    report.cycle(post, "one", **where)
    assert json.loads(decisions.read_text()) == {key: "front"} and len(sent) == 1
    before = decisions.stat().st_mtime_ns
    report.cycle(post, "one", **where)
    assert decisions.stat().st_mtime_ns == before  # an unchanged answer is not rewritten

    def down(body):
        raise OSError("fleet down")

    with pytest.raises(OSError):  # the bridge's loop catches this; the file keeps the last answer
        report.cycle(down, "one", **where)
    assert json.loads(decisions.read_text()) == {key: "front"}
    report.cycle(post, "one", **{**where, "registry_path": tmp_path / "none.json"})  # no registry: nothing to report
    assert len(sent) == 2


def test_bind_applies_a_decision_once_ignores_unknown_keys_and_never_trusts_a_bad_role(modules, tmp_path, monkeypatch):
    cameras, _ = modules
    registry, decisions = tmp_path / "reg.json", tmp_path / "decisions.json"
    registry.write_text(json.dumps(REGISTRY))
    exists = os.path.exists
    monkeypatch.setattr(os.path, "exists",
                        lambda p: str(p) in (TOP, NEW) or (not str(p).startswith("/dev/") and exists(p)))
    monkeypatch.setattr(cameras.omx_devices, "video_facts", lambda: FACTS)
    monkeypatch.setattr(cameras, "_names", lambda: NAMES)
    systemctl = lambda *a, **k: SimpleNamespace(returncode=0, stdout="")  # noqa: E731
    monkeypatch.setattr(cameras.subprocess, "run", systemctl)
    apply = cameras.apply
    monkeypatch.setattr(cameras, "apply", lambda plan, env_dir, running: apply(plan, env_dir, running, run=systemctl))
    key, other = cameras.device_key(NEW), "c" * 32
    argv = ["bind", "--apply", "--registry", str(registry), "--env-dir", str(tmp_path), "--decisions", str(decisions),
            "--manifest", str(tmp_path / "none.yaml")]

    decisions.write_text(json.dumps({other: "x", key: "bad role"}))
    assert cameras.main(argv) == 0
    assert len(json.loads(registry.read_text())["cameras"]) == 3  # unknown key and invalid role: nothing approved

    decisions.write_text(json.dumps({other: "x", key: "front"}))
    assert cameras.main(argv) == 0
    front = next(c for c in json.loads(registry.read_text())["cameras"] if c["role"] == "front")
    assert front["device"] == NEW and front["topic"] == "/front_camera/image_raw"
    assert json.loads(decisions.read_text()) == {other: "x"}  # applied entry cleared, the waiting one kept
    assert (tmp_path / "omx-camera-front.env").exists()
