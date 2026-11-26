"""A refusal before any motion command leaves a fault-free arm parked at home without human-hold; otherwise the hold stays."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))

import cell_policy_paced as paced  # noqa: E402
from cell_policy_pre_home import pre_settle_home  # noqa: E402
from cell_policy_timing import run_timed  # noqa: E402
from omx_adapter.chunk_library import NAMES, SCHEMA  # noqa: E402

HOME = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
OFF_HOME = [0.0, -58.0, 70.0, 50.0, -5.0, 49.0]
LIB = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6,
       "chunks": {"home": [HOME], "entry": [HOME, [1, -57, 51, 50, -5, 49]]}}
HOLD_REPLY = {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}


class Cell:
    def __init__(self, status):
        self.status, self.cmds = status, []

    def act(self, cmd):
        self.cmds.append(cmd)
        return dict(HOLD_REPLY) if cmd == "human-hold" else dict(self.status)


def _status(state=HOME, **kw):
    return {"command": "state", "ok": True, "settled": True, "holding": False, "state": list(state), **kw}


# (status, hold expected): gripper unconfirmed (holding) is the real 11-26 START_POSE_OFF_HOME refusal
CASES = [
    (_status(holding=True), False),                 # no command sent, at home, no fault: end at once
    (_status(OFF_HOME, holding=True), True),        # off home: torque stays
    (_status(holding=True, fault="overload"), True),  # fault: torque stays
]


@pytest.mark.parametrize("status,hold", CASES)
def test_pre_home_refusal(status, hold):
    cell, rows = Cell(status), []
    res, err = pre_settle_home(cell, LIB, status, {"chunk": 0}, rows.append, None, None)
    assert res is None and err["result"] in ("refused", "fault") and "START_POSE_OFF_HOME" in err["reason"]
    assert ("human-hold" in cell.cmds) is hold
    assert any("refused" in r for r in rows) and any(r.get("command") == "human-hold" for r in rows) is hold


def test_pre_home_missing_library_home_still_holds():
    status = _status(holding=True)
    cell = Cell(status)
    pre_settle_home(cell, {"chunks": {}}, status, {"chunk": 0}, lambda _r: None, None, None)
    assert "human-hold" in cell.cmds


@pytest.mark.parametrize("status,hold", CASES)
def test_timed_entry_start_refusal(status, hold, tmp_path):
    cell, rows = Cell(status), []
    shadow = SimpleNamespace(sim_rule=None, n_action_steps=1, chunk_size=1)
    res = run_timed(cell, shadow, LIB, tmp_path, infer=None, shape=None, max_step=1.0, n_action=1, max_obs_age_s=0.6,
                    max_chunks=1, dry_run=False, log=rows.append)
    assert res["result"] == "refused" and cell.cmds[0] == "state"
    assert ("human-hold" in cell.cmds) is hold


def _paced(cell, tmp_path, rows, **kw):
    return paced.run_paced_chunks(cell, SimpleNamespace(image_views={}), LIB, tmp_path, off=None, max_chunks=1, dry_run=False,
                                  log=rows.append, goal={}, sim_units=False, open_g=60.0, model_closed=46.0, closed=46.6,
                                  low=None, high=None, fastest=1.0, kin=None, jaw_spec=None, resolved_tcp=None,
                                  authorize=None, **kw)


@pytest.mark.parametrize("status,hold", CASES)
@pytest.mark.parametrize("pre_home", [True, False])
def test_paced_first_chunk_refusal(status, hold, pre_home, tmp_path):
    cell, rows = Cell(status), []
    res = _paced(cell, tmp_path, rows, pre_home=pre_home)
    assert res["result"] in ("refused", "fault") and res["parked"] is False
    assert ("human-hold" in cell.cmds) is hold


@pytest.mark.parametrize("patch", [{"ok": False, "error": "stale"}, {"contact": True}, {"hold": True}, {"human_hold_latched": True}])
def test_paced_unusable_state_reply_holds_even_at_home(patch, tmp_path):
    cell = Cell(_status(**patch))
    assert _paced(cell, tmp_path, [], pre_home=True)["result"] in ("refused", "fault")
    assert "human-hold" in cell.cmds


def test_idle_at_home_unit():
    from cell_policy_timing import idle_at_home

    assert idle_at_home(_status(), HOME) is True
    assert not any(idle_at_home(s, h) for s, h in [
        (_status(OFF_HOME), HOME), (_status(contact=True), HOME), (_status(ok=False), HOME), (_status(), None), (None, HOME),
        (_status(state=["x"] * 6), HOME), (_status(state=HOME[:3]), HOME), (_status(state=[float("nan")] * 6), HOME)])


def test_paced_state_read_error_holds(tmp_path):
    class Boom(Cell):
        def act(self, cmd):
            if cmd == "state":
                raise OSError("link down")
            return super().act(cmd)

    cell = Boom(_status())
    assert _paced(cell, tmp_path, [], pre_home=True)["result"] == "refused"
    assert "human-hold" in cell.cmds
