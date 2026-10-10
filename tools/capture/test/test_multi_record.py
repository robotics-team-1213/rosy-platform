"""Multi-camera capture: source isolation, clocks, private credentials and replay."""
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def module():
    assert (Path(__file__).resolve().parents[1] / "multi_record.py").exists(), "multi-source recorder missing"
    return importlib.import_module("multi_record")


def test_any_number_of_sources_and_unsafe_or_duplicate_ids(tmp_path):
    m = module()
    sources = [{"id": f"robot_{i}", "kind": "robot", "url": "https://robot.local:8080",
                "token_file": "operator.token", "ca_file": "ca.pem"} for i in range(3)]
    sources += [{"id": f"camera_{i}", "kind": "site", "source_id": f"ceiling_{i}"} for i in range(2)]
    config = {"site": {"url": "https://site.local", "ca_file": "site.pem", "token_file": "site.token"},
              "sources": sources}
    assert len(m.validate_config(config)["sources"]) == 5
    for bad in ("../escape", "robot_0"):
        with pytest.raises(ValueError):
            m.validate_config({**config, "sources": sources + [{**sources[0], "id": bad}]})
    with pytest.raises(ValueError):
        m.validate_config({**config, "sources": [{**sources[0], "url": "http://robot.local"}]})


def test_session_keeps_other_sources_and_never_exports_credentials(tmp_path):
    m = module()
    sources = [{"id": "front_a", "kind": "robot", "url": "https://private.local",
                "token_file": "SECRET", "ca_file": "ca.pem"}, {"id": "ceiling", "kind": "site"}]
    session = m.Session(tmp_path / "session", sources, clock=lambda: 1000.)
    session.frame("front_a", b"jpeg", {"seq": 1, "captured_at": 42., "received_at": 1000.,
                                       "timeline_at": 1000., "clock": "receipt", "rotation_deg": 0})
    session.error("ceiling", "unavailable")
    session.positions({"ts": 1000., "robots": [{"robot_id": "front_a", "status": "NO_POSE"}]})
    manifest = session.view(now=1000.5)
    assert manifest["sources"][0]["status"] == "live"
    assert manifest["sources"][1]["status"] == "unavailable"
    assert session.view(now=1004.)["sources"][0]["status"] == "stale"
    assert session.view(now=1004.)["positions"] is None
    session.finish()
    text = (session.out / "session.json").read_text()
    assert "SECRET" not in text and "private.local" not in text
    db = sqlite3.connect(session.out / "capture.sqlite3")
    assert db.execute("select count(*) from frames").fetchone()[0] == 1
    assert db.execute("select count(*) from positions").fetchone()[0] == 1
    assert db.execute("select count(*) from events where kind='source_error'").fetchone()[0] == 1
    with pytest.raises(FileExistsError):
        m.Session(session.out, sources)


def test_robot_frame_uses_sequence_and_does_not_invent_utc_or_send_commands():
    m = module()
    class Core:
        calls = []
        def call(self, method, path, **kwargs):
            self.calls.append((method, path))
            if path == "/vision/front/status":
                return 200, {"available": True, "stale": False, "sequence": 8,
                             "captured_at": 42., "age_ms": 10}
            assert path == "/vision/front/frame?sequence=8&overlay=false"
            return 200, b"\xff\xd8jpeg\xff\xd9"
    core = Core()
    jpeg, row = m.robot_frame(core, now=1000.)
    assert jpeg.startswith(b"\xff\xd8") and row["captured_at"] == 42.
    assert row["clock"] == "receipt" and row["timeline_at"] == 1000.
    assert all(method == "GET" for method, _ in core.calls)


def test_render_general_grid_and_blank_stale_frames(tmp_path):
    m = module()
    sources = [{"id": f"camera_{i}", "kind": "site"} for i in range(5)]
    s = m.Session(tmp_path / "session", sources, clock=lambda: 1000.)
    import io
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), "red").save(buf, format="JPEG")
    for source in sources:
        s.frame(source["id"], buf.getvalue(), {"seq": 1, "captured_at": 1000., "received_at": 1000.,
                                               "timeline_at": 1000., "clock": "source_utc", "rotation_deg": 0})
    s.finish()
    renderer = m.Renderer(s.out)
    image = renderer.frame(1000.5)
    assert image.size == (1280, 720)
    assert sum(image.tobytes()[i] > 200 and image.tobytes()[i + 1] < 50 for i in range(0, len(image.tobytes()), 3)) > 10000
    stale = renderer.frame(1004.)
    pixels = stale.tobytes()
    assert sum(pixels[i] > 200 and pixels[i + 1] < 50 for i in range(0, len(pixels), 3)) == 0


def test_workers_stop_independently_after_one_source_fails(tmp_path):
    m = module()
    import threading
    session = m.Session(tmp_path / "session", [{"id": "bad", "kind": "site"}, {"id": "good", "kind": "site"}])
    stop = threading.Event()
    def bad():
        raise OSError("secret URL and credential")
    def good():
        stop.set()
        return b"jpeg", {"seq": 1, "captured_at": 1., "received_at": 1., "timeline_at": 1.,
                         "clock": "receipt", "rotation_deg": 0}
    # Network exception text must not reach exported evidence.
    failed = threading.Event()
    def wrap_bad():
        try:
            return bad()
        finally:
            failed.set()
    thread = threading.Thread(target=m.collect, args=(session, "bad", wrap_bad, stop, .01))
    thread.start()
    assert failed.wait(2)
    m.collect(session, "good", good, stop, .01)
    thread.join(2)
    session.finish()
    text = (session.out / "session.json").read_text()
    assert "secret URL" not in text
    db = sqlite3.connect(session.out / "capture.sqlite3")
    assert db.execute("select source_id from frames").fetchall() == [("good",)]


def test_nonfinite_frame_and_tracking_do_not_poison_session(tmp_path):
    m = module()
    s = m.Session(tmp_path / "session", [{"id": "a", "kind": "robot"}], clock=lambda: 1000.)
    with pytest.raises(ValueError):
        s.frame("a", b"jpeg", {"seq": 1, "captured_at": float("nan"), "received_at": 1000.,
                               "timeline_at": 1000., "clock": "receipt"})
    assert s.by_id["a"]["latest"] is None
    with pytest.raises(ValueError):
        s.positions({"ts": float("nan"), "robots": []})
    assert s.position is None
    s.frame("a", b"jpeg", {"seq": 1, "captured_at": 1000., "received_at": 1000.,
                           "timeline_at": 1000., "clock": "source_utc"})
    s.finish()


def test_relative_session_and_large_robot_count(tmp_path, monkeypatch):
    m = module()
    monkeypatch.chdir(tmp_path)
    sources = [{"id": f"robot_{i}", "kind": "robot"} for i in range(20)]
    s = m.Session("session", sources, clock=lambda: 1000.)
    s.finish()
    renderer = m.Renderer("session")
    assert renderer.frame(1000.).height > 720


def test_wall_rejects_rebound_hosts(tmp_path):
    m = module()
    import functools
    import http.client
    import threading
    from http.server import ThreadingHTTPServer
    (tmp_path / "session.json").write_text('{"safe":true}')
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(m.LocalWall, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.request("GET", "/session.json", headers={"Host": "attacker.example"})
        r = conn.getresponse()
        assert r.status == 403
        r.read()
        conn.request("GET", "/session.json")
        r = conn.getresponse()
        assert r.status == 200 and json.loads(r.read())["safe"]
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
