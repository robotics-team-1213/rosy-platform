"""session_lock: one arm's session leaves the other arm free; a whole-cell holder still waits for both."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("fcntl")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import joint_tune as jt  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))  # the busy marker lands in ~/rosy-jobs


def test_two_arms_hold_their_own_sessions_at_once_and_one_arm_only_once():
    a, b = jt.session_lock("arm_a"), jt.session_lock("arm_b")
    with pytest.raises(SystemExit, match="session-arm_a.lock"):
        jt.session_lock("arm_a")
    a.close()
    jt.session_lock("arm_a").close()
    b.close()


def test_the_whole_cell_waits_for_every_arm_and_keeps_arms_out_while_it_holds():
    a = jt.session_lock("arm_a")
    with pytest.raises(SystemExit, match="session.lock"):
        jt.session_lock()
    a.close()
    cell = jt.session_lock()
    with pytest.raises(SystemExit, match="session.lock"):
        jt.session_lock("arm_b")
    cell.close()


def test_an_arm_id_must_be_a_plain_name():
    with pytest.raises(SystemExit, match="plain name"):
        jt.session_lock("../arm")


def test_tests_stay_off_the_host_until_the_last_session_ends_and_a_persons_marker_is_left_alone(tmp_path):
    busy = tmp_path / "rosy-jobs" / "busy"
    a, b = jt.session_lock("arm_a"), jt.session_lock("arm_b")
    assert busy.read_text().split()[1] == "omx-session"
    a.close()
    assert busy.exists(), "arm_b still runs"
    b.close()
    assert not busy.exists()
    busy.write_text("9999999999 person-wiring 1\n")
    jt.session_lock().close()
    assert busy.read_text() == "9999999999 person-wiring 1\n"
