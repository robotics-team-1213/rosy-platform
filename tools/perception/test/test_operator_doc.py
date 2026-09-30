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


def test_store_is_the_source_of_truth_and_hf_is_optional():
    text = DOC.read_text(encoding="utf-8")
    for needle in ("rosy_ml store-status", "--store", "datasets/<name>/<content_sha>",
                   "models/inbox", "models/accepted", "models/rejected", "READY",
                   "store-inbox:", "NAS", "Google Drive", "publish.py"):
        assert needle in text, needle
    assert "HF는 선택" in text
    init = text.split("rosy_ml init", 1)[1].split("```", 1)[0]
    assert "--store" in init and "--hf-repo" not in init  # the first-time setup needs no HF


TRAINING = ROOT / "tools" / "perception" / "training"


def test_trainer_docs_need_no_hf():
    for name in ("COLAB.md", "README.md"):
        text = (TRAINING / name).read_text(encoding="utf-8")
        for needle in ("store", "READY", "models/inbox", "content_sha"):
            assert needle in text, (name, needle)
        assert "HF는 선택" in text, name
        assert "로컬 stub 실행으로만" in text, name  # never verified on real Colab


RUNBOOK = ROOT / "docs" / "deployment" / "learned-perception-pinky.md"
PAYLOAD = ROOT / "deploy" / "robot" / "pinky_pro" / "image" / "build-native-payload.sh"
NATIVE_SRC = ROOT / "deploy" / "robot" / "pinky_pro" / "native"


def test_runbook_uses_the_native_path_the_release_payload_packs():
    script = PAYLOAD.read_text(encoding="utf-8")
    m = re.search(r'"\$NATIVE_RUNTIME_SOURCE/install-native-runtime\.sh" "\$RELEASE_ROOT/([^"]+)"',
                  script)
    assert m, "build-native-payload.sh no longer installs the native runtime into the release"
    packed = m.group(1)
    # install-native-runtime.sh copies its whole folder (deploy/robot/pinky_pro/native)
    assert 'cp -a "$SCRIPT_DIR" "$DESTINATION"' in (
        NATIVE_SRC / "install-native-runtime.sh").read_text(encoding="utf-8")
    on_device = f"/opt/rosy/current/{packed}/"
    for doc in (RUNBOOK, DOC):
        text = doc.read_text(encoding="utf-8")
        used = re.findall(r"/opt/rosy/current/deploy/[A-Za-z0-9_./-]+", text)
        for path in used:
            assert path.startswith(on_device), (doc.name, path, on_device)
            assert (NATIVE_SRC / path.removeprefix(on_device)).exists(), path
    assert on_device in RUNBOOK.read_text(encoding="utf-8")


def test_exit_code_table_is_exact():
    import sys
    for p in ("model", "dataset"):
        sys.path.insert(0, str(ROOT / "tools" / "perception" / p))
    import deliver
    import harvest
    import watch
    text = DOC.read_text(encoding="utf-8")
    section = text.split("### 종료 코드", 1)[1].split("\n## ", 1)[0]
    rows = set()
    for line in section.splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[1].isdigit():
            rows.add((cells[0], int(cells[1])))
    want = {("deliver", c) for c in (0, 1, 2, deliver.HISTORY_EXIT, deliver.LOCK_BUSY_EXIT,
                                     deliver.HELD_EXIT)}
    want |= {("harvest", c) for c in (0, 1, 2, harvest.EXIT_NOT_IDLE)}
    want |= {("watch", c) for c in (0, 1, 2, watch.LIST_FAILED_EXIT)}
    want |= {("doctor", c) for c in (0, 1, 2)}
    assert rows == want
