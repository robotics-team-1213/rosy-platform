#!/usr/bin/env python3
"""Status or display wake for one explicitly identified, already paired Android camera."""

import argparse
import ipaddress
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree


PACKAGE = "io.github.livsbittt.rosy.cam"
LIGHT_FIELDS = {"running", "light_supported", "light_requested", "torch_on", "dark",
                "light_limited", "photo_saving", "photo_saved", "photo_failed"}
LIGHT_BUTTONS = {True: "촬영 조명 요청", False: "조명 요청 취소"}


class ScreenError(RuntimeError):
    pass


def command(args, runner, optional=False, timeout=10):
    try:
        result = runner(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        if optional:
            return ""
        raise ScreenError("ADB command unavailable or timed out") from None
    if result.returncode:
        if optional:
            return ""
        raise ScreenError("ADB command failed; private output suppressed")
    return result.stdout


def validate(config):
    fields = {"adb_path", "expected_serial", "expected_model"}
    if not isinstance(config, dict) or set(config) != fields:
        raise ScreenError("Config must contain adb_path, expected_serial and expected_model")
    if any(not isinstance(config[k], str) or not config[k].strip() for k in fields):
        raise ScreenError("Config values must be nonempty strings")
    if not re.fullmatch(r"[A-Za-z0-9]+", config["expected_serial"]):
        raise ScreenError("Expected serial must be an explicit alphanumeric device serial")
    return config


def devices(config, runner):
    rows = []
    for line in command([config["adb_path"], "devices"], runner).splitlines():
        if not line.strip() or line.startswith("List of devices"):
            continue
        fields = line.split()
        if len(fields) != 2 or fields[1] != "device":
            raise ScreenError("Untrusted, offline or unauthorized ADB connection; refused")
        rows.append(fields[0])
    if len(rows) != len(set(rows)):
        raise ScreenError("Duplicate ADB connection; refused")
    return rows


def identity(config, target, runner):
    prefix = [config["adb_path"], "-s", target, "shell", "getprop"]
    serial = command([*prefix, "ro.serialno"], runner).strip()
    model = command([*prefix, "ro.product.model"], runner).strip()
    if not serial or not model:
        raise ScreenError("Device identity unavailable; refused")
    return serial, model


def verified(config, runner):
    matches = []
    for target in devices(config, runner):
        serial, model = identity(config, target, runner)
        if serial == config["expected_serial"]:
            if model != config["expected_model"]:
                raise ScreenError("Expected device model mismatch; refused")
            matches.append(target)
    if len(matches) > 1:
        raise ScreenError("Multiple connections match the expected device; refused")
    return matches[0] if matches else None


def endpoint(address, port):
    try:
        ip = ipaddress.ip_address(address)
        number = int(port)
        if not 1 <= number <= 65535:
            return None
        return f"[{ip}]:{number}" if ip.version == 6 else f"{ip}:{number}"
    except ValueError:
        return None


def candidates(config, runner):
    expected = re.compile(r"^adb-" + re.escape(config["expected_serial"]) + r"-[A-Za-z0-9_-]+(?: \(\d+\))?$")
    def matches(name):
        # Avahi escapes bytes as decimal \DDD; duplicate services gain " (2)".
        decoded = re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1))), name)
        return expected.fullmatch(decoded)
    found = set()
    raw = command([config["adb_path"], "mdns", "services"], runner, optional=True)
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 3 or fields[1] != "_adb-tls-connect._tcp":
            continue
        if not matches(fields[0].split(".", 1)[0]):
            continue
        address, _, port = fields[2].rpartition(":")
        value = endpoint(address.strip("[]"), port)
        if value:
            found.add(value)
    raw = command(["avahi-browse", "-rtp", "_adb-tls-connect._tcp"], runner, optional=True)
    for line in raw.splitlines():
        fields = line.split(";")
        if len(fields) < 9 or fields[0] != "=" or fields[4] != "_adb-tls-connect._tcp":
            continue
        if not matches(fields[3]):
            continue
        value = endpoint(fields[7], fields[8])
        if value:
            found.add(value)
    return sorted(found)


def light_state(shell, runner):
    raw = command([*shell, "dumpsys", "activity", "service", PACKAGE + "/.service.StreamService"], runner)
    records = re.findall(r"^\s*rosy_cam_state=(\{[^\n]*\})\s*$", raw, re.MULTILINE)
    if len(records) != 1:
        raise ScreenError("Unique running camera diagnostics unavailable")
    try:
        state = json.loads(records[0])
    except ValueError:
        raise ScreenError("Camera diagnostics invalid") from None
    if not isinstance(state, dict) or set(state) != LIGHT_FIELDS or any(type(v) is not bool for v in state.values()):
        raise ScreenError("Camera diagnostics unknown; refused")
    return state


def keyguard(shell, runner, timeout=10):
    raw = command([*shell, "dumpsys", "window", "policy"], runner, timeout=timeout)
    section = re.search(r"(?m)^\s*KeyguardServiceDelegate\s*:?\s*\n((?:[ \t]+[^\n]*\n?)*)", raw)
    if not section:
        raise ScreenError("Keyguard status unknown; refused")
    values = {}
    for field in ("showing", "secure"):
        matches = re.findall(r"(?m)^\s*" + field + r"=(true|false)\s*$", section[1])
        if len(matches) != 1:
            raise ScreenError("Keyguard status ambiguous; refused")
        values[field] = matches[0] == "true"
    return values


def wait_keyguard_dismissed(shell, runner):
    deadline = time.monotonic() + 2.0
    for attempt in range(10):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # The read itself shares the time budget, not a fresh ten-second timeout.
        guard = keyguard(shell, runner, timeout=remaining)
        if not guard["showing"]:
            return
        if guard["secure"]:
            raise ScreenError("Secure keyguard appeared; local unlock required")
        if attempt < 9:
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    raise ScreenError("Keyguard remains locked")


def focus_state(shell, runner):
    raw = command([*shell, "dumpsys", "window", "displays"], runner)
    matches = re.findall(r"mCurrentFocus=Window\{[^\n{}]+\s([^\s{}]+)\}", raw)
    apps = re.findall(r"mFocusedApp=ActivityRecord\{[^\n{}]*?\s([^\s{}]+/[^\s{}]+)\s+[^\n{}]+\}", raw)
    camera_components = {PACKAGE + "/.MainActivity", PACKAGE + "/" + PACKAGE + ".MainActivity"}
    if len(matches) != 1 or len(apps) != 1 or apps[0] not in camera_components:
        raise ScreenError("Camera app is not the unique focused activity")
    if matches[0] in camera_components:
        return "camera"
    if matches[0] == "NotificationShade":
        return "shade"
    raise ScreenError("Unknown overlay above camera; refused")


def focused(shell, runner):
    if focus_state(shell, runner) != "camera":
        raise ScreenError("Camera app is not the unique focused window")


def prepare_camera_focus(shell, runner):
    closed_shade = False
    for attempt in range(6):
        state = focus_state(shell, runner)
        if state == "camera":
            return
        # Only this known OS shade, above the verified camera activity and an
        # already dismissed keyguard, may receive one ordinary BACK key.
        if keyguard(shell, runner)["showing"]:
            raise ScreenError("Keyguard showing above camera; refused")
        if not closed_shade:
            command([*shell, "input", "keyevent", "KEYCODE_BACK"], runner)
            command([*shell, "am", "start", "-W", "-n", PACKAGE + "/.MainActivity"], runner)
            closed_shade = True
        if attempt < 5:
            time.sleep(0.1)
    raise ScreenError("Notification shade remains above camera; refused")


def display_size(shell, runner):
    raw = command([*shell, "wm", "size"], runner)
    physical = re.findall(r"(?m)^Physical size: (\d+)x(\d+)\s*$", raw)
    override = re.findall(r"(?m)^Override size: (\d+)x(\d+)\s*$", raw)
    if len(physical) != 1 or len(override) > 1:
        raise ScreenError("Display bounds unknown")
    width, height = map(int, (override or physical)[0])
    if not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise ScreenError("Display bounds invalid")
    return width, height


def ui_tree(shell, runner):
    # Every dump has a new path: a failed dump can never reuse an old UI tree.
    filename = "/data/local/tmp/rosy-cam-ui-" + uuid.uuid4().hex + ".xml"
    try:
        out = command([*shell, "uiautomator", "dump", filename], runner)
        if "dumped to:" not in out:
            raise ScreenError("Fresh UI dump unavailable")
        xml = command([*shell, "cat", filename], runner)
        if len(xml) > 2_000_000:
            raise ScreenError("UI dump too large")
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError:
            raise ScreenError("UI dump invalid") from None
        if root.tag != "hierarchy":
            raise ScreenError("UI hierarchy unknown")
        return root
    finally:
        command([*shell, "rm", "-f", filename], runner, optional=True)


def bounds(node, size, visible=True):
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
    if not match:
        raise ScreenError("UI bounds invalid")
    left, top, right, bottom = map(int, match.groups())
    limit = size if visible else (16384, 16384)
    if not (0 <= left < right <= limit[0] and 0 <= top < bottom <= limit[1]):
        raise ScreenError("UI bounds outside the display")
    return left, top, right, bottom


def light_button(root, desired, size):
    nodes = [n for n in root.iter("node") if n.get("package") == PACKAGE and n.get("text") == LIGHT_BUTTONS[desired]]
    if len(nodes) > 1:
        raise ScreenError("Duplicate light buttons; refused")
    if not nodes:
        return None
    parents = {child: parent for parent in root.iter() for child in parent}
    node = nodes[0]
    label = bounds(node, size)
    while node.get("clickable") != "true":
        if node.get("package") != PACKAGE or node.get("enabled") != "true":
            raise ScreenError("Untrusted light button")
        node = parents.get(node)
        if node is None or node.tag != "node":
            raise ScreenError("Light button is not actionable")
    if node.get("package") != PACKAGE or node.get("enabled") != "true":
        raise ScreenError("Untrusted light button")
    # Compose may expose a clipped clickable ancestor whose center is outside
    # the visible control. Tap only the visible exact-label rect, inside it.
    ancestor = bounds(node, size, visible=False)
    if not (ancestor[0] <= label[0] < label[2] <= ancestor[2] and
            ancestor[1] <= label[1] < label[3] <= ancestor[3]):
        raise ScreenError("Light label outside its clickable ancestor")
    return label


def check_request(state):
    if not state["running"] or not state["light_supported"] or state["light_limited"]:
        raise ScreenError("Camera light unavailable or limited; refused")


def light_action(config, target, action, runner):
    shell = [config["adb_path"], "-s", target, "shell"]
    state = light_state(shell, runner)
    if action == "light-status":
        return {"status": "connected", **state}
    desired = action == "light-request"
    if desired:
        check_request(state)
    if state["light_requested"] == desired:
        return {"status": "unchanged", **state}  # Never renew an existing request.
    if not state["running"]:
        raise ScreenError("Camera session is not running")
    guard = keyguard(shell, runner)
    if guard["showing"] and guard["secure"]:
        raise ScreenError("Secure keyguard locked; local unlock required")
    command([*shell, "input", "keyevent", "KEYCODE_WAKEUP"], runner)
    if guard["showing"]:
        command([*shell, "wm", "dismiss-keyguard"], runner)
    wait_keyguard_dismissed(shell, runner)
    command([*shell, "am", "start", "-W", "-n", PACKAGE + "/.MainActivity"], runner)
    prepare_camera_focus(shell, runner)
    size = display_size(shell, runner)
    button = None
    for attempt in range(4):
        focused(shell, runner)
        tree = ui_tree(shell, runner)
        button = light_button(tree, desired, size)
        if button is not None:
            break
        scroll = [n for n in tree.iter("node") if n.get("package") == PACKAGE and
                  n.get("scrollable") == "true" and n.get("enabled") == "true"]
        if len(scroll) != 1 or attempt == 3:
            raise ScreenError("Unique camera light control unavailable")
        left, top, right, bottom = bounds(scroll[0], size)
        if bottom - top < 100:
            raise ScreenError("Scrollable camera viewport too small")
        x = (left + right) // 2
        command([*shell, "input", "swipe", str(x), str(bottom - 20), str(x), str(top + 20), "300"], runner)
    # Recheck identity, foreground and live state immediately before the tap.
    if identity(config, target, runner) != (config["expected_serial"], config["expected_model"]):
        raise ScreenError("Device identity changed")
    focused(shell, runner)
    if keyguard(shell, runner)["showing"]:
        raise ScreenError("Keyguard appeared; refused")
    state = light_state(shell, runner)
    if not state["running"]:
        raise ScreenError("Camera session ended before the action")
    if desired:
        check_request(state)
    if state["light_requested"] == desired:
        return {"status": "unchanged", **state}
    # A fresh second UI dump must agree, avoiding stale coordinates after a scroll/layout change.
    if light_button(ui_tree(shell, runner), desired, size) != button:
        raise ScreenError("Camera UI changed; refused")
    left, top, right, bottom = button
    command([*shell, "input", "tap", str((left + right) // 2), str((top + bottom) // 2)], runner)
    for attempt in range(10):
        after = light_state(shell, runner)
        if after["running"] and after["light_requested"] == desired:
            return {"status": "request_confirmed" if desired else "cancel_confirmed", **after}
        if attempt < 9:
            time.sleep(0.1)
    raise ScreenError("Observed light request was not confirmed")


def execute(config, action, runner=subprocess.run):
    validate(config)
    if action not in {"status", "wake", "light-status", "light-request", "light-cancel"}:
        raise ScreenError("Unsupported action")
    target = verified(config, runner)
    if target is None:
        discovered = candidates(config, runner)
        if not discovered:
            raise ScreenError("Expected paired camera not found; use official wireless pairing")
        for candidate in discovered:
            try:
                command([config["adb_path"], "connect", candidate], runner)
                serial, model = identity(config, candidate, runner)
            except ScreenError:
                # A stale advertised port can fail while another port is live.
                continue
            if (serial, model) != (config["expected_serial"], config["expected_model"]):
                raise ScreenError("Discovered device identity mismatch; refused")
            target = verified(config, runner)
            if target is not None:
                break
        if target is None:
            raise ScreenError("Expected camera is not an authorized connection")
    # Check again immediately before the action; discovery names are not identity proof.
    if identity(config, target, runner) != (config["expected_serial"], config["expected_model"]):
        raise ScreenError("Device identity changed; refused")
    if action == "wake":
        command([config["adb_path"], "-s", target, "shell", "input", "keyevent", "KEYCODE_WAKEUP"], runner)
        return {"status": "wake_sent", "model": config["expected_model"]}
    if action.startswith("light-"):
        return light_action(config, target, action, runner)
    power = command([config["adb_path"], "-s", target, "shell", "dumpsys", "power"], runner)
    match = re.search(r"\bmWakefulness=(\w+)", power)
    return {"status": "connected", "model": config["expected_model"],
            "screen": match.group(1) if match else "unknown"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "wake", "light-status", "light-request", "light-cancel"])
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        result = execute(config, args.action)
    except (ScreenError, OSError, ValueError):
        # Never print config, ADB output, endpoint, pairing code or exception details.
        print(json.dumps({"status": "refused", "message": "Check private config, pairing and unique device identity"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
