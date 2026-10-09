"""D-525: LineAdviceRequest bounds and AdviceStore ordering / TTL on the injected clock."""
import pytest
from pydantic import ValidationError

from core_common.protocol.line_advice import AdviceStore, LineAdviceRequest

WALL = 1_800_000_000.0
SIGNAL = {"signal_id": "S1", "approach": "north", "stop_m": 1.2, "lamp": "red", "left_s": 4.0,
          "green_in_s": None, "exact": True, "may_enter": False}


def _req(**fields):
    body = {"advice_id": "a", "leg_id": "L1", "seq": 5, "fleet_epoch": "e1", "pose_stamp": WALL,
            "ttl_s": 2.0, "signal": SIGNAL, **fields}
    return LineAdviceRequest.model_validate(body)


def _store(**fields):
    store = AdviceStore()
    assert store.accept(_req(**fields), now=10.0) == (True, None)
    return store


def test_same_leg_older_or_equal_is_dropped_while_live():
    store = _store()
    assert store.accept(_req(seq=5), now=10.5) == (False, "stale")             # same (stamp, seq)
    assert store.accept(_req(seq=9, pose_stamp=WALL - 1), now=10.5) == (False, "stale")
    assert store.current(10.5)["seq"] == 5


def test_same_stamp_newer_seq_and_newer_stamp_win():
    store = _store()
    assert store.accept(_req(seq=6), now=10.5)[0] is True
    assert store.accept(_req(seq=0, pose_stamp=WALL + 0.1), now=10.6)[0] is True  # seq reset, newer stamp


def test_ntp_step_back_older_stamp_is_accepted_after_expiry():
    store = _store()
    assert store.current(12.0) is None                       # ttl 2 s on the monotonic clock
    assert store.accept(_req(seq=1, pose_stamp=WALL - 30), now=12.0) == (True, None)
    assert store.current(12.0)["pose_stamp"] == WALL - 30


def test_leg_change_and_fleet_restart_replace_a_live_entry():
    store = _store()
    assert store.accept(_req(leg_id="L2", seq=0, pose_stamp=WALL - 5), now=10.1)[0] is True
    assert store.accept(_req(leg_id="L2", fleet_epoch="e2", seq=0, pose_stamp=WALL - 9),
                        now=10.2)[0] is True
    assert store.current(10.2)["fleet_epoch"] == "e2"


def test_signal_none_clears_the_shown_advice_but_keeps_ordering():
    store = _store()
    assert store.accept(_req(seq=6, signal=None), now=10.1)[0] is True
    assert store.current(10.1) is None
    assert store.accept(_req(seq=6), now=10.2) == (False, "stale")


def test_current_reports_expiry_and_echoes_fields():
    shown = _store().current(10.5)
    assert shown["expires_in_s"] == 1.5 and shown["signal"]["lamp"] == "red"
    assert shown["leg_id"] == "L1" and shown["map_version"] is None


@pytest.mark.parametrize("fields", [
    {"ttl_s": 0}, {"ttl_s": 2.5}, {"seq": -1}, {"pose_stamp": 0}, {"advice_id": ""},
    {"fleet_epoch": "x" * 65}, {"extra": 1}, {"signal": {**SIGNAL, "lamp": "blue"}},
    {"signal": {**SIGNAL, "stop_m": float("nan")}},
])
def test_invalid_requests_are_rejected(fields):
    with pytest.raises(ValidationError):
        _req(**fields)
