"""Interface-only surface: the .srv files this package ships (D-73)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRV = ROOT / "srv"
EXPECTED = ("Emotion.srv", "SetBrightness.srv", "SetLamp.srv", "SetLed.srv", "PilotRecordingStart.srv")


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


def test_recording_start_is_additive_and_bounds_the_preview_mode():
    service = (SRV / 'PilotRecordingStart.srv').read_text(encoding='utf-8')
    request, response = service.split('---')
    assert 'uint8 RAW=0' in request and 'uint8 ANNOTATED=1' in request
    assert 'uint8 preview_mode' in request
    assert 'bool success' in response and 'string message' in response
    assert '"srv/PilotRecordingStart.srv"' in (ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')


def _map_adoption_fields():
    text = (SRV / 'MapAdoption.srv').read_text(encoding='utf-8')
    request, response = text.split('---')
    def fields(section):
        return tuple(line.strip() for line in section.splitlines()
                     if line.strip() and not line.lstrip().startswith('#'))
    return fields(request), fields(response)


def test_native_map_request_is_only_a_fixed_challenge_without_a_motion_command():
    request, _ = _map_adoption_fields()
    assert request == ('uint8[16] challenge',)


def test_native_map_response_bounds_original_identity_and_native_owner():
    _, response = _map_adoption_fields()
    assert response == (
        'uint16 CONTRACT_VERSION=1', 'uint16 contract_version', 'uint8[16] challenge',
        'uint8[16] instance_id', 'uint64 generation', 'bool active', 'bool adopted',
        'string<=64 reason', 'string<=32 role', 'string<=256 node_fqn', 'string<=64 build_id',
        'string<=64 config_digest', 'string<=64 grid_digest', 'string<=128 frame_id',
        'uint32 width', 'uint32 height', 'float64 resolution', 'float64[7] origin',
        'uint64 source_stamp_ns', 'uint64 map_load_time_ns',
    )


def test_native_map_service_is_in_the_real_rosidl_generation_list():
    assert '"srv/MapAdoption.srv"' in (ROOT / 'CMakeLists.txt').read_text(encoding='utf-8')
