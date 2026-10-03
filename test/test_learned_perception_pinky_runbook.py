"""D-373: the Pinky first-deploy runbook points at things that exist and leaks nothing.

Same checks as the operator guide's (learning/training/perception/test/test_operator_doc.py),
plus every repository path the runbook names in backticks must exist, and the
switch, topics and commands it tells an operator to use must match the code.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "deployment" / "learned-perception-pinky.md"
REPO_PREFIXES = (".github/", ".claude/", "deploy/", "docs/", "src/", "test/", "tools/", "middleware/", "operations/", "contracts/", "learning/", "shared/", "integrations/")


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_no_addresses_or_tokens():
    text = _text()
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text)  # this repo is public
    assert not re.search(r"\bhf_[A-Za-z0-9]{10,}", text)


def test_relative_links_resolve():
    for target in re.findall(r"\]\(([^)#]+)\)", _text()):
        if "://" not in target:
            assert (DOC.parent / target).resolve().exists(), target


def test_named_repository_paths_exist():
    named = set()
    for span in re.findall(r"`([^`\n]+)`", _text()):
        for word in span.split():
            word = word.strip("\"'(),")
            if word.startswith(REPO_PREFIXES) and "<" not in word and "*" not in word:
                named.add(word.rstrip("/"))
    assert named, "the runbook names no repository paths"
    missing = sorted(p for p in named if not (ROOT / p).exists())
    assert not missing, missing


def test_sections_a_to_g():
    text = _text()
    for letter in "ABCDEFG":
        assert re.search(rf"^## {letter}\. ", text, re.MULTILINE), letter


def test_switch_matches_the_unit_and_the_launch_file():
    text = _text()
    unit = (ROOT / "deploy/robot/pinky_pro/native/rosy-camera.service").read_text(encoding="utf-8")
    launch = (ROOT / "middleware/perception/launch/camera_preview.launch.py").read_text(encoding="utf-8")
    assert "EnvironmentFile=-/etc/rosy/learned-perception.env" in unit
    assert "EnvironmentFile=-/etc/rosy/learned-perception.env" in text
    for name in ("ROSY_LEARNED_SHADOW", "ROSY_CAPTURE"):
        assert f"'{name}'" in launch
        assert f"{name}=true" in text
    assert "systemctl restart rosy-camera" in text


def test_topics_and_commands_match_the_code():
    text = _text()
    trigger = (ROOT / "middleware/perception/control/capture_trigger_node.py").read_text(encoding="utf-8")
    shadow = (ROOT / "middleware/perception/control/learned_lane_node.py").read_text(encoding="utf-8")
    status = (ROOT / "middleware/perception/control/sensing/perception/learned/status.py").read_text(
        encoding="utf-8")
    assert "'capture/request'" in trigger
    assert re.search(r'ros2 topic pub --once "\$NS/capture/request" std_msgs/msg/String', text)
    assert "perception/learned/status" in shadow and "perception/learned/status" in text
    assert "--qos-durability transient_local" in text
    for key in ("skip_ratio", "latency_ms_p50", "model_revision", "last_error"):
        assert f'"{key}"' in status and key in text
    rosy_ml = (ROOT / "learning/training/perception/rosy_ml.py").read_text(encoding="utf-8")
    for cmd in ("doctor", "deliver", "rollback", "release-hold", "harvest", "intake", "status"):
        assert f"rosy_ml {cmd}" in text, cmd
        assert f'"{cmd}"' in rosy_ml, cmd
    # the learned runtime has its own prefix and never changes the payload runtime id
    assert "/opt/rosy/learned-perception/site-packages" in text
    assert "learned-perception-requirements.txt" in text
    assert "NATIVE_PYTHON_RUNTIME" not in text and "compatible_predecessors" not in text
    # the one thing never automated
    assert "D-205" in text
