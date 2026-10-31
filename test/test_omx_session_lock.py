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
