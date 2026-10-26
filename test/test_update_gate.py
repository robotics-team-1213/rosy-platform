"""D-805: updaters run only when nothing freezes updates; anything uncertain skips (fail closed)."""
from pathlib import Path
import http.server
import os
import re
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "deploy/hosts/common/host-state/rosy-update-gate"
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell fake git")


def gate(tmp_path, *, git_script=None, local=False, home_freeze=False, refs_url="http://127.0.0.1:9/closed"):
    env = {**os.environ, "ROSY_HOST_STATE_ROOT": str(tmp_path / "root"), "HOME": str(tmp_path / "home"),
           "ROSY_UPDATE_GATE_REFS": refs_url}
    if git_script is not None:
        fake = tmp_path / "git"
        fake.write_text("#!/bin/sh\n" + git_script)
        fake.chmod(0o755)
        env["ROSY_UPDATE_GATE_GIT"] = str(fake)
    else:
        env["ROSY_UPDATE_GATE_GIT"] = str(tmp_path / "no-such-git")
    if local:
        (tmp_path / "root/etc/rosy").mkdir(parents=True)
        (tmp_path / "root/etc/rosy/update-freeze").write_text("")
    if home_freeze:
        (tmp_path / "home/.config/rosy").mkdir(parents=True)
        (tmp_path / "home/.config/rosy/update-freeze").write_text("")
    done = subprocess.run([sys.executable, "-I", str(GATE)], env=env, capture_output=True, text=True, timeout=30)
    return done.returncode, done.stdout


def test_no_tag_lets_the_updater_run(tmp_path):
    assert gate(tmp_path, git_script="exit 0\n") == (0, "rosy-update-gate: run: no freeze\n")


def test_the_site_tag_freezes(tmp_path):
    code, out = gate(tmp_path, git_script="echo 'abc123\trefs/tags/ops-update-freeze'\n")
    assert code == 1 and "frozen by tag" in out


@pytest.mark.parametrize("script", ["exit 128\n", "sleep 30\n"])
def test_an_uncheckable_tag_skips_the_run(tmp_path, script):
    code, out = gate(tmp_path, git_script=script)
    assert code == 1 and "failing closed" in out


def test_missing_git_and_unreachable_refs_skip_the_run(tmp_path):
    code, out = gate(tmp_path)
    assert code == 1 and "failing closed" in out


ADVERT = b"001e# service=git-upload-pack\n0000"


@pytest.mark.parametrize("body,expected", [
    (ADVERT + b"00f1" + b"a" * 40 + b" HEAD\x00multi_ack\n003f" + b"b" * 40 + b" refs/heads/main\n0000", 0),
    (ADVERT + b"0048" + b"c" * 40 + b" refs/tags/ops-update-freeze\x00caps\n0000", 1),
    (ADVERT + b"003f" + b"b" * 40 + b" refs/heads/main\n004b" + b"d" * 40 + b" refs/tags/ops-update-freeze^{}\n0000",
     1),
    (ADVERT + b"003f" + b"b" * 40 + b" refs/heads/main\n0048" + b"e" * 40 + b" refs/tags/ops-update-freeze-old\n0000",
     0),
    (ADVERT + b"003f" + b"b" * 40 + b" refs/heads/main\n", 1),  # cut off before the tags: not a "run"
    (ADVERT, 1),  # an empty list proves nothing
    (b"<html>rate limited</html>", 1),
])
def test_robots_without_git_read_the_ref_list_over_https(tmp_path, body, expected):
    code, out = served_gate(tmp_path, body)
    assert code == expected, out
    assert ("run: no freeze" in out) if expected == 0 else ("frozen by tag" in out or "failing closed" in out)


def test_the_twins_local_ref_list_lets_its_updater_run(tmp_path):
    script = (ROOT / "tools/device_twin/image/install_twin.sh").read_text()
    body = re.search(r"printf '(001e[^']*)' > /etc/rosy-twin-refs", script).group(1)
    assert served_gate(tmp_path, body.replace("\\n", "\n").encode()) == (0, "rosy-update-gate: run: no freeze\n")


def served_gate(tmp_path, body):
    class Refs(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Refs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        return gate(tmp_path, refs_url=f"http://127.0.0.1:{server.server_port}/info/refs")
    finally:
        server.shutdown()


def test_the_robot_updater_ships_and_checks_the_same_gate():
    native = ROOT / "deploy/robot/pinky_pro/native"
    assert ("ExecCondition=/bin/sh -c 'exec /usr/bin/python3 -I /opt/rosy/native-runtime/rosy-update-gate'"
            in (native / "rosy-auto-update.service").read_text().splitlines())
    installer = (native / "install-native-runtime.sh").read_text()
    assert 'cp "$SCRIPT_DIR/../../../hosts/common/host-state/rosy-update-gate" "$DESTINATION/rosy-update-gate"' in installer
    assert (native / "../../../hosts/common/host-state/rosy-update-gate").resolve() == GATE


def test_the_installed_robot_runtime_carries_the_gate(tmp_path):
    destination = tmp_path / "native-runtime"
    subprocess.run(["bash", str(ROOT / "deploy/robot/pinky_pro/native/install-native-runtime.sh"), str(destination)],
                   check=True, capture_output=True, timeout=60)
    assert (destination / "rosy-update-gate").read_bytes() == GATE.read_bytes()


@pytest.mark.parametrize("where", ["local", "home_freeze"])
def test_a_local_freeze_file_wins_without_asking_the_network(tmp_path, where):
    code, out = gate(tmp_path, git_script="exit 0\n", **{where: True})
    assert code == 1 and "frozen by" in out and "update-freeze" in out


def test_every_gated_unit_and_drop_in_points_at_the_installed_gate():
    dropin = (ROOT / "deploy/hosts/common/host-state/10-update-gate.conf").read_text()
    assert "ExecCondition=/bin/sh -c 'exec /usr/local/bin/rosy-update-gate'" in dropin
    for unit in ("deploy/robot/omx/rosy-omx-autoupdate.service", "deploy/model_pc/rosy-review-release-update.service",
                 "deploy/site/rosy-model-code-update.service",
                 "deploy/ai_pc/rosy-situation-autoupdate.service",
                 "deploy/robot/omx/rosy-omx-devices-autoupdate.service",
                 "deploy/model_pc/rosy-learning-center-update.service",
                 "deploy/site/rosy-site-tools-autoupdate.service"):
        assert "ExecCondition=/bin/sh -c 'exec /usr/local/bin/rosy-update-gate'" in (ROOT / unit).read_text(), unit
    common = (ROOT / "deploy/hosts/common/host-state/manifest").read_text()
    assert "safe file /usr/local/bin/rosy-update-gate common/rosy-update-gate 0755" in common
    for manifest, units in (("site", ("rosy-site-autoupdate", "rosy-docker-upgrade", "rosy-nightly-reboot")),
                            ("model_pc", ("rosy-nightly-reboot", "rosy-model-watch")),
                            ("ai_pc", ("rosy-nightly-reboot",))):
        text = (ROOT / f"deploy/{manifest}/host-state/manifest").read_text()
        for unit in units:
            assert (f"safe file /etc/systemd/system/{unit}.service.d/10-update-gate.conf "
                    "common/10-update-gate.conf") in text, (manifest, unit)
