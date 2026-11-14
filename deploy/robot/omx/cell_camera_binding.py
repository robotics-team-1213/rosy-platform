"""Read only physical camera identity for OMX lens calibration."""

import json
import re
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


def viewer_label_from_url(url: str) -> str:
    parsed = urlsplit(url)
    path = PurePosixPath(parsed.path)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != 8767
            or path.parent != PurePosixPath("/frame") or path.suffix != ".jpg"
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("camera must use the local original-frame viewer")
    return path.stem


def runtime_viewer_state(camera: str, topic: str) -> tuple[int, float]:
    with urllib.request.urlopen("http://127.0.0.1:8767/state.json", timeout=3) as response:
        state = json.loads(response.read(1_000_001))
    item = (state.get("cameras") or {}).get(camera) or {}
    seq, stamp = item.get("sequence"), item.get("source_stamp")
    if (item.get("topic") != topic or item.get("fresh") is not True
            or type(seq) is not int or seq < 0 or type(stamp) not in (int, float) or stamp <= 0):
        raise ValueError("CALIBRATION_REQUIRED: running viewer source is unverified")
    return seq, float(stamp)


def viewer_session() -> str:
    import camera_readiness

    raw = camera_readiness.command(["systemctl", "--user", "show", "rosy-omx-camera-view.service",
                                    "-p", "InvocationID", "-p", "MainPID"])
    props = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    if not props.get("InvocationID") or not (props.get("MainPID") or "").isdigit() or int(props["MainPID"]) <= 0:
        raise ValueError("CALIBRATION_REQUIRED: running viewer session unavailable")
    return props["InvocationID"]


def producer_argv(pid: int) -> list[str]:
    return [part.decode() for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if part]


def live_camera_binding(camera: str, *, viewer_label: str | None = None) -> dict:
    """Bind a viewer label to its sole active registered USB camera and readable focus controls."""
    import camera_readiness
    import cell_upkeep
    import omx_cameras
    import omx_devices

    label = viewer_label or camera
    topic = cell_upkeep.viewer_labels().get(label)
    rows = [row for row in omx_cameras.load()["cameras"] if row.get("topic") == topic] if topic else []
    if len(rows) != 1:
        raise ValueError("CALIBRATION_REQUIRED: camera viewer has no unique registered source")
    row = rows[0]
    device = row["device"]
    identity = camera_readiness.identity(device)
    facts = omx_devices.video_facts()
    fact = facts.get(identity["realpath"])
    if (fact is None or not row.get("usb_id") or row["usb_id"] != fact.get("id")
            or not fact.get("usb") or not fact.get("interface")):
        raise ValueError("CALIBRATION_REQUIRED: registered USB camera identity unavailable")
    session = viewer_session()
    runtime_viewer_state(label, topic)
    producer = camera_readiness.producer(row["role"], device, wait_s=0)
    if not producer.get("InvocationID"):
        raise ValueError("CALIBRATION_REQUIRED: camera producer session unavailable")
    pid = int(producer["MainPID"])
    argv = producer_argv(pid)
    if not all(any(argv[i:i + 2] == [flag, value] for i in range(len(argv) - 1)) for flag, value in
               (("--device", device), ("--topic", topic), ("--frame-id", row["frame"]))):
        raise ValueError("CALIBRATION_REQUIRED: camera producer command differs from registry")
    runtime_viewer_state(label, topic)
    if viewer_session() != session:
        raise ValueError("CALIBRATION_REQUIRED: viewer restarted during camera identity check")
    controls = camera_readiness.command(["v4l2-ctl", "--device=" + device, "--list-ctrls"])
    names = set(re.findall(r"^\s*((?:focus_\w+|auto_focus))\s+0x", controls, re.M))
    focus = camera_readiness.get_controls(device, names) if names else {}
    same_serial_ports = {entry.get("usb") for entry in facts.values()
                         if entry.get("id") == fact["id"] and entry.get("serial") == fact.get("serial")}
    # shortcut: a replacement with the same cloned serial on the same port is indistinguishable; re-survey after replacement.
    unique = bool(fact.get("serial") and fact["serial"] != "SN0001" and same_serial_ports == {fact["usb"]})
    return {"viewer_label": label, "topic": topic, "role": row["role"], "device_alias": device,
            "usb_id": fact["id"], "usb_port": fact["usb"], "usb_interface": fact["interface"],
            "serial": fact.get("serial"), "focus_controls": focus, "unique_hardware_identity": unique,
            "viewer_invocation_id": session, "producer_invocation_id": producer["InvocationID"]}
