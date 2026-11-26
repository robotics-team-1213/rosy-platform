"""What the cell did by itself is recorded in auto-events.jsonl and sent with the cell-quality post (2026-11-19)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts" / "foundation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_auto_fold as af  # noqa: E402
import cell_camera_telemetry_sync as sync  # noqa: E402
import omx_incident_auto as auto  # noqa: E402

HOME = [0.0, -58.0, 50.0, 50.0, -5.0, 46.6]
TORQUE0 = {str(i): 0 for i in range(11, 17)}
FLEET_FIELDS = ("kind", "arm", "robot_id", "incident_id", "batch_id", "result", "why", "candidate", "t", "person_needed",
                "source")  # pipeline_auto_events.FIELDS


@pytest.fixture(autouse=True)
def incidents(tmp_path, monkeypatch):
    import omx_incident
    import omx_incident_fleet

    monkeypatch.setattr(omx_incident_fleet, "INCIDENTS", tmp_path / "incidents")
    monkeypatch.setattr(omx_incident, "INCIDENTS", tmp_path / "incidents")
    return tmp_path / "incidents"


def events(folder):
    return [json.loads(line) for line in (folder / "auto-events.jsonl").read_text().splitlines()]


def test_note_event_appends_one_json_line_with_a_time(incidents):
    auto.note_event({"kind": "auto_clear", "arm": "arm_s", "incident_id": None, "result": True, "why": "rested"})
    auto.note_event({"kind": "auto_fold", "arm": "arm_s", "incident_id": "i-1", "result": "held"})
    rows = events(incidents)
    assert [r["kind"] for r in rows] == ["auto_clear", "auto_fold"] and all(isinstance(r["t"], float) for r in rows)


def test_note_event_never_raises(incidents, monkeypatch):
    import omx_incident_fleet

    blocker = incidents.parent / "blocker"
    blocker.write_text("x")
    monkeypatch.setattr(omx_incident_fleet, "INCIDENTS", blocker / "sub")  # a file is in the way
    auto.note_event({"kind": "auto_fold"})
    monkeypatch.setattr(omx_incident_fleet, "INCIDENTS", None)
    auto.note_event({"kind": "auto_fold", "bad": object()})


def test_auto_clear_verdict_becomes_an_event_with_only_fleet_fields(incidents):
    auto.note_auto_clear("arm_s", {"cleared": False, "why": "no assessor token"})
    (row,) = events(incidents)
    assert row["kind"] == "auto_clear" and row["result"] is False and row["incident_id"] is None
    assert set(row) <= set(FLEET_FIELDS)


def test_handle_notes_the_auto_clear_it_decided(incidents):
    import inspect

    import omx_incident

    source = inspect.getsource(omx_incident.handle)
    assert source.index('incident["auto_clear"] = auto_clear(') < source.index("note_auto_clear(arm")


def test_telemetry_body_carries_the_last_thirty_events(tmp_path, incidents):
    prep = tmp_path / "prep"
    (prep / "incidents").mkdir(parents=True)
    lines = [json.dumps({"kind": "auto_fold", "arm": "arm_s", "result": "held", "t": float(i)}) for i in range(40)]
    (prep / "incidents" / "auto-events.jsonl").write_text("\n".join([*lines, "not json", "[1]"]) + "\n")
    rows = sync._collect_auto_events(prep)
    assert len(rows) <= 30 and rows[-1]["t"] == 39.0 and all(isinstance(r, dict) for r in rows)
    assert sync._collect_auto_events(tmp_path / "absent") == []
    sent = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *a):
            return b"{}"

    def fake_urlopen(request, **kwargs):
        if request.full_url.endswith("/cell-quality"):
            sent.append(json.loads(request.data))
            return Reply()
        raise OSError("no local viewer")

    sync.sync_cell_telemetry("https://fleet.test", "token", prep_dir=prep, urlopen_fn=fake_urlopen)
    assert sent and sent[0]["auto_events"] == rows
    sync.sync_cell_telemetry("https://fleet.test", "token", prep_dir=tmp_path / "absent", urlopen_fn=fake_urlopen)
    assert sent[1]["auto_events"] == []


class Link:
    def __init__(self, ids):
        self.ids = ids

    def hold(self):
        return SimpleNamespace(incident_ids=self.ids, held=bool(self.ids), reason="x")


def _launch(tmp_path, incident, result=None, session=True, clear=None):
    conf, cwd = tmp_path / f"auto-fold-{incident}.conf.json", tmp_path / f"prep-{incident}"  # no file shared between cases
    cwd.mkdir(exist_ok=True)
    conf.write_text(json.dumps({"arm_s": {"wrapper": "w.sh", "config": "c.json", "library": "l.json", "site": "pinky",
                                          "roi": [0, 0, 10, 10], "cwd": str(cwd)}}))

    def run_fn(command, **kw):
        if result is not None:
            Path(command[command.index("--out") + 1]).write_text(json.dumps(result))
        if session:
            (cwd / "session.json").write_text(json.dumps({"torque_after": TORQUE0}))
        return SimpleNamespace(stdout="", stderr="boom")

    return af.launch("arm_s", conf, link=Link([incident]), run=run_fn, sleep=lambda s: None,
                     clear=clear or (lambda *a, **k: 0))


FOLDED = {"result": "folded", "candidate": "park", "state": HOME, "home": HOME, "corridor": {"clear": True}}


def test_every_launch_result_leaves_one_event_and_skipped_leaves_none(tmp_path, incidents):
    assert _launch(tmp_path, "i-ok", FOLDED)["result"] == "cleared"
    assert _launch(tmp_path, "i-held", {"result": "held", "reason": "ALL_PATHS_BLOCKED"})["result"] == "held"
    assert _launch(tmp_path, "i-fail")["result"] == "failed"
    assert _launch(tmp_path, "i-nosession", FOLDED, session=False)["result"] == "not_cleared"

    def refuse(*a, **k):
        raise SystemExit("refused")

    assert _launch(tmp_path, "i-refused", FOLDED, clear=refuse)["result"] == "not_cleared"
    assert _launch(tmp_path, "i-ok", FOLDED)["result"] == "skipped"  # already tried: no second event
    rows = {r["incident_id"]: r for r in events(incidents)}
    assert len(events(incidents)) == 5
    assert [rows[i]["result"] for i in ("i-ok", "i-held", "i-fail", "i-nosession", "i-refused")] == [
        "cleared", "held", "failed", "not_cleared", "not_cleared"]
    assert rows["i-held"]["why"] == "ALL_PATHS_BLOCKED" and rows["i-ok"]["candidate"] == "park"
    assert rows["i-fail"]["candidate"] is None and "boom" in rows["i-fail"]["why"]
    assert "SystemExit" in rows["i-refused"]["why"]
    assert all(r["kind"] == "auto_fold" and r["arm"] == "arm_s" and set(r) <= set(FLEET_FIELDS) for r in rows.values())


def test_launch_learns_the_tried_candidate_from_the_result_path(tmp_path, incidents):
    from cell_choices import Choices

    path = tmp_path / "choices.json"
    seed = Choices(path)
    for name in af.candidate_names():
        seed.offer(af.CHOICE, name, "D-1048")
    seed.save()
    _launch(tmp_path, "i-1", {**FOLDED, "choices_path": str(path)})
    _launch(tmp_path, "i-2", {"result": "held", "reason": "PARK_NOT_HOME", "candidate": "pan+5", "choices_path": str(path)})
    _launch(tmp_path, "i-3", {"result": "held", "reason": "ALL_PATHS_BLOCKED", "choices_path": str(path)})
    tried = {c["value"]: (c["tries"], c["ok"]) for c in Choices(path).data["values"][af.CHOICE] if c["tries"]}
    assert tried == {"park": (1, 1), "pan+5": (1, 0)}


def test_tail_read_and_stat_caches_handle_large_files_and_ssl_mtime(tmp_path, monkeypatch):
    import os
    import ssl
    from unittest.mock import patch

    prep = tmp_path / "prep"
    (prep / "chunk-io-a").mkdir(parents=True)
    status_file = prep / "chunk-io-a" / "chunk-status.jsonl"
    padding = json.dumps({"padding": "x" * 2048}) + "\n"
    first_row = json.dumps({"state": [1.0, -60.0, 50.0, 40.0, 0.0, 10.0], "health": {"temp_c": [31.0], "current_ma": [12.0]}})
    # >200 KB file so _read_tail_lines (64 KB initial span) actually seeks past leading lines
    status_file.write_text((padding * 110) + first_row + "\n", encoding="utf-8")

    tail = sync._read_tail_lines(status_file, 25)
    assert len(tail) == 25 and tail[-1] == first_row
    states = sync._collect_live_arm_states(prep)
    assert states["arm_a"]["joints_deg"] == [1.0, -60.0, 50.0, 40.0, 0.0, 10.0]

    # Stat cache hit avoids re-reading unchanged file; growth invalidates cache cleanly
    with patch.object(sync, "_read_tail_lines", side_effect=AssertionError("should use stat cache")):
        assert sync._collect_live_arm_states(prep)["arm_a"]["temp_c"] == 31.0

    new_row = json.dumps({"state": [2.0, -58.0, 48.0, 40.0, 0.0, 10.0], "health": {"temp_c": [33.5], "current_ma": [15.0]}})
    bad_row = json.dumps({"state": [None, 0, 0, 0, 0, 0], "health": "bad"})
    with status_file.open("a", encoding="utf-8") as fh:
        fh.write(new_row + "\n" + bad_row + "\n")
    st = status_file.stat()
    os.utime(status_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert sync._collect_live_arm_states(prep)["arm_a"]["joints_deg"][0] == 2.0
    assert sync._collect_live_arm_states(prep)["arm_a"]["temp_c"] == 33.5

    # SSL context cache keys on (ca_path, mtime_ns, verified, is_https) without relaxing verification
    monkeypatch.setattr(sync, "_SSL_CACHE", {})
    calls = []

    def fake_ctx(*args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        calls.append(kwargs.get("cafile"))
        return ctx

    monkeypatch.setattr(ssl, "create_default_context", fake_ctx)
    ca = tmp_path / "ca.pem"
    ca.write_text("ca-1", encoding="utf-8")
    c1 = sync._ssl_context(ca, True, True)
    c2 = sync._ssl_context(ca, True, True)
    assert c1 is c2 and calls == [str(ca)]
    st_ca = ca.stat()
    os.utime(ca, ns=(st_ca.st_atime_ns, st_ca.st_mtime_ns + 1_000_000))
    c3 = sync._ssl_context(ca, True, True)
    assert c3 is not c1 and len(calls) == 2
    uv = sync._ssl_context(None, False, True)
    vf = sync._ssl_context(None, True, True)
    assert uv is not vf and uv.verify_mode == ssl.CERT_NONE and len(calls) == 3
