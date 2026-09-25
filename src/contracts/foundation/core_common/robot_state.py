"""One robot state for the buzzer, the lamp, the LCD and the dashboard (D-260).

D-260 decision 1 folds three inputs into one of five states, and decision 6
derives the todo list from fixed rules. Two readers apply the same table:

* ``rosy-boot-display`` (root side, user rosy-display) reads only files, so the
  robot still says what it is when CORE is down;
* CORE's ``GET /api/v1/host/status-summary`` feeds the dashboard summary line.

Both import this module, so the table cannot drift between them. It is
standard library only and never imports CORE or pydantic: the boot display
loads it from the release's site-packages next to ``emotion`` and ``rosylib``
(the same PYTHONPATH), and ``core_common/__init__.py`` imports nothing.

Inputs: the boot stage (``boot-status.json`` ``stage``, D-174), the device rows
of ``hardware.json`` (D-247; ``id``, ``state``, ``product``, ``label``), the
battery percent against the SAF-005 warning threshold, and the runtime mode,
whose ``motion_reason`` is D-247 decision 7's sentence (kept here as
``MOTION_REASON`` so CORE and the LCD say the same thing).

Every text has a Korean form (dashboard) and an ASCII form (LCD): the boot card
font is DejaVu, which has no Hangul, so the LCD speaks the same rule in English.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

BOOTING = "booting"
FAILED = "failed"
CAUTION = "caution"
READY_HELD = "ready_held"
READY = "ready"

#: D-260 decision 1: the five states. Order is the table's.
STATES = (BOOTING, FAILED, CAUTION, READY_HELD, READY)
LABELS = {
    BOOTING: "부팅 중",
    FAILED: "실패",
    CAUTION: "주의",
    READY_HELD: "준비됨 — 못 움직임",
    READY: "준비됨",
}
LCD_LABELS = {
    BOOTING: "Booting",
    FAILED: "Failed",
    CAUTION: "Caution",
    READY_HELD: "Ready - cannot move",
    READY: "Ready",
}
#: 1 is the highest. BOOTING has none: it is every stage before CORE_READY that is not FAILED.
PRIORITY = {FAILED: 1, CAUTION: 2, READY_HELD: 3, READY: 4}

#: SAF-005 default (rosy_default.yaml safety.battery_warning_percent); CORE passes its live policy.
BATTERY_WARNING_PERCENT = 20.0
DEFAULT_RUNTIME_MODE = "core"

#: D-247 decision 7: why the robot cannot move, per runtime mode. Empty: the mode holds nothing.
MOTION_REASON = {
    "core": "모터가 꺼진 CORE 전용 모드입니다. 관리자가 모터 모드로 올려야 움직입니다.",
    "motor": "모터 벤치 모드입니다. 저속 직접 제어만 됩니다. LiDAR와 자율주행(Nav2)은 꺼져 있습니다.",
}
#: The short form after the state label (D-260 4: ``준비됨 — 못 움직임: CORE 전용 모드``).
MODE_SHORT = {"core": ("CORE 전용 모드", "CORE only mode"), "motor": ("모터 벤치 모드", "motor bench mode")}

#: English device names for the LCD; the dashboard uses the probe's own Korean label.
LCD_DEVICE = {
    "motor.1": "motor 1", "motor.2": "motor 2", "lidar": "LiDAR", "imu": "IMU",
    "adc.battery": "ADC", "adc.ir0": "ADC", "adc.ir1": "ADC", "adc.ir2": "ADC",
    "adc.ultrasonic": "ADC", "camera": "camera", "lcd": "LCD", "buzzer": "buzzer",
    "lamp": "lamp", "pi.power": "Pi power",
}
STATE_WORDS = {
    "no_response": ("응답 없음", "no response"),
    "bus_missing": ("버스 없음", "bus missing"),
    "driver_missing": ("드라이버 없음", "driver missing"),
    "needs_human": ("사람 확인 필요", "needs a person"),
}

# D-260 decision 6: the todo rules, most urgent first. (id, Korean, LCD).
TODO_FAILED = "failed_unit"
TODO_BATTERY = "battery"
TODO_ADC = "adc_power_cycle"
TODO_CAMERA = "camera_cable"
TODO_LIDAR = "lidar_cable"
TODO_MOTOR = "motor_cable"
TODO_DEVICE = "device_check"
TODO_PI_POWER = "pi_power"
TODO_PROMOTE = "promote_motor"
TODO_TEST = "human_test"
TODO_TEXT = {
    TODO_BATTERY: ("배터리를 충전하세요", "Charge the battery"),
    TODO_ADC: ("로봇 전원을 완전히 껐다 켜세요 (ADC)", "Power-cycle the robot (ADC)"),
    TODO_CAMERA: ("카메라 케이블 확인", "Check the camera cable"),
    TODO_LIDAR: ("LiDAR 케이블 확인", "Check the LiDAR cable"),
    TODO_MOTOR: ("모터 케이블·전원 확인", "Check the motor cable"),
    TODO_PI_POWER: ("Pi 전원(5 V) 확인", "Check the Pi 5 V supply"),
    TODO_PROMOTE: ("관리자가 모터 모드로 승격", "Admin: promote to motor mode"),
}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def stage_kind(stage: Any) -> str:
    """``FAILED:rosy-core`` -> ``FAILED``; a missing stage is ``BOOTING`` (as the boot display)."""
    text = _text(stage).strip()
    return text.split(":", 1)[0] if text else "BOOTING"


def motion_reason(runtime_mode: Optional[str]) -> str:
    """D-247 7's sentence for the mode; a missing mode is CORE's own default, ``core``."""
    return MOTION_REASON.get(runtime_mode or DEFAULT_RUNTIME_MODE, "")


def battery_low(percent: Any, warning_percent: Any = BATTERY_WARNING_PERCENT) -> bool:
    """SAF-005 warning or below. No reading is not low (D-82 Law 0)."""
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        return False
    try:
        threshold = float(warning_percent)
    except (TypeError, ValueError):
        threshold = BATTERY_WARNING_PERCENT
    return float(percent) <= threshold


def _rows(devices: Optional[Iterable[Any]]) -> list[Mapping[str, Any]]:
    return [row for row in (devices or []) if isinstance(row, Mapping) and _text(row.get("id"))]


def _todo(todo_id: str, text: str, lcd: str, device: Optional[str] = None) -> dict:
    item = {"id": todo_id, "text": text, "lcd": lcd}
    if device is not None:
        item["device"] = device
    return item


def _device_name(row: Mapping[str, Any]) -> tuple[str, str]:
    device = _text(row.get("id"))
    return _text(row.get("label")) or device, LCD_DEVICE.get(device, device)


def todos(stage: Any = None, devices: Optional[Iterable[Any]] = None, *, battery_percent: Any = None,
          battery_warning_percent: Any = BATTERY_WARNING_PERCENT,
          runtime_mode: Optional[str] = None, failed_unit: Any = None) -> list[dict]:
    """The ordered todo list (D-260 decision 6), most urgent first, one entry per rule and device."""
    items: list[dict] = []
    kind = stage_kind(stage)
    if kind == "FAILED":
        unit = _text(failed_unit) or (_text(stage).split(":", 1)[1] if ":" in _text(stage) else "")
        unit = unit.removesuffix(".service")
        where = f" ({unit})" if unit else ""
        items.append(_todo(TODO_FAILED, f"실패한 부팅 단계를 확인하세요{where}", f"Check failed unit{where}"))
    if battery_low(battery_percent, battery_warning_percent):
        items.append(_todo(TODO_BATTERY, *TODO_TEXT[TODO_BATTERY]))
    rows = _rows(devices)
    silent = [row for row in rows if row.get("product") is True and row.get("state") == "no_response"]
    if any(_text(row["id"]).startswith("adc.") for row in silent):
        items.append(_todo(TODO_ADC, *TODO_TEXT[TODO_ADC], device="adc.battery"))
    for device, rule in (("camera", TODO_CAMERA), ("lidar", TODO_LIDAR)):
        if any(row["id"] == device for row in silent):
            items.append(_todo(rule, *TODO_TEXT[rule], device=device))
    motors = [row for row in silent if _text(row["id"]).startswith("motor.")]
    if motors:
        items.append(_todo(TODO_MOTOR, *TODO_TEXT[TODO_MOTOR], device=motors[0]["id"]))
    handled = ("adc.", "camera", "lidar", "motor.")
    for row in rows:
        state = row.get("state")
        if row.get("product") is not True or state not in {"no_response", "bus_missing", "driver_missing"}:
            continue
        if state == "no_response" and _text(row["id"]).startswith(handled):
            continue
        label, lcd = _device_name(row)
        word, lcd_word = STATE_WORDS[state]
        items.append(_todo(TODO_DEVICE, f"{label} {word} — 장치 카드 확인", f"Check {lcd}: {lcd_word}",
                           device=row["id"]))
    for row in rows:
        if row["id"] == "pi.power" and row.get("state") == "needs_human":
            items.append(_todo(TODO_PI_POWER, *TODO_TEXT[TODO_PI_POWER], device="pi.power"))
    if (runtime_mode or DEFAULT_RUNTIME_MODE) == "core" and kind == "CORE_READY":
        items.append(_todo(TODO_PROMOTE, *TODO_TEXT[TODO_PROMOTE]))
    for device, (word, lcd) in (("buzzer", ("부저", "buzzer")), ("lamp", ("램프", "lamp"))):
        if any(row["id"] == device and row.get("state") == "needs_human" for row in rows):
            items.append(_todo(TODO_TEST, f"{word}: 시험 동작으로 확인", f"Test the {lcd} (dashboard)",
                               device=device))
    return items


def evaluate(stage: Any = None, devices: Optional[Iterable[Any]] = None, *, battery_percent: Any = None,
             battery_warning_percent: Any = BATTERY_WARNING_PERCENT, runtime_mode: Optional[str] = None,
             failed_unit: Any = None) -> dict:
    """D-260 decision 1: the one state, its reason line (Korean and LCD) and the todo list.

    Priority when conditions overlap: FAILED > CAUTION > READY_HELD > READY; the
    lower ones stay in ``todos``. Before CORE_READY (and not FAILED) it is BOOTING
    whatever else holds. Missing or malformed inputs never raise.
    """
    kind = stage_kind(stage)
    items = todos(stage, devices, battery_percent=battery_percent,
                  battery_warning_percent=battery_warning_percent, runtime_mode=runtime_mode,
                  failed_unit=failed_unit)
    rows = _rows(devices)
    silent = [row for row in rows if row.get("product") is True and row.get("state") == "no_response"]
    held = motion_reason(runtime_mode)
    reason, lcd_reason = "", ""
    if kind == "FAILED":
        state = FAILED
        unit = _text(failed_unit) or (_text(stage).split(":", 1)[1] if ":" in _text(stage) else "")
        reason = lcd_reason = unit.removesuffix(".service")
    elif kind != "CORE_READY":
        state = BOOTING
        reason, lcd_reason = ("CORE 준비 전", "waiting for CORE")
        if kind == "PROVISIONED":
            reason, lcd_reason = ("설정 완료 · CORE 준비 전", "provisioned, waiting for CORE")
    elif battery_low(battery_percent, battery_warning_percent) or silent:
        state = CAUTION
        if battery_low(battery_percent, battery_warning_percent):
            reason = f"배터리 {float(battery_percent):.0f} %"
            lcd_reason = f"battery {float(battery_percent):.0f} %"
        else:
            label, lcd = _device_name(silent[0])
            reason, lcd_reason = f"{label} 응답 없음", f"{lcd} no response"
    elif held:
        state = READY_HELD
        reason, lcd_reason = MODE_SHORT.get(runtime_mode or DEFAULT_RUNTIME_MODE, (held, "held"))
    else:
        state = READY
    return {
        "state": state,
        "label": LABELS[state],
        "lcd_label": LCD_LABELS[state],
        "reason": reason,
        "lcd_reason": lcd_reason,
        "motion_reason": held if kind == "CORE_READY" else "",
        "todos": items,
    }


def state_line(result: Mapping[str, Any], *, lcd: bool = False) -> str:
    """``준비됨 — 못 움직임: CORE 전용 모드`` (or its LCD form); the label alone without a reason."""
    label = result["lcd_label"] if lcd else result["label"]
    reason = result["lcd_reason"] if lcd else result["reason"]
    return f"{label}: {reason}" if reason else label


def device_counts(devices: Optional[Iterable[Any]]) -> dict:
    """``정상 N/M`` over every observed row, and the rows that are not ok in probe order.

    ``not_measured`` is not a problem: another unit holds the bus (D-247 4).
    """
    rows = _rows(devices)
    problems = [{"id": row["id"], "label": _text(row.get("label")) or row["id"], "state": row.get("state"),
                 "product": row.get("product") is True}
                for row in rows if row.get("state") not in {"ok", "not_measured"}]
    # Product devices first: a bench IMU on the bus must not hide a silent camera.
    problems.sort(key=lambda item: not item["product"])
    return {"ok": sum(1 for row in rows if row.get("state") == "ok"), "total": len(rows), "problems": problems}
