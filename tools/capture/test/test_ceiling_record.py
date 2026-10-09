"""D-563 3 ceiling recorder against a fake site: lease, raw frames, calibration snapshot."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ceiling_record  # noqa: E402

RECORD = {"source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-test",
          "map_to_image": [1, 0, 0, 0, 1, 0, 0, 0, 1], "image": {"width": 64, "height": 48}}


class Fake(BaseHTTPRequestHandler):
    seq = 0
    leases = 0

    def log_message(self, *args):
        pass

    def _send(self, code, body, headers=()):
        self.send_response(code)
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        Fake.leases += 1
        assert json.loads(self.rfile.read(int(self.headers["Content-Length"]))) == {"source_id": "ceiling_north"}
        self._send(200, json.dumps({"lease": "L", "frame_path": "/api/vision/sources/ceiling_north/frame",
                                    "expires_in_s": 60}).encode())

    def do_GET(self):
        if self.path == "/api/fleet/calibrations":
            return self._send(200, json.dumps({"calibrations": [RECORD]}).encode())
        assert self.headers["Authorization"] == "Bearer L"
        Fake.seq += 1
        if Fake.seq == 2:
            return self._send(429, b"rate limited\n")
        seq = Fake.seq // 2  # every frame is served twice: the recorder keeps it once
        self._send(200, b"\xff\xd8jpeg" + bytes([seq]), [
            ("X-Frame-Seq", str(seq)), ("X-Frame-Captured-At", f"{1000 + seq}.5"),
            ("X-Frame-Width", "64"), ("X-Frame-Height", "48"), ("X-Frame-Rotation-Deg", "0"),
            ("X-Frame-Rectified", "false"), ("X-Source-Lens", "kind=standard;focal_mm=5.4;hfov_deg=67.8")])


def test_records_unique_frames_and_the_calibration(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        site = ceiling_record.Site(f"http://127.0.0.1:{server.server_address[1]}")
        saved = ceiling_record.record(site, tmp_path, duration=0.6, interval=0.0, sleep=lambda s: None)
    finally:
        server.shutdown()
    rows = [json.loads(line) for line in (tmp_path / "frames.jsonl").read_text().splitlines()]
    assert saved == len(rows) >= 3 and Fake.leases == 1
    assert len({r["seq"] for r in rows}) == len(rows)
    assert rows[0]["captured_at"] == 1000 + rows[0]["seq"] + 0.5 and rows[0]["rectified"] == "false"
    assert (tmp_path / rows[-1]["file"]).read_bytes().startswith(b"\xff\xd8")
    calibration = json.loads((tmp_path / "calibration.json").read_text())
    assert calibration["record"] == RECORD
    assert calibration["frame_lens"] == {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 67.8}


def test_calibration_is_written_before_the_first_frame(tmp_path):
    class Dead:
        def request(self, path, body=None, bearer=None):
            if path == "/api/fleet/calibrations":
                return json.dumps({"calibrations": [RECORD]}).encode(), {}
            assert json.loads((tmp_path / "calibration.json").read_text())["record"] == RECORD
            raise KeyboardInterrupt  # killed mid-run
    assert ceiling_record.record(Dead(), tmp_path) == 0
