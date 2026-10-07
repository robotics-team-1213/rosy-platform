import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tools.decision_replay import replay


def test_choice_replay_and_fail_closed(tmp_path):
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
        with pytest.raises(ValueError, match="loopback"):
            replay(cases, "http://example.com/v1/systemone", "multilingual", 1)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
