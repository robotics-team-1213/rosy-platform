"""Fleet berth park through CORE's pink-line docking: Fleet asks and reads, never drives."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fleet.server.ledger.berth_core_dock import execute_core_line_dock
from fleet.server.ledger.berth_parking_helpers import BAY_DOCK_SPECS


class Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.content, self.text = code, body, b"x", str(body)

    def json(self):
        return self._body


class Http:
    def __init__(self, statuses, start_code=200):
        self.calls, self.statuses, self.start_code = [], list(statuses), start_code

    async def request(self, method, path, json=None, headers=None):
        self.calls.append((method, path, json))
        if path.endswith("/dock"):
            return Resp(self.start_code, {"state": "DOCKING", "phase": "backoff"} if self.start_code < 400
                        else {"code": "CAPABILITY_NOT_SUPPORTED"})
        if path.endswith("/cancel"):
            return Resp(200, {"state": "UNDOCKED"})
        return Resp(200, self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0])


def console(http):
    return SimpleNamespace(_clients={"rosy_45": SimpleNamespace(_http=http, _headers=lambda: {})})


def run(http, **kw):
    t = [0.0]

    async def sleep(s):
        t[0] += s
    return asyncio.run(execute_core_line_dock(console(http), "rosy_45", BAY_DOCK_SPECS["C3"],
                                              clock=lambda: t[0], sleep=sleep, **kw))


def test_it_asks_core_for_the_bay_dock_and_reports_core_s_docked():
    http = Http([{"state": "DOCKING", "phase": "turning"}, {"state": "DOCKING", "phase": "aligning"},
                 {"state": "DOCKED", "phase": None}])
    out = run(http)
    assert out["succeeded"] is True and out["stop_reason"] == "docked"
    assert http.calls[0][:2] == ("POST", "/api/v1/docking/dock") and http.calls[0][2]["dock"] == "bay_c3"
    assert out["phases_executed"] == ["backoff", "turning", "aligning"]
    assert not any("/teleop" in c[1] or "/teach" in c[1] for c in http.calls)   # Fleet never drives


def test_a_core_failure_or_refusal_is_not_a_berth_park():
    out = run(Http([{"state": "DOCK_FAILED", "error": "bay zone: nose toward the bay"}]))
    assert out["succeeded"] is False and out["core"]["error"].startswith("bay zone")
    refused = run(Http([], start_code=501))
    assert refused["executed"] is False and refused["stop_reason"] == "core_refused_501"


def test_fleet_s_deadline_cancels_core_instead_of_leaving_it_unwatched():
    http = Http([{"state": "DOCKING", "phase": "aligning"}])
    out = run(http, timeout_s=5.0)
    assert out["succeeded"] is False and out["stop_reason"] == "timeout"
    assert ("POST", "/api/v1/docking/cancel", {}) in http.calls


def test_a_failed_cancel_is_reported_not_hidden():
    class NoCancel(Http):
        async def request(self, method, path, json=None, headers=None):
            if path.endswith("/cancel"):
                raise OSError("link down")
            return await super().request(method, path, json, headers)
    out = run(NoCancel([{"state": "DOCKING", "phase": "aligning"}]), timeout_s=3.0)
    assert out["stop_reason"] == "timeout_cancel_failed" and out["succeeded"] is False


def test_unreadable_status_ends_with_a_cancel_instead_of_spinning():
    class Broken(Http):
        async def request(self, method, path, json=None, headers=None):
            if path.endswith("/status"):
                self.calls.append((method, path, json))
                return Resp(503, {})
            return await super().request(method, path, json, headers)
    http = Broken([])
    out = run(http, max_bad_reads=3)
    assert out["stop_reason"] == "status_unreadable"
    assert ("POST", "/api/v1/docking/cancel", {}) in http.calls

