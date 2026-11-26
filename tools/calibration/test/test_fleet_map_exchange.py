"""Tests for tools/calibration/fleet_map_exchange.py against a local HTTP stub."""

from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fleet_map_exchange as fme  # noqa: E402
import slam_map_align as sma  # noqa: E402


class _StubState:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.master: dict | None = None
        self.state_payload: dict = {"robots": {}}
        self.activation_phase: str = "ACTIVE"
        pgm = b"P5\n4 4\n255\n" + bytes([0] * 4 + [0, 254, 254, 0] * 2 + [0] * 4)
        self.bundle_payload = {
            "robot_id": "rosy_46",
            "map_id": "slam-1",
            "width": 4,
            "height": 4,
            "sha256": hashlib.sha256(pgm).hexdigest(),
            "pgm_base64": base64.b64encode(pgm).decode("ascii"),
            "yaml": {
                "image": "robot_rosy_46.pgm",
                "mode": "trinary",
                "resolution": 0.05,
                "origin": [-0.1, -0.1, 0.0],
                "negate": 0,
                "occupied_thresh": 0.65,
                "free_thresh": 0.196,
            },
        }


def _serve(stub: _StubState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _reply(self, code: int, body: dict):
            raw = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            stub.calls.append(("GET", self.path, {}))
            if self.path == "/api/fleet/robots/rosy_46/map/bundle":
                self._reply(200, stub.bundle_payload)
            elif self.path == "/api/fleet/site-map/master-grid":
                if stub.master is None:
                    self._reply(404, {"detail": {"code": "MASTER_GRID_NOT_SET"}})
                else:
                    self._reply(200, stub.master)
            elif self.path == "/api/fleet/state":
                self._reply(200, stub.state_payload)
            else:
                self._reply(404, {"detail": {"code": "NOT_FOUND"}})

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            return json.loads(raw)

        def do_PUT(self):
            body = self._read_json()
            stub.calls.append(("PUT", self.path, body))
            if self.path == "/api/fleet/site-map/master-grid":
                stub.master = {
                    "site_map_id": body.get("site_map_id", "map_v2_fleet"),
                    "version": body.get("version", 1),
                    "grid_id": body["grid_id"],
                    "sha256": body["sha256"],
                }
                self._reply(200, stub.master)
            else:
                self._reply(404, {})

        def do_POST(self):
            body = self._read_json()
            stub.calls.append(("POST", self.path, body))
            if self.path.endswith("/master-map/push"):
                rid = self.path.split("/")[4]
                act = {"phase": stub.activation_phase} if body.get("activate") else None
                self._reply(200, {"robot_id": rid, "activate": body.get("activate", False),
                                  "robot_reply": {"staged": True, "activation": act}})
            else:
                self._reply(404, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _write_sealed_bundle(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    cells = np.full((12, 12), 254, dtype=np.uint8)
    cells[0, :] = cells[-1, :] = cells[:, 0] = cells[:, -1] = 0
    (src / "raw.pgm").write_bytes(b"P5\n12 12\n255\n" + cells.tobytes())
    raw_yaml = src / "raw.yaml"
    raw_yaml.write_text(
        "image: raw.pgm\nmode: trinary\nresolution: 0.05\norigin: [-0.3, -0.3, 0.0]\n"
        "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n",
        encoding="utf-8",
    )
    mb = sma.load_map_bundle_module()
    return mb.import_saved(
        raw_yaml, tmp_path / "sealed", "master_v1",
        margin_m=0.05, source="rosy_45+rosy_46", site_map_id="map_v2_fleet", require_zero_yaw=True,
    )


def test_pull_upload_push_and_verify_loc_cli(tmp_path):
    stub = _StubState()
    server, url = _serve(stub)
    try:
        out_dir = tmp_path / "pulled"
        assert fme.main(["--fleet-url", url, "--token", "t", "pull", "--robot", "rosy_46",
                         "--out-dir", str(out_dir)]) == 0
        assert (out_dir / "robot_rosy_46.pgm").is_file()
        assert yaml.safe_load((out_dir / "robot_rosy_46.yaml").read_text(encoding="utf-8"))["free_thresh"] == 0.196

        sealed = _write_sealed_bundle(tmp_path)
        assert fme.main(["--fleet-url", url, "--token", "t", "upload", str(sealed), "--version", "1"]) == 0
        assert stub.master is not None

        assert fme.main(["--fleet-url", url, "--token", "t", "push",
                         "--robot", "rosy_46", "--robot", "rosy_45", "--activate"]) == 0
        pushes = [c for c in stub.calls if c[0] == "POST"]
        assert len(pushes) == 2 and all(c[2]["activate"] is True for c in pushes)

        grid_id = stub.master["grid_id"]
        stub.state_payload = {
            "robots": {
                "rosy_46": {"online": True, "map_grid_id": grid_id,
                            "localization": {"state": "LOCALIZED", "pose_frame": "map"}},
                "rosy_45": {"online": True, "map_grid_id": grid_id,
                            "localization": {"state": "LOCALIZED", "pose_frame": "map"}},
            }
        }
        assert fme.main(["--fleet-url", url, "--token", "t", "verify-loc",
                         "--robot", "rosy_46", "--robot", "rosy_45", "--wait-s", "0.5"]) == 0

        stub.state_payload["robots"]["rosy_45"]["localization"]["state"] = "CANDIDATES"
        assert fme.main(["--fleet-url", url, "--token", "t", "verify-loc",
                         "--robot", "rosy_46", "--robot", "rosy_45", "--wait-s", "0.05", "--poll-s", "0.05"]) == 2

        stub.activation_phase = "ROLLED_BACK"
        assert fme.main(["--fleet-url", url, "--token", "t", "push", "--robot", "rosy_46", "--activate"]) == 2

        stub.state_payload = {
            "robots": [
                {
                    "robot_id": "rosy_46",
                    "online": True,
                    "state": {"map_grid_id": grid_id, "localization": {"state": "LOCALIZED", "pose_frame": "map"}},
                },
                {
                    "robot_id": "rosy_45",
                    "online": True,
                    "state": {"map_grid_id": grid_id, "localization": {"state": "LOCALIZED", "pose_frame": "map"}},
                },
            ]
        }
        assert fme.main(["--fleet-url", url, "--token", "t", "verify-loc",
                         "--robot", "rosy_46", "--robot", "rosy_45", "--wait-s", "0.5"]) == 0
    finally:
        server.shutdown()
