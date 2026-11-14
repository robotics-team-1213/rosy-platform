"""cell_site_camera: one site-camera frame through Fleet's vision lease, or a row saying why there is none."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_site_camera as ev  # noqa: E402

JPEG = b"\xff\xd8frame"


def serve(frame=JPEG):
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, body, code=200):
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            calls.append((self.path, self.headers["Authorization"], self.rfile.read(int(self.headers["Content-Length"]))))
            self.reply(json.dumps({"lease": "L1", "frame_path": "/api/vision/sources/cam/frame"}).encode())

        def do_GET(self):
            calls.append((self.path, self.headers["Authorization"], b""))
            self.reply(frame)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


def test_a_lease_then_the_frame_is_saved(tmp_path):
    srv, calls = serve()
    (tmp_path / "t").write_text("OPERATOR\n")
    conf = {"fleet_url": f"http://127.0.0.1:{srv.server_port}", "token_file": str(tmp_path / "t"), "source_id": "cam"}
    out = ev.fleet_frame(conf, tmp_path / "evidence", wait_s=0)
    srv.shutdown()
    assert Path(out["path"]).read_bytes() == JPEG and out["source"] == "cam"
    assert calls[0] == ("/api/fleet/vision/lease", "Bearer OPERATOR", b'{"source_id": "cam"}')
    assert calls[1][:2] == ("/api/vision/sources/cam/frame", "Bearer L1")  # the lease, not the operator token


def test_no_frame_is_a_row_not_an_error(tmp_path):
    srv, _ = serve(frame=b"stale")
    (tmp_path / "t").write_text("x")
    conf = {"fleet_url": f"http://127.0.0.1:{srv.server_port}", "token_file": str(tmp_path / "t"), "source_id": "cam"}
    assert ev.fleet_frame(conf, tmp_path, tries=2, wait_s=0) == {"frame": None, "source": "cam", "why": "not a JPEG"}
    srv.shutdown()
    assert ev.fleet_frame(dict(conf, token_file=str(tmp_path / "missing")), tmp_path)["frame"] is None
