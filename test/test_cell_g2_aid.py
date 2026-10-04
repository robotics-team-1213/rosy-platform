"""One request only; a late service acknowledgement cannot become a replay."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import g2_aid


def fixture(monkeypatch, *, latency=.11, data=True, echo=True, overrun=None):
    class Request:
        def __init__(self):
            self.entity = NS()
            self.plugins = NS(add=lambda: NS())
    for name, value in [("boolean", NS(Boolean=object)), ("entity", NS(Entity=NS(MODEL=2))),
                        ("entity_plugin_v", NS(EntityPlugin_V=Request)), ("empty", NS(Empty=object))]:
        monkeypatch.setitem(sys.modules, "gz.msgs10."+name+"_pb2", value)
    clock, calls = [0.], []
    monkeypatch.setattr(g2_aid.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(g2_aid.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    aid = object.__new__(g2_aid.OneShotSimAid)
    aid._robot_id, aid._states, aid._publishers = 7, {}, {}
    def watch(model):
        aid._states.setdefault(model, [])
        aid._publishers[model] = NS(publish=lambda msg: calls.append("detach"))
    aid.watch = watch
    def request(service, msg, request_type, response_type, timeout):
        calls.append(timeout)
        clock[0] += overrun if overrun is not None else min(latency, timeout/1000)
        if echo:
            aid._states["box"].append("attached")
        return latency <= timeout/1000, NS(data=data if latency <= timeout/1000 else False)
    aid._node = NS(request=request)
    return aid, calls, clock


def test_110ms_acknowledgement_fits_the_unchanged_200ms_budget(monkeypatch):
    aid, calls, _ = fixture(monkeypatch)
    receipt = aid.attach("box")
    assert receipt["service_ok"] is True and receipt["confirmed"] is True
    assert receipt["elapsed_s"] <= .2 and len(calls) == 1


@pytest.mark.parametrize("kwargs", [{"latency": .18}, {"data": False}, {"echo": False}])
def test_missing_ack_negative_reply_or_missing_echo_remains_uncertain(monkeypatch, kwargs):
    aid, calls, _ = fixture(monkeypatch, **kwargs)
    receipt = aid.attach("box")
    assert not (receipt["service_ok"] and receipt["confirmed"])
    assert receipt["re_commanded_after"] is None and len(calls) == 1


def test_over_budget_transport_cannot_confirm_even_with_echo(monkeypatch):
    aid, calls, _ = fixture(monkeypatch, overrun=.201)
    receipt = aid.attach("box")
    assert receipt["confirmed"] is False
    assert len(calls) == 1


def test_raw_acknowledgement_fields_distinguish_timeout_and_negative_reply(monkeypatch):
    aid, _, _ = fixture(monkeypatch, data=False)
    receipt = aid.attach("box")
    assert receipt["transport_ok"] is True and receipt["response_data"] is False
    assert receipt["request_timeout_ms"] == 150


def test_late_detach_echo_cannot_confirm_or_publish_again(monkeypatch):
    aid, calls, clock = fixture(monkeypatch)
    aid.watch("box")
    aid.watch = lambda model: None
    def publish(msg):
        calls.append("detach")
        clock[0] += .201
        aid._states["box"].append("detached")
    aid._publishers["box"].publish = publish
    receipt = aid.detach("box")
    assert receipt["confirmed"] is False and calls == ["detach"]


def test_detach_wait_subtracts_publish_time_from_total_budget(monkeypatch):
    aid, calls, clock = fixture(monkeypatch)
    aid.watch("box")
    aid.watch = lambda model: None
    def publish(msg):
        calls.append("detach")
        clock[0] += .12
    aid._publishers["box"].publish = publish
    receipt = aid.detach("box")
    assert receipt["confirmed"] is False and calls == ["detach"]
    assert receipt["elapsed_s"] <= .200001
