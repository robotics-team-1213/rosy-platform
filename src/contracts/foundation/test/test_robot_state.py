"""D-260: the robot state rule table shared by the boot display and CORE."""

from __future__ import annotations

import ast
from pathlib import Path
import sys

import pytest

from core_common import robot_state as rs

MODULE = Path(rs.__file__)


def _row(device_id: str, state: str = "ok", product: bool = True, label: str | None = None) -> dict:
    return {"id": device_id, "label": label or device_id, "state": state, "product": product}


OK_BOARD = [_row("motor.1"), _row("lidar"), _row("adc.battery"), _row("camera"),
            _row("imu", "bus_missing", product=False), _row("buzzer", "ok", product=False)]


# --- every row of the D-260 decision 1 table --------------------------------


@pytest.mark.parametrize("stage", [None, "", "BOOTING", "PROVISIONED"])
def test_before_core_ready_is_booting(stage):
    result = rs.evaluate(stage, OK_BOARD, runtime_mode="hardware")

    assert result["state"] == rs.BOOTING and result["label"] == "부팅 중"
    assert result["motion_reason"] == ""


@pytest.mark.parametrize("stage,unit", [("FAILED:rosy-core", "rosy-core"), ("FAILED", "")])
def test_a_failed_stage_is_failed(stage, unit):
    result = rs.evaluate(stage, OK_BOARD, runtime_mode="hardware")

    assert result["state"] == rs.FAILED and result["label"] == "실패"
    assert result["reason"] == unit
    assert result["todos"][0]["id"] == rs.TODO_FAILED


def test_failed_unit_from_the_status_file_wins_over_the_label():
    result = rs.evaluate("FAILED:rosy-first-boot", [], failed_unit="rosy-first-boot.service")

    assert result["reason"] == "rosy-first-boot"
    assert result["todos"][0]["text"] == "실패한 부팅 단계를 확인하세요 (rosy-first-boot)"


def test_low_battery_is_caution():
    result = rs.evaluate("CORE_READY", OK_BOARD, battery_percent=15, runtime_mode="hardware")

    assert result["state"] == rs.CAUTION and result["reason"] == "배터리 15 %"
    assert rs.state_line(result) == "주의: 배터리 15 %"
    assert rs.state_line(result, lcd=True) == "Caution: battery 15 %"


def test_the_warning_threshold_is_inclusive_and_configurable():
    assert rs.battery_low(20) and not rs.battery_low(20.5)
    assert rs.battery_low(30, 35) and not rs.battery_low(30, 25)
    assert rs.battery_low(10, "nonsense")  # a broken threshold falls back to SAF-005's 20


@pytest.mark.parametrize("percent", [None, "12", True, float("nan")])
def test_no_battery_reading_is_not_low(percent):
    assert rs.evaluate("CORE_READY", OK_BOARD, battery_percent=percent,
                       runtime_mode="hardware")["state"] == rs.READY


def test_a_silent_product_device_is_caution():
    board = OK_BOARD + [_row("camera", "no_response", label="카메라 (OV5647)")]
    board = [row for row in board if not (row["id"] == "camera" and row["state"] == "ok")]

    result = rs.evaluate("CORE_READY", board, runtime_mode="hardware")

    assert result["state"] == rs.CAUTION
    assert rs.state_line(result) == "주의: 카메라 (OV5647) 응답 없음"
    assert rs.state_line(result, lcd=True) == "Caution: camera no response"


def test_a_silent_bench_device_is_not_caution():
    result = rs.evaluate("CORE_READY", [_row("imu", "no_response", product=False)], runtime_mode="hardware")

    assert result["state"] == rs.READY


def test_core_ready_with_a_motion_reason_is_ready_held():
    result = rs.evaluate("CORE_READY", OK_BOARD, runtime_mode="core")

    assert result["state"] == rs.READY_HELD
    assert rs.state_line(result) == "준비됨 — 못 움직임: CORE 전용 모드"
    assert rs.state_line(result, lcd=True) == "Ready - cannot move: CORE only mode"
    assert result["motion_reason"] == rs.MOTION_REASON["core"]


def test_motor_bench_mode_is_held_by_its_d247_reason():
    result = rs.evaluate("CORE_READY", OK_BOARD, runtime_mode="motor")

    assert result["state"] == rs.READY_HELD and result["reason"] == "모터 벤치 모드"


def test_hardware_mode_with_nothing_wrong_is_ready():
    result = rs.evaluate("CORE_READY", OK_BOARD, battery_percent=80, runtime_mode="hardware")

    assert result == {"state": rs.READY, "label": "준비됨", "lcd_label": "Ready", "reason": "",
                      "lcd_reason": "", "motion_reason": "", "todos": []}
    assert rs.state_line(result) == "준비됨"


def test_a_missing_runtime_mode_is_core_s_own_default():
    assert rs.evaluate("CORE_READY", OK_BOARD)["state"] == rs.READY_HELD
    assert rs.motion_reason(None) == rs.MOTION_REASON["core"]


# --- priority collisions --------------------------------------------------------


def test_failed_beats_caution_and_held_and_keeps_the_rest_as_todos():
    board = [_row("adc.battery", "no_response"), _row("camera", "no_response")]

    result = rs.evaluate("FAILED:rosy-core", board, battery_percent=5, runtime_mode="core")

    assert result["state"] == rs.FAILED
    assert [item["id"] for item in result["todos"]] == [
        rs.TODO_FAILED, rs.TODO_BATTERY, rs.TODO_ADC, rs.TODO_CAMERA]


def test_caution_beats_held():
    result = rs.evaluate("CORE_READY", [_row("adc.battery", "no_response")], runtime_mode="core")

    assert result["state"] == rs.CAUTION
    assert [item["id"] for item in result["todos"]] == [rs.TODO_ADC, rs.TODO_PROMOTE]


def test_battery_is_the_caution_reason_before_a_device():
    result = rs.evaluate("CORE_READY", [_row("camera", "no_response")], battery_percent=9,
                         runtime_mode="hardware")

    assert result["reason"] == "배터리 9 %"


def test_booting_beats_caution():
    result = rs.evaluate("BOOTING", [_row("camera", "no_response")], battery_percent=5)

    assert result["state"] == rs.BOOTING
    assert [item["id"] for item in result["todos"]] == [rs.TODO_BATTERY, rs.TODO_CAMERA]


def test_the_priority_table_is_the_adr_s():
    assert rs.PRIORITY == {rs.FAILED: 1, rs.CAUTION: 2, rs.READY_HELD: 3, rs.READY: 4}
    assert set(rs.LABELS) == set(rs.LCD_LABELS) == set(rs.STATES)
    assert [rs.LABELS[state] for state in rs.STATES] == ["부팅 중", "실패", "주의", "준비됨 — 못 움직임", "준비됨"]
    assert all(text.isascii() for text in rs.LCD_LABELS.values())


# --- the todo rules (D-260 decision 6) -----------------------------------------


def test_every_todo_rule():
    board = [
        _row("adc.ir0", "no_response"), _row("adc.battery", "no_response"),
        _row("camera", "no_response"), _row("lidar", "no_response"), _row("motor.2", "no_response"),
        _row("adc.ultrasonic", "bus_missing", label="초음파 거리 (ADC)"),
        _row("pi.power", "needs_human", product=False),
        _row("buzzer", "needs_human", product=False), _row("lamp", "needs_human", product=False),
    ]

    items = rs.todos("CORE_READY", board, battery_percent=10, runtime_mode="core")

    assert [(item["id"], item["text"]) for item in items] == [
        (rs.TODO_BATTERY, "배터리를 충전하세요"),
        (rs.TODO_ADC, "로봇 전원을 완전히 껐다 켜세요 (ADC)"),
        (rs.TODO_CAMERA, "카메라 케이블 확인"),
        (rs.TODO_LIDAR, "LiDAR 케이블 확인"),
        (rs.TODO_MOTOR, "모터 케이블·전원 확인"),
        (rs.TODO_DEVICE, "초음파 거리 (ADC) 버스 없음 — 장치 카드 확인"),
        (rs.TODO_PI_POWER, "Pi 전원(5 V) 확인"),
        (rs.TODO_PROMOTE, "관리자가 모터 모드로 승격"),
        (rs.TODO_TEST, "부저: 시험 동작으로 확인"),
        (rs.TODO_TEST, "램프: 시험 동작으로 확인"),
    ]
    assert [item.get("device") for item in items] == [
        None, "adc.battery", "camera", "lidar", "motor.2", "adc.ultrasonic", "pi.power", None, "buzzer", "lamp"]
    assert all(item["lcd"].isascii() and item["lcd"] for item in items)


def test_promotion_is_asked_only_once_core_is_ready():
    assert rs.todos("BOOTING", [], runtime_mode="core") == []
    assert [item["id"] for item in rs.todos("CORE_READY", [], runtime_mode="motor")] == []


def test_ok_and_not_measured_rows_make_no_todo():
    board = [_row("lidar", "not_measured"), _row("camera"), _row("buzzer", "ok", product=False)]

    assert rs.todos("CORE_READY", board, runtime_mode="hardware") == []


# --- empty and malformed inputs -------------------------------------------------


@pytest.mark.parametrize("devices", [None, [], [None, 3, "x", {}, {"id": ""}, {"id": 5, "state": "no_response"}]])
def test_missing_or_malformed_devices_never_raise(devices):
    result = rs.evaluate("CORE_READY", devices, runtime_mode="hardware")

    assert result["state"] == rs.READY and result["todos"] == []
    assert rs.device_counts(devices) == {"ok": 0, "total": 0, "problems": []}


@pytest.mark.parametrize("stage", [None, 7, {"stage": "x"}, "WHATEVER"])
def test_an_unknown_stage_is_booting(stage):
    assert rs.evaluate(stage, [])["state"] == rs.BOOTING


def test_device_counts_put_product_problems_first():
    board = [_row("imu", "bus_missing", product=False), _row("motor.1"), _row("lidar", "not_measured"),
             _row("camera", "no_response", label="카메라")]

    counts = rs.device_counts(board)

    assert (counts["ok"], counts["total"]) == (1, 4)
    assert [item["id"] for item in counts["problems"]] == ["camera", "imu"]
    assert counts["problems"][0] == {"id": "camera", "label": "카메라", "state": "no_response", "product": True}


# --- one module for both readers --------------------------------------------------


def test_the_module_is_standard_library_only():
    # The boot display imports it as rosy-display without CORE's dependencies.
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported
    assert (MODULE.parent / "__init__.py").read_text(encoding="utf-8").strip() == ""


def test_moved_card_setup_is_caution_with_registration_action():
    result = rs.evaluate("SETUP")
    assert result["state"] == "caution"
    assert result["lcd_reason"] == "register new device"
    assert result["todos"][0]["id"] == "new_device_setup"
