"""D-373 decision 7: deploy/site/install-model-watch.sh, checked without running it."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "deploy" / "site" / "install-model-watch.sh"


def _text():
    return SCRIPT.read_text(encoding="utf-8")


def test_script_is_strict_bash_and_parses():
    text = _text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    r = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_dry_run_and_root_guard():
    text = _text()
    assert "--dry-run)" in text
    assert re.search(r'\[ "\$DRY" = 1 \] \|\| \[ "\$\(id -u\)" -eq 0 \]', text)
    # every change goes through run(), which only prints under --dry-run
    for verb in ("useradd", "ssh-keygen", "systemctl", "chown", "chmod", "runuser"):
        for line in text.splitlines():
            if re.search(rf"(^|\s){verb}\s", line) and not line.lstrip().startswith("#") \
                    and "echo" not in line and "printf" not in line:
                assert "run " in line, line


def test_idempotent_and_never_overwrites_config_or_secrets():
    text = _text()
    assert 'getent passwd "$SVC" >/dev/null || run useradd --system' in text
    assert '[ -e "$CONFIG" ] || run install -o root -g "$SVC" -m 0640' in text
    assert '[ -e "$KEY" ] || run ssh-keygen' in text
    assert '[ -e "$TOKEN" ] || run install -o root -g "$SVC" -m 0640 /dev/null "$TOKEN"' in text
    # the token file is only ever created empty: nothing is written into it
    for line in text.splitlines():
        if "TOKEN" in line:
            assert not re.search(r">>?\s*\"?\$TOKEN|tee\b.*\$TOKEN", line), line


def test_installs_units_and_enables_only_a_filled_config():
    text = _text()
    assert "rosy-model-watch.service" in text and "rosy-model-watch.timer" in text
    enable = text.index("run systemctl enable --now rosy-model-watch.timer")
    assert text.rindex("configured", 0, enable) < enable  # guarded by the placeholder check
    assert "runuser -u \"$SVC\" --" in text and "doctor --watch-config" in text
    for name in ("rosy-model-watch.service", "rosy-model-watch.timer", "model-watch.yaml.example"):
        assert (SCRIPT.parent / name).is_file()


def test_store_folder_is_created_and_made_writable_by_a_drop_in():
    text = _text()
    assert "STORE=" in text and "store:" in text
    assert '[ -d "$STORE" ] || run install -d -o "$SVC" -g "$SVC"' in text
    for sub in ("datasets", "models/inbox", "models/accepted", "models/rejected"):
        assert sub in text, sub
    assert "rosy-model-watch.service.d" in text and "ReadWritePaths=" in text


def test_hf_token_placeholder_only_for_backend_hf():
    text = _text()
    token = text.index('[ -e "$TOKEN" ] || run install')
    block = text[text.rindex("\nif ", 0, token):token]
    assert 'if [ "$BACKEND" = hf ]' in block and "\nfi\n" not in block


WRAPPER = SCRIPT.parent / "rosy-model-watch"


def _locate(src: Path) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    env = {**os.environ, "ROSY_MODEL_WATCH_SRC": src.as_posix()}
    return subprocess.run([bash, WRAPPER.as_posix(), "locate"], capture_output=True, text=True, env=env)


def test_installer_installs_the_wrapper_and_doctor_runs_through_it():
    text = _text()
    assert 'run install -D -o root -g root -m 0755 "$HERE/rosy-model-watch" "$WRAPPER"' in text
    assert "WRAPPER=/opt/rosy/model-watch/bin/rosy-model-watch" in text
    assert '"$WRAPPER" doctor --watch-config "$CONFIG"' in text
    data = WRAPPER.read_bytes()
    assert data.startswith(b"#!/usr/bin/env bash\n") and b"\r" not in data


@pytest.mark.parametrize("layouts, expected", [
    (("learning/training/perception",), "learning/training/perception"),
    (("tools/perception",), "tools/perception"),
    (("learning/training/perception", "tools/perception"), "learning/training/perception"),
])
def test_wrapper_prefers_the_moved_folder_and_falls_back(tmp_path, layouts, expected):
    for layout in layouts:
        (tmp_path / layout / "model").mkdir(parents=True)
        (tmp_path / layout / "model" / "watch.py").write_text("", encoding="utf-8")
    r = _locate(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("/" + expected)


def test_wrapper_fails_without_a_watcher(tmp_path):
    r = _locate(tmp_path)
    assert r.returncode == 1 and "no perception tools" in r.stderr
