"""Interface-only surface: the .srv files this package ships (D-73)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRV = ROOT / "srv"
EXPECTED = ("Emotion.srv", "SetBrightness.srv", "SetLamp.srv", "SetLed.srv")


def test_service_definitions_exist_and_are_nonempty():
    names = {path.name for path in SRV.glob("*.srv")}
    assert set(EXPECTED) <= names
    for name in EXPECTED:
        text = (SRV / name).read_text(encoding="utf-8").strip()
        assert text, f"{name} is empty"
        assert "---" in text


def test_service_fields_match_the_device_contract():
    led = (SRV / "SetLed.srv").read_text(encoding="utf-8")
    assert "string command" in led
    assert "int32 r" in led and "int32 g" in led and "int32 b" in led
    emotion = (SRV / "Emotion.srv").read_text(encoding="utf-8")
    assert "string emotion" in emotion
    lamp = (SRV / "SetLamp.srv").read_text(encoding="utf-8")
    assert "ColorRGBA color" in lamp
    brightness = (SRV / "SetBrightness.srv").read_text(encoding="utf-8")
    assert "int32 brightness" in brightness
