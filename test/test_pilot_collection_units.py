"""Collection and offline preparation share a lock and retain signed code and TLS."""
import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def unit(name):
    parsed = configparser.ConfigParser(interpolation=None, strict=False)
    parsed.read(ROOT / "deploy/model_pc" / name)
    return parsed


def test_receiver_uses_configured_url_and_signed_entry_with_shared_lock():
    text = (ROOT / "deploy/model_pc/rosy-pilot-fetch@.service").read_text()
    command = unit("rosy-pilot-fetch@.service")["Service"]["ExecStart"]
    assert "${ROBOT_BASE_URL}" in command
    assert "Environment=ROBOT_BASE_URL=https://rosy-pinky-%i.local:8080" in text
    assert text.index("Environment=ROBOT_BASE_URL=") < text.index("EnvironmentFile=")
    assert "model-code/current/learning/curation/perception/fetch_http.py" in command
    assert "--ca-file" in command and "--token-file" in command
    assert "/usr/bin/flock --nonblock --conflict-exit-code 75 %t/rosy-pilot-collection.lock" in command


def test_offline_pipeline_has_its_own_timer_and_no_robot_credentials():
    service = unit("rosy-pilot-process.service")["Service"]
    command = service["ExecStart"]
    assert "model-code/current/learning/curation/perception/pilot_review.py" in command
    assert "/usr/bin/flock --nonblock --conflict-exit-code 75 %t/rosy-pilot-collection.lock" in command
    assert all(flag in command for flag in ["--raw-root", "--video-dir", "--out", "--classes", "--state"])
    assert "--token" not in command and "--ca-file" not in command
    assert service["EnvironmentFile"] == "%h/.config/rosy/pilot-process.env"
    assert service["SuccessExitStatus"] == "75"
    timer = unit("rosy-pilot-process.timer")
    assert timer["Timer"]["OnUnitInactiveSec"] == "10min"
    assert timer["Timer"]["Unit"] == "rosy-pilot-process.service"
