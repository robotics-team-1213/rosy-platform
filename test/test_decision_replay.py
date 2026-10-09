import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tools.decision_replay import main, replay


def test_choice_replay_and_fail_closed(tmp_path, monkeypatch, capsys):
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(json.dumps({
        "id": str(i), "state": {"fact": "person ahead", "case": i},
        "instructions": "Choose an advisory candidate from the facts.",
        "criteria": {"WAIT": "person or robot", "ESCALATE": "uncertain"},
        "expected": "WAIT",
    }) for i in range(2)), encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["questions"]["decision"]["type"] == "choice"
            assert body["model"] == "multilingual"
            choice = "WAIT" if body["state"]["case"] == 0 else "MOVE"
            response = {"answers": {"decision": {"choice": choice}}}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/systemone"
        result = replay(cases, url, "multilingual", 1)
        assert result["summary"]["correct"] == 1
        assert result["summary"]["abstain_or_error"] == 1
        assert result["cases"][1]["error"] == "ValueError"
        monkeypatch.setattr(sys, "argv", ["decision_replay.py", str(cases),
                                      "--endpoint", url, "--model", "multilingual"])
        assert main() == 1
        assert json.loads(capsys.readouterr().out)["summary"]["abstain_or_error"] == 1
        with pytest.raises(ValueError, match="loopback"):
            replay(cases, "http://example.com/v1/systemone", "multilingual", 1)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_replay_validates_whole_dataset_before_calls_and_records_hash(tmp_path, monkeypatch, capsys):
    cases = tmp_path / "cases.jsonl"
    valid = {"id": "first", "state": {"fact": "person"}, "instructions": "Choose.",
             "criteria": {"WAIT": "person", "ESCALATE": "unknown"}, "expected": "WAIT"}
    invalid = {**valid, "id": "second", "expected": "MOVE"}
    cases.write_text("\n".join(map(json.dumps, (valid, invalid))) + "\n", encoding="utf-8")
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({"answers": {"decision": {"choice": "WAIT"}}}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/systemone"
        with pytest.raises(ValueError, match="line 2"):
            replay(cases, url, "multilingual", 1)
        assert calls == []

        cases.write_text(json.dumps(valid) + "\n", encoding="utf-8")
        result = replay(cases, url, "multilingual", 1)
        assert result["dataset_sha256"] == hashlib.sha256(cases.read_bytes()).hexdigest()
        assert result["summary"]["correct"] == 1
        monkeypatch.setattr(sys, "argv", ["decision_replay.py", str(cases),
                                      "--endpoint", url, "--model", "multilingual"])
        assert main() == 0
        assert json.loads(capsys.readouterr().out)["summary"]["count"] == 1
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_replay_records_invalid_server_bytes_and_continues(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(json.dumps({
        "id": str(i), "state": {"case": i}, "instructions": "Choose.",
        "criteria": {"WAIT": "person", "ESCALATE": "unknown"}, "expected": "WAIT",
    }) for i in range(2)), encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = (b"\xff" if state["state"]["case"] == 0 else
                    b'{"answers":{"decision":{"choice":"WAIT"}}}')
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = replay(cases, f"http://127.0.0.1:{server.server_port}/v1/systemone",
                        "multilingual", 1)
        assert result["summary"]["count"] == 2
        assert result["cases"][0]["error"] == "UnicodeDecodeError"
        assert result["cases"][1]["correct"] is True
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
