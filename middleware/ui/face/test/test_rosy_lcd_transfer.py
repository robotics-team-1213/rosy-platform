"""The field LCD must avoid SPI0 DMA transfers that time out on Pi 5."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest


def test_lcd_data_is_sent_in_order_without_dma_sized_transfers(monkeypatch):
    spi = ModuleType("spidev")
    rpi = ModuleType("RPi")
    gpio = ModuleType("RPi.GPIO")
    gpio.HIGH = 1
    outputs = []
    gpio.output = lambda pin, value: outputs.append((pin, value))
    rpi.GPIO = gpio
    for module in (spi, rpi, gpio):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    path = Path(__file__).resolve().parents[1] / "emotion" / "rosy_lcd.py"
    spec = importlib.util.spec_from_file_location("emotion._lcd_transfer_under_test", path)
    lcd_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lcd_module)

    transfers = []
    lcd = lcd_module.LCD.__new__(lcd_module.LCD)
    lcd.spi = type("SPI", (), {"writebytes2": lambda _self, data: transfers.append(bytes(data))})()
    payload = bytes(range(256)) + bytes(range(37))
    lcd._write_data_buffer(np.frombuffer(payload, dtype=np.uint8).reshape(1, len(payload), 1))

    assert outputs == [(lcd_module.DC_PIN, gpio.HIGH)]
    assert b"".join(transfers) == payload
    assert max(map(len, transfers)) <= 64

    transfers.clear()
    lcd._write_data_buffer(list(range(80)))
    assert b"".join(transfers) == bytes(range(80))
    assert max(map(len, transfers)) <= 64


def test_panel_sends_only_changed_rectangle_and_redraws_after_sleep(monkeypatch):
    spi = ModuleType("spidev")
    rpi = ModuleType("RPi")
    gpio = ModuleType("RPi.GPIO")
    gpio.HIGH = 1
    gpio.LOW = 0
    gpio.output = lambda *_: None
    rpi.GPIO = gpio
    for module in (spi, rpi, gpio):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    path = Path(__file__).resolve().parents[1] / "emotion" / "rosy_lcd.py"
    spec = importlib.util.spec_from_file_location("emotion._lcd_delta_under_test", path)
    lcd_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lcd_module)

    lcd = lcd_module.LCD.__new__(lcd_module.LCD)
    lcd.w, lcd.h = 4, 3
    windows, sent = [], []
    lcd._write_cmd = lambda *_: None
    lcd._write_data = lambda *_: None
    lcd._set_windows = lambda *args: windows.append(args)
    lcd._write_data_buffer = lambda data: sent.append(bytes(data))

    first = np.zeros((3, 4, 2), dtype=np.uint8)
    lcd.show_panel(first)
    assert windows == [(0, 0, 4, 3)]
    assert sent == [first.tobytes()]

    changed = first.copy()
    changed[1, 2] = (12, 34)
    lcd.show_panel(changed)
    assert windows[-1] == (2, 1, 3, 2)
    assert all(type(value) is int for value in windows[-1])
    assert sent[-1] == bytes((12, 34))
    lcd.show_panel(changed)
    assert len(sent) == 2

    lcd.sleep()
    lcd.show_panel(changed)
    assert windows[-1] == (0, 0, 4, 3)
    assert sent[-1] == changed.tobytes()

    def fail_once(_data):
        raise OSError("SPI interrupted")

    lcd._write_data_buffer = fail_once
    changed[0, 0] = (56, 78)
    with pytest.raises(OSError, match="SPI interrupted"):
        lcd.show_panel(changed)
    lcd._write_data_buffer = lambda data: sent.append(bytes(data))
    lcd.show_panel(changed)
    assert windows[-1] == (0, 0, 4, 3)
    assert sent[-1] == changed.tobytes()
