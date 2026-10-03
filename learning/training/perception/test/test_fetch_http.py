"""D-411 A: HTTP fetch verifies every byte, refuses tar escapes and pair-checks the sidecar."""

import hashlib
import http.server
import io
import json
import tarfile
import threading

import pytest

import fetch_http

RID = "20261002T101500Z_rosy_01"
RID2 = "20261002T102000Z_rosy_01"


def _tar(entries):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for entry in entries:
            if isinstance(entry, tarfile.TarInfo):
                archive.addfile(entry)
                continue
            name, body = entry
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    return data.getvalue()


def _recording(tamper=False, extra=(), upper=False, rid=RID):
    bag, session = b"m" * 300, json.dumps({"device": "rosy_01", "started_at": "2026-10-02T10:15:00Z"}).encode()
    digest = (lambda b: hashlib.sha256(b).hexdigest().upper()) if upper else (lambda b: hashlib.sha256(b).hexdigest())
    files = [{"path": "bag/bag_0.mcap", "bytes": len(bag), "sha256": digest(bag)},
             {"path": "session.json", "bytes": len(session), "sha256": digest(session)}]
    manifest = json.dumps({"schema": fetch_http.MANIFEST_SCHEMA, "id": rid, "files": files}).encode()
    return _tar([(f"{rid}/manifest.json", manifest), (f"{rid}/bag/bag_0.mcap", b"x" * 300 if tamper else bag),
                 (f"{rid}/session.json", session), *extra])


@pytest.fixture
def server():
    state = {"listing": {"items": [{"id": RID, "status": "complete"}], "download_allowed": True,
                         "download_blocker": None}, "archive": _recording(), "auth": [], "paths": [],
             "short": False, "listing_status": 200, "archive_status": 200, "archive_code": "ROBOT_MOVING",
             "archive_headers": {}}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state["auth"].append(self.headers.get("Authorization"))
            state["paths"].append(self.path)
            listing = self.path == "/api/v1/recordings"
            status = state["listing_status"] if listing else state["archive_status"]
            if status != 200:
                body = json.dumps({"error": {"code": "UNAUTHORIZED" if listing else state["archive_code"]}}).encode()
            else:
                body = json.dumps(state["listing"]).encode() if listing else state["archive"]
            self.send_response(status)
            for key, value in ({} if listing else state["archive_headers"]).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            # A CORE that stops the stream mid-way (robot moved) sends fewer bytes than promised.
            short = state["short"] and status == 200 and not listing
            self.wfile.write(body[: len(body) // 2] if short else body)
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
    return sorted(p.name for p in raw.iterdir()) if raw.exists() else []


def _paired_convert(folder, out, codec):
    out.mkdir(parents=True, exist_ok=True)
    rows = [{"side": {"cmd_vel": {"linear": 0.1}, "teleop/intent": {"accepted": True}}},
            {"side": {"cmd_vel": None, "teleop/intent": None}}]
    path = out / f"{folder.name}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return 0, path


def test_fetch_verifies_extracts_converts_and_pair_checks(server, tmp_path, capsys):
    base, state = server
    assert _main(base, tmp_path, _paired_convert) == 0
    assert (tmp_path / "raw" / RID / "bag" / "bag_0.mcap").read_bytes() == b"m" * 300
    assert state["auth"][0] == "Bearer op-token"
    assert _leftovers(tmp_path) == [RID]
    assert "2 frames, 1 paired cmd_vel+intent (1 accepted)" in capsys.readouterr().out


def test_uppercase_sha256_in_the_manifest_is_accepted(server, tmp_path):
    base, state = server
    state["archive"] = _recording(upper=True)
    assert _main(base, tmp_path, _paired_convert) == 0


def test_leftover_part_and_staging_are_replaced(server, tmp_path):
    base, _ = server
    staging = tmp_path / "raw" / f".staging-{RID}" / RID
    staging.mkdir(parents=True)
    (staging / "stray.bin").write_bytes(b"old")           # would fail the manifest check if kept
    (tmp_path / "raw" / f".part-{RID}.tar").write_bytes(b"old partial")
    assert _main(base, tmp_path, _paired_convert) == 0
    assert _leftovers(tmp_path) == [RID]


def test_already_fetched_recording_is_skipped(server, tmp_path):
    base, state = server
    (tmp_path / "raw" / RID).mkdir(parents=True)
    assert _main(base, tmp_path, lambda *a: pytest.fail("must not convert")) == 0
    assert state["paths"] == ["/api/v1/recordings"]


def test_only_without_a_match_fails(server, tmp_path, capsys):
    base, _ = server
    assert _main(base, tmp_path, _paired_convert, "--only", RID2) == 1
    assert "no complete recording" in capsys.readouterr().err


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


@pytest.mark.parametrize("member", ["../evil.txt", f"{RID}/bag/CON.mcap", f"{RID}/a:b", f"{RID}/q?.bin",
                                    f"{RID}/trailing. ", "/abs.txt"])
def test_escaping_or_unportable_member_is_refused(server, tmp_path, member):
    base, state = server
    state["archive"] = _recording(extra=[(member, b"x")])
    assert _main(base, tmp_path, lambda *a: (0, None)) == 1
    assert not (tmp_path / "evil.txt").exists()
    assert _leftovers(tmp_path) == []


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.DIRTYPE])
def test_symlink_and_directory_members_are_refused(server, tmp_path, kind):
    base, state = server
    info = tarfile.TarInfo(f"{RID}/link")
    info.type = kind
    info.linkname = "../../outside" if kind == tarfile.SYMTYPE else ""
    state["archive"] = _recording(extra=[info])
    assert _main(base, tmp_path, lambda *a: (0, None)) == 1
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
    assert state["paths"] == ["/api/v1/recordings"]


def test_archive_409_keeps_an_earlier_recording_and_reports_failures(server, tmp_path, capsys):
    base, state = server
    state["listing"]["items"] = [{"id": RID2, "status": "complete"}, {"id": RID, "status": "complete"}]
    (tmp_path / "raw" / RID2).mkdir(parents=True)
    (tmp_path / "raw" / RID2 / "keep.txt").write_text("kept")
    state["archive_status"] = 409
    assert _main(base, tmp_path, lambda *a: (0, None)) == fetch_http.EXIT_NOT_IDLE
    assert (tmp_path / "raw" / RID2 / "keep.txt").read_text() == "kept"
    assert _leftovers(tmp_path) == [RID2]
    assert "robot not idle" in capsys.readouterr().err


@pytest.mark.parametrize("where", ["listing", "archive"])
def test_a_refused_token_stops_with_exit_2(server, tmp_path, capsys, where):
    base, state = server
    state["listing"]["items"].append({"id": RID2, "status": "complete"})
    if where == "listing":
        state["listing_status"] = 401
    else:
        state["archive_status"], state["archive_code"] = 403, "FORBIDDEN"
    assert _main(base, tmp_path, lambda *a: (0, None)) == 2
    assert "Operator token" in capsys.readouterr().err
    assert len(state["paths"]) == (1 if where == "listing" else 2)     # stops at the first refusal


def test_a_redirect_is_refused(server, tmp_path):
    base, state = server
    state["archive_status"], state["archive_headers"] = 302, {"Location": "/api/v1/recordings"}
    assert _main(base, tmp_path, lambda *a: (0, None)) == 1
    assert state["paths"] == ["/api/v1/recordings", f"/api/v1/recordings/{RID}/archive"]
    assert _leftovers(tmp_path) == []


def test_no_paired_frame_is_a_failure_and_keeps_the_verified_copy(server, tmp_path):
    base, _ = server

    def convert(folder, out, codec):
        out.mkdir(parents=True, exist_ok=True)
        path = out / "rows.jsonl"
        path.write_text(json.dumps({"side": {"cmd_vel": {"linear": 0.1}, "teleop/intent": None}}) + "\n",
                        encoding="utf-8")
        return 0, path

    assert _main(base, tmp_path, convert) == 1
    assert _leftovers(tmp_path) == [RID]


def test_missing_token_is_a_usage_error(server, tmp_path, monkeypatch):
    base, _ = server
    monkeypatch.delenv(fetch_http.TOKEN_ENV, raising=False)
    assert fetch_http.main([base, "--dest", str(tmp_path / "raw")]) == 2


def test_pair_counts():
    rows = [{"side": {"cmd_vel": {}, "teleop/intent": {"accepted": True}}},
            {"side": {"cmd_vel": {}, "teleop/intent": {"accepted": False}}},
            {"side": {"cmd_vel": {}, "teleop/intent": None}},
            {"side": {"cmd_vel": None, "teleop/intent": None}}]
    assert fetch_http.pair_counts(rows) == {"frames": 4, "with_cmd_vel": 3, "with_intent": 2, "paired": 2,
                                            "paired_accepted": 1}


def test_manifest_schema_matches_the_robot_contract():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "contracts" / "foundation"))
    from core_common.protocol.recording import MANIFEST_SCHEMA, RECORDING_ID, TELEOP_INTENT_TOPIC
    assert fetch_http.MANIFEST_SCHEMA == MANIFEST_SCHEMA and fetch_http.INTENT_TOPIC == TELEOP_INTENT_TOPIC
    assert fetch_http.RECORDING_ID.pattern == RECORDING_ID.pattern
