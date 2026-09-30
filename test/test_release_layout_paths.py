"""On-device paths into a release must use the release layout, not the repo layout.

A release keeps its native runtime at deploy/robot/native/ (build-native-payload.sh,
REQUIRED_PAYLOAD), whatever the repo calls the folder. e3b0c95e moved the repo
copy to deploy/robot/pinky_pro/ and a blanket rewrite also changed the on-device
paths, which broke the image build and rosy-core's ExecStartPost.
"""

import re
import subprocess
from pathlib import Path

import build_payload_release

ROOT = Path(__file__).resolve().parents[1]
RELEASE_NATIVE = "deploy/robot/native/"
INTO_RELEASE = re.compile(
    r"""opt/rosy/(?:current|releases/[^/\s"']+)/(deploy/[^\s"'`)]+)"""
    r"""|release(?:_dir)? / "(deploy/[^"]+)\"""")


def _deploy_files():
    listed = subprocess.run(["git", "ls-files", "deploy", "test"], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout.split()
    return [ROOT / name for name in listed
            if not name.endswith(".md") and (ROOT / name).is_file()]


def test_payload_builder_uses_the_release_native_folder():
    assert f"{RELEASE_NATIVE}rosy-runtime.target" in build_payload_release.REQUIRED_PAYLOAD
    builder = (ROOT / "deploy/robot/pinky_pro/image/build-native-payload.sh").read_text(encoding="utf-8")
    assert '"$RELEASE_ROOT/deploy/robot/native"' in builder


def test_every_on_device_release_path_uses_the_release_layout():
    wrong = []
    for path in _deploy_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in INTO_RELEASE.finditer(text):
            target = (match.group(1) or match.group(2)).rstrip("/") + "/"
            if not target.startswith(RELEASE_NATIVE):
                wrong.append(f"{path.relative_to(ROOT).as_posix()}: {match.group(0)}")
    assert not wrong, wrong
