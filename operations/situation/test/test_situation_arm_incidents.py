"""D-971: the AI PC explains an open arm incident from its frames; explanation only, failures never block."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from concurrent.futures import Future

from rosy_situation.arm_incidents import RETRY_S, ArmIncidentExplainer
from rosy_situation.service import Situation
from rosy_situation.vlm import Vlm

JPEG = base64.b64encode(b"\xff\xd8fake\xff\xd9").decode()
DIGEST = "abcdef0123456789" * 4
RUNNING = lambda _url, _timeout: {"models": [{"name": "qwen3-vl:8b-instruct", "digest": DIGEST}]}  # noqa: E731
LIST = "/api/fleet/workcell-observations/arm-incidents/unexplained"
INCIDENT = {"incident_id": "a" * 32, "source_id": "omx_arm_b", "session_id": "s",
            "facts": {"latched": {"13": {"hw_error": 32, "bits": ["overload"]}}, "folded": True},
            "decision": {"hold": True, "reason": "latched ID 13 overload"}, "recovery": None,
            "frames": [{"role": "top", "sha256": "0" * 64, "jpeg_b64": JPEG},
                       {"role": "side", "sha256": "1" * 64, "jpeg_b64": JPEG}]}


class Fleet:
    def __init__(self, incidents=(), fail=None):
        self.incidents, self.fail, self.calls = list(incidents), fail, []

    def call(self, path, body=None):
        self.calls.append((path, body))
        if self.fail:
            raise self.fail
        return {"incidents": self.incidents} if path == LIST else {}

    def posts(self):
        return [(p, b) for p, b in self.calls if b is not None]


def vlm(answer, running=True):
    sent = []

    def post(url, body, timeout):
        sent.append((url, body, timeout))
        return {"message": {"content": answer if isinstance(answer, str) else json.dumps(answer)}}

    model = Vlm(post=post, get=RUNNING if running else (lambda _u, _t: {"models": []}))
    return model, sent


def test_open_incident_is_explained_from_both_frames_and_the_facts_with_a_no_motion_prompt():
    fleet, (model, sent) = Fleet([INCIDENT]), vlm({"seen": "A box between the jaws.", "suspected_cause": "Jaws held the box."})
    assert ArmIncidentExplainer(fleet, model, clock=lambda: 0.0).cycle() == 1
    [(path, body)] = fleet.posts()
    assert path == f"/api/fleet/workcell-observations/arms/omx_arm_b/incidents/{'a' * 32}/explanation"
    assert body["seen"] == "A box between the jaws." and body["model"].startswith("qwen3-vl:8b-instruct@")
    [(_, request, _)] = sent
    message = request["messages"][0]
    assert message["images"] == [JPEG, JPEG] and "top, side" in message["content"]
    assert "overload" in message["content"] and "Do not suggest motions" in message["content"]
    assert set(request["format"]["properties"]) == {"seen", "suspected_cause"}  # nothing that could be an action


def test_no_model_no_frames_or_a_bad_answer_leaves_the_incident_unexplained():
    for incident, answer, running in (
            (INCIDENT, {"seen": "x", "suspected_cause": "y"}, False),
            ({**INCIDENT, "frames": []}, {"seen": "x", "suspected_cause": "y"}, True),
            (INCIDENT, {"seen": "x", "suspected_cause": "y", "action": "move"}, True),
            (INCIDENT, {"seen": " ", "suspected_cause": "y"}, True)):
        fleet, (model, _) = Fleet([incident]), vlm(answer, running)
        assert ArmIncidentExplainer(fleet, model, clock=lambda: 0.0).cycle() == 0 and not fleet.posts()


def test_a_tried_incident_waits_before_the_next_try_and_a_fleet_without_observations_is_quiet():
    now = [0.0]
    fleet, (model, _) = Fleet([INCIDENT]), vlm("not json")
    explainer = ArmIncidentExplainer(fleet, model, clock=lambda: now[0])
    try:
        explainer.cycle()
    except ValueError:
        pass
    assert explainer.cycle() == 0  # inside the retry window the model is not asked again
    assert [c[0] for c in fleet.calls].count(LIST) == 2
    missing = Fleet(fail=urllib.error.HTTPError(LIST, 404, "no", {}, io.BytesIO(b"{}")))
    assert ArmIncidentExplainer(missing, model, clock=lambda: now[0]).cycle() == 0
    now[0] += RETRY_S + 1
    try:
        explainer.cycle()
    except ValueError:
        pass  # asked again after the window


class Immediate:
    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:  # the service logs a failed task
            future.set_exception(exc)
        return future


def test_the_service_polls_arm_incidents_only_when_configured_and_available_and_survives_failures(tmp_path):
    class Clock:
        now = 0.0
        __call__ = lambda self: self.now  # noqa: E731

    clock = Clock()
    mode = tmp_path / "mode"
    mode.write_text("available")
    fleet = Fleet([INCIDENT])
    model, _ = vlm({"seen": "A box.", "suspected_cause": "Box in the jaws."})
    off = Situation(fleet, tmp_path / "off", mode, clock=clock, wall=clock, executor=Immediate())
    off.step()
    assert LIST not in [p for p, _ in fleet.calls]  # not configured: never asked
    on = Situation(fleet, tmp_path / "on", mode, clock=clock, wall=clock, executor=Immediate(),
                   arm_incidents=ArmIncidentExplainer(fleet, model, clock=clock))
    on.step()
    on.step()  # the finished task is collected on the next step
    explained = [p for p, _ in fleet.posts() if p.endswith("/explanation")]
    assert len(explained) == 1
    mode.write_text("owner_busy")
    clock.now += 100
    on.step()
    assert [p for p, _ in fleet.calls].count(LIST) == 1  # owner busy: no polling
    mode.write_text("available")
    fleet.fail = OSError("Fleet down")
    clock.now += 100
    on.step()  # the failure is logged by the next collection and never raises
    clock.now += 100
    on.step()
