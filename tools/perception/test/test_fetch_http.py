"""D-411 A: HTTP fetch verifies every byte, refuses tar escapes and pair-checks the sidecar."""

import hashlib
import http.server
import io
import json
import tarfile
import threading

import fetch_http
import pytest

RID = "20261002T101500Z_rosy_01"


def _tar(entries):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, body in entries:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    return data.getvalue()


def _recording(tamper=False, extra=()):
    bag, session = b"m" * 300, json.dumps({"device": "rosy_01", "started_at": "2026-10-02T10:15:00Z"}).encode()
    files = [{"path": "bag/bag_0.mcap", "bytes": len(bag), "sha256": hashlib.sha256(bag).hexdigest()},
             {"path": "session.json", "bytes": len(session), "sha256": hashlib.sha256(session).hexdigest()}]
    manifest = json.dumps({"schema": fetch_http.MANIFEST_SCHEMA, "id": RID, "files": files}).encode()
    return _tar([(f"{RID}/manifest.json", manifest), (f"{RID}/bag/bag_0.mcap", b"x" * 300 if tamper else bag),
                 (f"{RID}/session.json", session), *extra])


@pytest.fixture
def server():
    state = {"listing": {"items": [{"id": RID, "status": "complete"}], "download_allowed": True,
                         "download_blocker": None}, "archive": _recording(), "auth": [],
             "short": False, "archive_status": 200}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state["auth"].append(self.headers.get("Authorization"))
            status = 200
            if self.path == "/api/v1/recordings":
                body = json.dumps(state["listing"]).encode()
            elif state["archive_status"] != 200:
                status = state["archive_status"]
                body = json.dumps({"error": {"code": "ROBOT_MOVING"}}).encode()
            else:
                body = state["archive"]
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            # A CORE that stops the stream mid-way (robot moved) sends fewer bytes than promised.
            self.wfile.write(body[: len(body) // 2] if state["short"] and status == 200
                             and self.path != "/api/v1/recordings" else body)
            if state["short"]:
                self.close_connection = True

        def log_message(self, *_):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    httpd.shutdown()
    httpd.server_close()


def _main(base, tmp_path, convert, *extra):
    token = tmp_path / "token"
    token.write_text("op-token\n", encoding="utf-8")
    return fetch_http.main([base, "--token-file", str(token), "--dest", str(tmp_path / "raw"),
                            "--video-out", str(tmp_path / "video"), *extra], convert=convert)


def _leftovers(tmp_path):
    raw = tmp_path / "raw"
    return [p.name for p in raw.iterdir()] if raw.exists() else []


def test_fetch_verifies_extracts_converts_and_pair_checks(server, tmp_path):
    base, state = server

    def convert(folder, out, codec):
        out.mkdir(parents=True, exist_ok=True)
        rows = [{"side": {"cmd_vel": {"linear": 0.1}, "teleop/intent": {"accepted": True}}},
                {"side": {"cmd_vel": None, "teleop/intent": None}}]
        path = out / "teleop_rosy_01_20261002T101500Z.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return 0, path

    assert _main(base, tmp_path, convert) == 0
    assert (tmp_path / "raw" / RID / "bag" / "bag_0.mcap").read_bytes() == b"m" * 300
    assert state["auth"][0] == "Bearer op-token"
    assert _leftovers(tmp_path) == [RID]


def test_already_fetched_recording_is_skipped(server, tmp_path):
    base, state = server
    (tmp_path / "raw" / RID).mkdir(parents=True)
    assert _main(base, tmp_path, lambda *a: pytest.fail("must not convert")) == 0
    assert len(state["auth"]) == 1                      # the listing only


def test_a_tampered_member_fails_and_leaves_nothing(server, tmp_path):
    base, state = server
    state["archive"] = _recording(tamper=True)
    assert _main(base, tmp_path, lambda *a: (0, None)) == 1
    assert _leftovers(tmp_path) == []


def test_a_file_missing_from_the_manifest_fails(server, tmp_path):
    base, state = server
    state["archive"] = _recording(extra=[(f"{RID}/stray.bin", b"s")])
    assert _main(base, tmp_path, lambda *a: (0, None)) == 1
    assert _leftovers(tmp_path) == []


def test_escaping_member_is_refused(server, tmp_path):
    base, state = server
    state["archive"] = _tar([("../evil.txt", b"x")])
    assert _main(base, tmp_path, lambda *a: (0, None)) == 1
    assert not (tmp_path / "evil.txt").exists()
    assert _leftovers(tmp_path) == []


def test_a_short_body_is_an_aborted_download(server, tmp_path):
    base, state = server
    state["short"] = True
    assert _main(base, tmp_path, lambda *a: pytest.fail("must not convert")) == 1
    assert _leftovers(tmp_path) == []


def test_robot_not_idle_exits_4(server, tmp_path):
    base, state = server
    state["listing"] = {**state["listing"], "download_allowed": False, "download_blocker": "ROBOT_MOVING"}
    assert _main(base, tmp_path, lambda *a: (0, None)) == fetch_http.EXIT_NOT_IDLE
    assert len(state["auth"]) == 1


def test_archive_409_stops_with_not_idle(server, tmp_path):
    base, state = server
    state["archive_status"] = 409
    assert _main(base, tmp_path, lambda *a: (0, None)) == fetch_http.EXIT_NOT_IDLE
    assert _leftovers(tmp_path) == []


def test_no_paired_frame_is_a_failure(server, tmp_path):
    base, _ = server

    def convert(folder, out, codec):
        out.mkdir(parents=True, exist_ok=True)
        path = out / "rows.jsonl"
        path.write_text(json.dumps({"side": {"cmd_vel": {"linear": 0.1}, "teleop/intent": None}}) + "\n",
                        encoding="utf-8")
        return 0, path

    assert _main(base, tmp_path, convert) == 1


def test_missing_token_is_a_usage_error(server, tmp_path, monkeypatch):
    base, _ = server
    monkeypatch.delenv(fetch_http.TOKEN_ENV, raising=False)
    assert fetch_http.main([base, "--dest", str(tmp_path / "raw")]) == 2


def test_pair_counts():
    rows = [{"side": {"cmd_vel": {}, "teleop/intent": {}}}, {"side": {"cmd_vel": {}, "teleop/intent": None}},
            {"side": {"cmd_vel": None, "teleop/intent": None}}]
    assert fetch_http.pair_counts(rows) == {"frames": 3, "with_cmd_vel": 2, "with_intent": 1, "paired": 1}


def test_manifest_schema_matches_the_robot_contract():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "contracts" / "foundation"))
    from core_common.protocol.recording import (
        MANIFEST_SCHEMA,
        RECORDING_ID,
        TELEOP_INTENT_TOPIC,
    )
    assert fetch_http.MANIFEST_SCHEMA == MANIFEST_SCHEMA and fetch_http.INTENT_TOPIC == TELEOP_INTENT_TOPIC
    assert fetch_http.RECORDING_ID.pattern == RECORDING_ID.pattern
