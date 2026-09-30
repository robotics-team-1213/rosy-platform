"""D-373 decision 7: the operator doc stays in step with rosy_ml and leaks nothing."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs" / "deployment" / "learned-perception-operators.md"


def test_no_addresses_or_tokens():
    text = DOC.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text)  # this repo is public
    assert not re.search(r"\bhf_[A-Za-z0-9]{10,}", text)


def test_covers_every_rosy_ml_command_and_section():
    text = DOC.read_text(encoding="utf-8")
    for cmd in ("init", "doctor", "status", "deliver", "rollback", "release-hold",
                "harvest", "intake"):
        assert f"rosy_ml {cmd}" in text, cmd
    for heading in ("## 처음 한 번", "## 매일 쓰는 명령", "## 여러 사람이 같이 쓸 때",
                    "## 사이트 PC 자동 반영 켜기", "## 문제가 생기면"):
        assert heading in text
    for needle in ("history.jsonl", ".lock", "install-model-watch.sh", "authorized_keys"):
        assert needle in text


def test_relative_links_resolve():
    for target in re.findall(r"\]\(([^)#]+)\)", DOC.read_text(encoding="utf-8")):
        if "://" not in target:
            assert (DOC.parent / target).resolve().exists(), target


RULE = ("사람이 손으로 deliver/rollback 하면 그 로봇의 자동 반영은 멈춘다; "
        "`rosy_ml release-hold <robot>`로 다시 켠다.")


def test_hold_rule_and_exit_codes_are_stated():
    text = DOC.read_text(encoding="utf-8")
    assert RULE in text
    assert "/var/lib/rosy/models/hold" in text
    for code in ("75", "76", "3"):
        assert f"`{code}`" in text, code
    # holds live in the hold file, not in history: rotation cannot drop them
    assert "history.jsonl" in text and "감사" in text
    assert "마지막 포인터 기록이 그 rollback인 동안" not in text  # the old history rule is gone
