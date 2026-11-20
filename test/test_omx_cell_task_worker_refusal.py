"""The cell task worker never calls the real arm on a refused handoff, and unknown sites and tiers are refused."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_fleet_pipeline as cfp  # noqa: E402
import cell_task_worker as ctw  # noqa: E402

LOCKED = {"wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0}


@pytest.mark.parametrize(("replies", "hold_after"), [
    (["timeout", "clear"], None),
    (["timeout", None, "timeout"], 3),
    (["estop"], 1),
    (["human"], None),  # background poll: a person in a cell does not latch idle runners (unchanged)
    (["timeout", "estop"], 2),
])
def test_background_safety_listing_retries_only_missing_replies(tmp_path, monkeypatch, replies, hold_after):
    read, held = [], []

    def request(method, path, body):
        assert method == "GET"
        reply = replies[len(read)]
        read.append(reply)
        if reply == "timeout":
            raise TimeoutError("Fleet listing deadline")
        if reply is None:
            return None
        return {"tasks": [], "human_safety": {"active_estop": reply == "estop",
                                              "human_detected": {"cell_s": reply == "human"}}}

    monkeypatch.setattr(ctw, "_SAFETY_LISTING_RETRY_S", 0, raising=False)
    monkeypatch.setattr(ctw, "emergency_stop_arms", lambda _: held.append(len(read)))
    assert ctw.poll_and_execute_once(None, request_fn=request, live_act_fn=pytest.fail, prep_dir=tmp_path) == []
    assert held == ([] if hold_after is None else [hold_after])
    assert read == replies


def _run(tmp_path: Path, handoff: dict, tier: int = 1):
    hw_calls: list[dict] = []
    posted: list[dict] = []
    cell_id = handoff.get("cell_id", "cell_s")
    bound = {"handoff_lease_id": "lease-1", "task_id": "t-1", "tier": tier,
             "arm_id": "arm_s" if cell_id == "cell_s" else "arm_b", **handoff}

    def _req(method: str, path: str, body):
        if method == "GET":
            return {"tasks": [{"task_id": "t-1", "cell_id": cell_id, "tier": tier}],
                    "human_safety": {"active_estop": False, "human_detected": {}},
                    "cells": {cell_id: {"phase": "ARM_IN_BED_ZONE", "active_task_id": "t-1"}}}
        if path.endswith("/claim"):
            return {"claimed": True, "gate": {}, "handoff": bound}
        posted.append(body)
        return {"gate": {}, "task": {"status": body["phase"]}}

    def _hw(h):
        hw_calls.append(h)
        return {"arm": "arm_s", "events_count": 0, "stop_event": {}}

    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    ctw.poll_and_execute_once(pipe, request_fn=_req, live_act_fn=_hw, prep_dir=tmp_path)
    return hw_calls, posted[0]


@pytest.mark.parametrize(
    "handoff,reason",
    [
        ({"cell_id": "cell_s"}, "AMR_NOT_LOCKED_AT_HANDOFF"),  # interlock keys missing
        ({**LOCKED, "cell_id": "cell_s", "wheel_brake_locked": False}, "AMR_NOT_LOCKED_AT_HANDOFF"),
        ({**LOCKED, "cell_id": "cell_s", "v_cmd_mps": float("nan")}, "AMR_NOT_LOCKED_AT_HANDOFF"),
        ({**LOCKED, "cell_id": "cell_s", "dst_site": "bellt"}, "UNKNOWN_SITE"),
        ({**LOCKED, "cell_id": "cell_ab", "src_site": "pinky"}, "UNKNOWN_SITE"),
        ({**LOCKED, "cell_id": "cell_ab", "dst_site": "pallet-l2"}, "UNKNOWN_SITE"),  # wrong level for tier 1
    ],
)
def test_refused_handoff_never_calls_the_arm(tmp_path: Path, handoff: dict, reason: str) -> None:
    hw_calls, body = _run(tmp_path, handoff)
    assert hw_calls == []
    assert body["phase"] == "ABORTED" and body["reason"] == reason
    assert body["hardware_telemetry"] == {"error": reason}


@pytest.mark.parametrize("cell_id", ["cell_s", "cell_ab"])
def test_unknown_tier_is_refused_by_the_handoff_check(tmp_path: Path, cell_id: str) -> None:
    from cell_fleet_handoff import handoff_refusal

    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    assert handoff_refusal(pipe, {**LOCKED, "cell_id": cell_id}, 4) == "UNKNOWN_SITE"


def test_locked_handoff_without_measured_placement_is_aborted(tmp_path: Path) -> None:
    hw_calls, body = _run(tmp_path, {**LOCKED, "cell_id": "cell_s"})
    assert len(hw_calls) == 1  # the arm runs, but only measured placement releases
    assert body["phase"] == "ABORTED" and body["reason"] == "MEASURED_PLACEMENT_MISSING"
    assert body["receipt"]["simulated_success"] is False and body["receipt"]["physical_completion"] is False


def test_dispatch_path_cannot_complete_with_a_synthetic_stage(tmp_path: Path) -> None:
    hw_calls: list[dict] = []
    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    with pytest.raises(RuntimeError, match="SIMULATED_STAGE_CANNOT_COMPLETE_FLEET_TASK"):
        pipe.dispatch_and_execute_fleet_r_cell_task(fleet_r_url="https://fleet.invalid", dst_site="bellt",
                                                    live_act_fn=hw_calls.append, request_fn=lambda *a: {})
    assert hw_calls == []


def test_pipeline_refuses_unknown_site_and_tier(tmp_path: Path) -> None:
    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    with pytest.raises(ValueError, match="unknown site"):
        pipe.run_fleet_stage(arm_id="arm_s", src_site="pinky", dst_site="bellt")
    with pytest.raises(ValueError, match="tier"):
        pipe.prestage_cell_ab_handover(tier=4)


def test_worker_main_seals_legacy_live_jog_by_default(tmp_path: Path, monkeypatch) -> None:
    tok = tmp_path / "tok"
    tok.write_text("dummy-token", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(ctw, "make_default_request_fn", lambda *a, **k: (lambda m, p, b: calls.append(f"{m}:{p}") or {}))
    monkeypatch.setattr(ctw, "sync_cell_telemetry", lambda *a, **k: calls.append("sync") or {})
    monkeypatch.setattr(ctw, "execute_live_hardware_arm", lambda *a, **k: calls.append("live_jog") or {})

    ctw.main(["--once", "--token-file", str(tok), "--work-dir", str(tmp_path / "w"), "--prep-dir", str(tmp_path / "p")])
    assert "sync" in calls
    assert "live_jog" not in calls
    assert not any(c.startswith("POST:/api/fleet/pipeline/cell-tasks/claim") for c in calls)


def test_worker_skips_held_arm_before_claim_and_classifies_401(tmp_path: Path) -> None:
    from urllib.error import HTTPError

    tok = tmp_path / "tok"
    tok.write_text("short-token-value", encoding="utf-8")
    calls: list[str] = []

    def _req(method: str, path: str, body):
        calls.append(f"{method}:{path}")
        return {"tasks": [{"task_id": "t-held", "cell_id": "cell_ab", "arm_id": "arm_a", "tier": 1}],
                "human_safety": {"active_estop": False, "human_detected": {}},
                "cells": {"cell_ab": {"phase": "ARM_IN_BED_ZONE", "active_task_id": "t-held"}}}

    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    ctw.poll_and_execute_once(pipe, request_fn=_req, live_act_fn=lambda h: {"ok": True}, prep_dir=tmp_path,
                              hold_check_fn=lambda arm: {"held": arm == "arm_a", "reason": "open hold"})
    assert calls == ["GET:/api/fleet/pipeline/cell-tasks?status=QUEUED"]

    err = HTTPError("https://192.168.1.93:8443/api/fleet/pipeline/cell-tasks", 401, "Unauthorized", {}, io.BytesIO(b""))
    diag = ctw.classify_poll_error(err, tok)
    assert diag["event"] == "poll_auth_error" and diag["status"] == 401 and diag["token_chars"] == len("short-token-value")
    assert "short-token-value" not in json.dumps(diag)


# --- D-1057: a result Fleet did not get is resent as it was; the arm never runs again -------------------------------------
from urllib.error import HTTPError, URLError  # noqa: E402


def _good_result(handoff):
    import time as _t

    zone = {"verified": True, "basis": "top_camera_only_target_zone",
            "target": {"site": "belt", "area": "belt", "roi": [1, 2, 3, 4], "tier": 1}}
    return {"arm": "arm_s", "measured_at": _t.time(), "stop_event": {"command": "stop", "ok": True, "folded": True},
            "stage_result": {"handoff_lease_id": handoff["handoff_lease_id"], "directive_id": handoff["task_id"], "arm_id": "arm_s",
                             "task_verified": True, "verification": zone, "place": {"area": "belt", "tier": 1}}}


class Fleet:
    """A scripted Fleet: claim, listings, and a send hook that can fail."""

    def __init__(self, lease="lease-1", fail=None, running_lease=None):
        self.lease, self.fail, self.running_lease = lease, fail, running_lease or lease
        self.posts, self.status, self.claimed = [], "RUNNING", False

    def __call__(self, method, path, body):
        if method == "GET" and "status=QUEUED" in path:
            queued = [] if self.claimed else [{"task_id": "t-1", "cell_id": "cell_s", "tier": 1}]  # claimed: RUNNING in Fleet
            return {"tasks": queued, "human_safety": {"active_estop": False, "human_detected": {}},
                    "cells": {"cell_s": {"phase": "ARM_IN_BED_ZONE", "active_task_id": "t-1"}}}
        if method == "GET" and "status=RUNNING" in path:
            return {"tasks": [{"task_id": "t-1", "status": "RUNNING", "handoff_lease_id": self.running_lease}] if self.status == "RUNNING" else []}
        if path.endswith("/claim"):
            self.claimed = True
            return {"claimed": True, "gate": {}, "handoff": {**LOCKED, "task_id": "t-1", "cell_id": "cell_s", "tier": 1, "arm_id": "arm_s",
                                                             "handoff_lease_id": self.lease, "src_site": "pinky", "dst_site": "belt"}}
        if self.fail is not None and (exc := self.fail(path)) is not None:
            raise exc
        self.posts.append((path.rsplit("/", 1)[1], body))
        return {"gate": {}, "task": {"status": "COMPLETED"}}


def _run_worker(tmp_path, fleet, calls):
    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")

    def act(handoff):
        calls.append(handoff)
        return _good_result(handoff)

    try:
        return ctw.poll_and_execute_once(pipe, request_fn=fleet, live_act_fn=act, prep_dir=tmp_path)
    except Exception as exc:  # the first run reports the failed send as before
        return exc


def _forbidden(path):
    return HTTPError("https://f/x", 403, "no", {}, None) if path.endswith("owner-evidence") else None


def test_a_403_on_owner_evidence_keeps_the_result_and_the_next_poll_resends_it_without_the_arm(tmp_path):
    calls = []
    registered = [False]
    fleet = Fleet(fail=lambda p: None if registered[0] else _forbidden(p))
    first = _run_worker(tmp_path, fleet, calls)
    assert isinstance(first, HTTPError) and len(calls) == 1 and fleet.posts == []
    kept = json.loads((tmp_path / "pipe" / "pending-results.json").read_text(encoding="utf-8"))["t-1"]
    assert kept["lease"] == "lease-1" and kept["complete"]["phase"] == "RELEASED"
    assert _run_worker(tmp_path, fleet, calls) == [] and fleet.posts == []  # still 403: kept, nothing new started
    registered[0] = True  # the principal got registered
    fleet.posts.clear()
    _run_worker(tmp_path, fleet, calls)
    assert [p for p, _ in fleet.posts] == ["owner-evidence", "complete"] and len(calls) == 1  # no second arm run
    assert fleet.posts[0][1] == kept["owner_evidence"] and fleet.posts[1][1] == kept["complete"]  # the very same bodies
    assert not (tmp_path / "pipe" / "pending-results.json").read_text(encoding="utf-8").strip("{} \n")  # entry removed


def test_a_network_break_on_complete_is_resent_on_a_later_poll(tmp_path):
    calls, broken = [], [True]
    fleet = Fleet(fail=lambda p: URLError("down") if (broken[0] and p.endswith("/complete")) else None)
    assert isinstance(_run_worker(tmp_path, fleet, calls), URLError) and len(calls) == 1
    assert [p for p, _ in fleet.posts] == ["owner-evidence"]  # the evidence arrived, the completion did not
    broken[0] = False
    fleet.posts.clear()
    _run_worker(tmp_path, fleet, calls)
    assert [p for p, _ in fleet.posts] == ["owner-evidence", "complete"] and len(calls) == 1


def test_a_changed_lease_or_a_finished_task_is_not_resent(tmp_path):
    calls = []
    fleet = Fleet(fail=lambda p: _forbidden(p))
    _run_worker(tmp_path, fleet, calls)
    assert (tmp_path / "pipe" / "pending-results.json").exists()
    fleet.fail, fleet.posts = None, []
    fleet.running_lease = "lease-2"  # Fleet shows the task RUNNING under another lease: that handoff is over
    _run_worker(tmp_path, fleet, calls)
    assert fleet.posts == [] and json.loads((tmp_path / "pipe" / "pending-results.json").read_text(encoding="utf-8")) == {}
    fleet.fail = lambda p: _forbidden(p)
    fleet.running_lease = "lease-2"
    fleet.lease = "lease-2"
    _run_worker(tmp_path, fleet, calls)  # a new run under the new lease leaves a new pending entry
    fleet.fail, fleet.posts, fleet.status = None, [], "COMPLETED"  # ... but Fleet no longer shows it RUNNING
    _run_worker(tmp_path, fleet, calls)
    assert fleet.posts == [] and json.loads((tmp_path / "pipe" / "pending-results.json").read_text(encoding="utf-8")) == {}


def test_a_body_fleet_refuses_on_its_merits_is_dropped_not_retried(tmp_path):
    from cell_result_outbox import Outbox, resend_pending

    outbox = Outbox(tmp_path / "o.json")
    outbox.put("t-1", {"lease": "lease-1", "owner_evidence": {"x": 1}, "complete": {"phase": "RELEASED"}})
    refuse = HTTPError("https://f/x", 409, "OWNER_EVIDENCE_ALREADY_RECORDED", {}, None)

    def fleet(method, path, body):
        if method == "GET":
            return {"tasks": [{"task_id": "t-1", "handoff_lease_id": "lease-1"}]}
        raise refuse

    assert resend_pending(outbox, fleet)[0]["action"] == "dropped" and outbox.items() == {}
    assert Outbox(None).items() == {}  # no work directory: nothing is kept and nothing fails


def test_a_run_held_for_review_aborts_with_review_required_and_no_owner_evidence(tmp_path):
    calls = []
    fleet = Fleet()
    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    ctw.poll_and_execute_once(pipe, request_fn=fleet, prep_dir=tmp_path,
                              live_act_fn=lambda h: calls.append(h) or {"arm": "arm_s", "review_required": True, "error": "held: not_reviewed",
                                                                         "stop_event": {"ok": False, "folded": False}})
    assert [p for p, _ in fleet.posts] == ["complete"]
    body = fleet.posts[0][1]
    assert body["phase"] == "ABORTED" and body["reason"] == "REVIEW_REQUIRED" and len(calls) == 1


class _Remeasure:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, task_id, entry):
        import time as _t

        self.calls.append(task_id)
        if self.fail:
            raise RuntimeError(self.fail)
        owner = {**entry["owner_evidence"], "measured_at": _t.time(), "fresh": True}
        return owner, {**entry["complete"], "fresh": True}


def _stale_entry(age_s):
    import time as _t

    return {"lease": "lease-1", "owner_evidence": {"handoff_lease_id": "lease-1", "measured_at": _t.time() - age_s},
            "complete": {"phase": "RELEASED"}}


def _running(lease="lease-1"):
    def fleet(method, path, body, posts=[]):  # noqa: B006
        return {"tasks": [{"task_id": "t-1", "handoff_lease_id": lease}]} if method == "GET" else {"ok": True}

    return fleet


def test_a_stale_kept_result_is_measured_again_before_it_is_resent(tmp_path):
    from cell_result_outbox import Outbox, resend_pending

    outbox, sent = Outbox(tmp_path / "o.json"), []
    outbox.put("t-1", _stale_entry(70))
    fresh = _Remeasure()
    fleet = _running()
    resend_pending(outbox, lambda m, p, b: (sent.append((p.rsplit("/", 1)[1], b)) or fleet(m, p, b)) if m == "POST" else fleet(m, p, b), fresh)
    assert fresh.calls == ["t-1"] and [p for p, _ in sent] == ["owner-evidence", "complete"]
    assert sent[0][1]["fresh"] is True and sent[1][1]["fresh"] is True and outbox.items() == {}


def test_a_fresh_kept_result_is_resent_as_it_is(tmp_path):
    from cell_result_outbox import Outbox, resend_pending

    outbox, sent = Outbox(tmp_path / "o.json"), []
    outbox.put("t-1", _stale_entry(20))
    fresh = _Remeasure()
    resend_pending(outbox, lambda m, p, b: (sent.append(b) or {"ok": True}) if m == "POST" else _running()(m, p, b), fresh)
    assert fresh.calls == [] and "fresh" not in sent[0]


def test_a_failed_re_measurement_keeps_the_task_with_the_reason_and_sends_nothing(tmp_path):
    from cell_result_outbox import Outbox, resend_pending

    outbox, sent = Outbox(tmp_path / "o.json"), []
    outbox.put("t-1", _stale_entry(70))
    done = resend_pending(outbox, lambda m, p, b: (sent.append(b) or {"ok": True}) if m == "POST" else _running()(m, p, b),
                          _Remeasure(fail="the placement is not verified now"))
    kept = outbox.items()["t-1"]
    assert sent == [] and done[0]["action"] == "kept" and "not verified now" in kept["last_refusal"]["reason"]


def test_a_stale_result_under_another_lease_is_not_measured_or_sent(tmp_path):
    from cell_result_outbox import Outbox, resend_pending

    outbox, sent = Outbox(tmp_path / "o.json"), []
    outbox.put("t-1", _stale_entry(70))
    fresh = _Remeasure()
    resend_pending(outbox, lambda m, p, b: (sent.append(b) or {"ok": True}) if m == "POST" else _running("lease-2")(m, p, b), fresh)
    assert fresh.calls == [] and sent == [] and outbox.items() == {}


def test_the_real_remeasurement_needs_its_stored_context_and_checks_placement_and_fold(tmp_path, monkeypatch):
    import cv2
    import numpy as np

    import cell_remeasure as cr
    import cell_zone_verification as czv

    entry = {"complete": {"stage_result": {"verification": {"placement": {"verified": True, "inside": True}}},
                          "hardware_telemetry": {"measured_at": 1.0, "stop_event": {"ok": True, "folded": True, "readback": {"folded": True}}},
                          "receipt": {"handoff_lease_id": "lease-1"}}}
    with pytest.raises(cr.RemeasureFailed, match="no stored context"):
        cr.remeasure("t-1", entry, tmp_path)
    work = tmp_path / "work"
    (work / "zone-before").mkdir(parents=True)
    cv2.imwrite(str(work / "zone-before" / "t-1-top.jpg"), np.zeros((8, 8, 3), np.uint8))
    (tmp_path / "cfg.json").write_text(json.dumps({"io": str(tmp_path), "cameras": {}, "sites": {}}), encoding="utf-8")
    (tmp_path / "remeasure-t-1.json").write_text(json.dumps({
        "cfg": str(tmp_path / "cfg.json"), "prep_dir": str(tmp_path), "arm_id": "arm_s", "dst": "belt", "src_site": "pinky",
        "src_roi": [0, 0, 1, 1], "work_dir": str(work), "before_frames": {"top": "t-1-top.jpg"},
        "handoff": {"task_id": "t-1", "cell_id": "cell_s", "tier": 1, "handoff_lease_id": "lease-1", "arm_id": "arm_s"}}), encoding="utf-8")
    good = {"verified": True, "basis": "top_camera_only_target_zone", "target": {"site": "belt", "area": "belt", "roi": [1, 2, 3, 4], "tier": 1}}
    monkeypatch.setattr(czv, "measure", lambda *a, **k: good)
    monkeypatch.setattr("cell_pipeline.FifoCell", lambda *a, **k: object())
    monkeypatch.setattr("cell_task_exec.measured_fold", lambda *a, **k: {"folded": True, "state": None, "fresh": True})
    owner, complete = cr.remeasure("t-1", entry, tmp_path)
    assert owner["measured_at"] > 1.0 and complete["receipt"]["goal_evidence_digest"].startswith("sha256:")
    assert owner["stage_result"]["verification"]["basis"] == "top_camera_only_target_zone"
    monkeypatch.setattr(czv, "measure", lambda *a, **k: {**good, "verified": False, "basis": "unverified: x"})
    with pytest.raises(cr.RemeasureFailed, match="not verified now"):
        cr.remeasure("t-1", entry, tmp_path)
    monkeypatch.setattr(czv, "measure", lambda *a, **k: good)
    monkeypatch.setattr("cell_task_exec.measured_fold", lambda *a, **k: {"folded": False, "state": None, "fresh": True})
    with pytest.raises(cr.RemeasureFailed, match="not folded now"):
        cr.remeasure("t-1", entry, tmp_path)


# --- D-1057 round 7: the original evidence is used while Fleet holds it; a lapsed bed confirmation waits for a person ----------
def _refused(code, status=422):
    import io

    return HTTPError("https://f/x", status, "refused", {}, io.BytesIO(json.dumps({"detail": {"code": code}}).encode()))


def _posting(fleet, sent, fail=None):
    def request(method, path, body):
        if method != "POST":
            return fleet(method, path, body)
        sent.append(path.rsplit("/", 1)[1])
        error = fail(sent[-1]) if fail else None
        if error is not None:
            raise error
        return {"ok": True}
    return request


def test_original_evidence_still_held_by_fleet_is_not_measured_again_and_a_409_on_it_means_recorded(tmp_path):
    from cell_result_outbox import Outbox, resend_pending

    outbox, sent = Outbox(tmp_path / "o.json"), []
    outbox.put("t-1", _stale_entry(55))  # Fleet holds the first evidence for 60 s
    fresh = _Remeasure()
    fail = lambda part: _refused("OWNER_EVIDENCE_ALREADY_RECORDED", 409) if part == "owner-evidence" else None  # noqa: E731
    done = resend_pending(outbox, _posting(_running(), sent, fail), fresh)
    assert fresh.calls == [] and sent == ["owner-evidence", "complete"]
    assert done[0]["action"] == "resent" and outbox.items() == {}


def test_an_owner_evidence_409_with_another_code_is_still_dropped(tmp_path):
    from cell_result_outbox import Outbox, resend_pending

    outbox, sent = Outbox(tmp_path / "o.json"), []
    outbox.put("t-1", _stale_entry(20))
    done = resend_pending(outbox, _posting(_running(), sent, lambda part: _refused("SOMETHING_ELSE", 409)), _Remeasure())
    assert sent == ["owner-evidence"] and done[0]["action"] == "dropped" and outbox.items() == {}


def test_only_the_expired_evidence_is_measured_again(tmp_path):
    from cell_result_outbox import STALE_S, Outbox, resend_pending

    assert STALE_S > 60  # Fleet's own limit plus a margin for the two clocks
    outbox, sent, fresh = Outbox(tmp_path / "o.json"), [], _Remeasure()
    outbox.put("t-1", _stale_entry(STALE_S + 1))
    resend_pending(outbox, _posting(_running(), sent), fresh)
    assert fresh.calls == ["t-1"] and outbox.items() == {}


def test_a_lapsed_bed_confirmation_keeps_the_result_with_the_reason_until_a_person_confirms_again(tmp_path):
    from cell_result_outbox import Outbox, resend_pending

    outbox, sent, bed = Outbox(tmp_path / "o.json"), [], [False]
    outbox.put("t-1", _stale_entry(20))
    fail = lambda part: None if part == "owner-evidence" or bed[0] else _refused("BED_CONFIRMATION_INVALID")  # noqa: E731
    done = resend_pending(outbox, _posting(_running(), sent, fail), _Remeasure())
    kept = outbox.items()["t-1"]
    assert done[0]["action"] == "kept" and kept["last_refusal"]["reason"] == "BED_CONFIRMATION_INVALID"
    assert resend_pending(outbox, _posting(_running(), sent, fail), _Remeasure())[0]["action"] == "kept"  # still waiting
    bed[0] = True  # a named operator confirmed the bed again under the same lease
    assert resend_pending(outbox, _posting(_running(), sent, fail), _Remeasure())[0]["action"] == "resent"
    assert outbox.items() == {}


def test_other_422_refusals_are_dropped_as_before_except_evidence_that_expired_in_between(tmp_path):
    from cell_result_outbox import Outbox, resend_pending

    for code, action, left in (("OMX_OWNER_EVIDENCE_MISMATCH", "dropped", 0), ("AMR_BRAKE_BED_VELOCITY_UNMEASURED", "dropped", 0),
                               ("OMX_OWNER_EVIDENCE_UNAVAILABLE", "kept", 1)):
        outbox = Outbox(tmp_path / f"{code}.json")
        outbox.put("t-1", _stale_entry(20))
        fail = lambda part, code=code: _refused(code) if part == "complete" else None  # noqa: E731
        assert resend_pending(outbox, _posting(_running(), [], fail), _Remeasure())[0]["action"] == action
        assert len(outbox.items()) == left
