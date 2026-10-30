"""Collection and offline preparation share a lock and retain signed code and TLS."""
import configparser
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def unit(name):
    parsed = configparser.ConfigParser(interpolation=None, strict=False)
    parsed.read(ROOT / "deploy/model_pc" / name)
    return parsed


def test_signed_model_jobs_resolve_the_pipeline_to_its_canonical_source():
    path = ROOT / "deploy/site/model_code_jobs.py"
    spec = importlib.util.spec_from_file_location("pilot_model_jobs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = "learning/curation/perception/pilot_review.py"
    file, base, name, mapped = module.job_entry(ROOT, "dataset/pilot_review.py")
    assert (file, base, name, mapped) == (ROOT / expected, ROOT, expected, expected)


def test_receiver_uses_configured_url_and_signed_entry_with_shared_lock():
    text = (ROOT / "deploy/model_pc/rosy-pilot-fetch@.service").read_text()
    command = unit("rosy-pilot-fetch@.service")["Service"]["ExecStart"]
    assert "${ROBOT_BASE_URL}" in command
    assert "Environment=ROBOT_BASE_URL=https://rosy-pinky-%i.local:8080" in text
    assert text.index("Environment=ROBOT_BASE_URL=") < text.index("EnvironmentFile=")
    assert "-I %h/.local/lib/rosy-model-code/rosy_model_code.py" in command
    assert "--config %h/.config/rosy/model-code.json exec dataset/fetch_http.py" in command
    assert "--ca-file" in command and "--token-file" in command
    assert "/usr/bin/flock --nonblock --conflict-exit-code 75 %t/rosy-pilot-collection.lock" in command
    assert set(unit("rosy-pilot-fetch@.service")["Service"]["SuccessExitStatus"].split()) == {"3", "75"}


def test_offline_pipeline_has_its_own_timer_and_no_robot_credentials():
    service = unit("rosy-pilot-process.service")["Service"]
    command = service["ExecStart"]
    assert "-I %h/.local/lib/rosy-model-code/rosy_model_code.py" in command
    assert "--config %h/.config/rosy/model-code.json exec dataset/pilot_review.py" in command
    assert "/usr/bin/flock --nonblock --conflict-exit-code 75 %t/rosy-pilot-collection.lock" in command
    assert all(flag in command for flag in ["--raw-root", "--video-dir", "--out", "--classes", "--state"])
    assert "--token" not in command and "--ca-file" not in command
    assert service["EnvironmentFile"] == "%h/.config/rosy/pilot-process.env"
    assert set(service["SuccessExitStatus"].split()) == {"3", "75"}
    timer = unit("rosy-pilot-process.timer")
    assert timer["Timer"]["OnUnitInactiveSec"] == "10min"
    assert timer["Timer"]["Unit"] == "rosy-pilot-process.service"
