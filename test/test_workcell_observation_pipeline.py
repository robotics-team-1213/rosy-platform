"""Real verified HTTPS/WSS handoff from native bridge into Fleet and Vision."""
import asyncio
from hashlib import sha256
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import ssl
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from core_common.protocol.vision_preview import VisionLeaseSigner
from core_common.protocol.workcell_observations import WorkcellObservationManifest
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.workcell_observations import WorkcellObservations

ROOT = Path(__file__).resolve().parents[1]
# Match the source-only closure of the reused overhead test harness.
for relative in ("operations/overhead", "middleware/core/services", "operations/apps/games"):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)
from rosy_vision.ingest import IngestServer


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tls = _load("workcell_pipeline_tls", "operations/overhead/test/test_pairing_e2e.py")
bridge = _load("workcell_pipeline_bridge", "deploy/robot/omx/workcell_observation_bridge.py")


def test_native_bridge_reaches_real_fleet_and_vision_with_verified_transports(tmp_path):
    asyncio.run(_pipeline(tmp_path))


async def _pipeline(tmp_path):
    from PIL import Image
    manifest = WorkcellObservationManifest.model_validate({"schema": "rosy.workcell-observations/1", "workcells": [{
        "workcell_id": "example", "label": "Example", "arms": [{
            "source_id": "arm_feedback", "arm_id": "arm_a", "label": "Arm A", "board_id": "EXAMPLE-BOARD",
            "joint_topic": "/omx_commissioning/arm_a/joint_states", "joint_names": ["joint1"],
            "token_env": "EXAMPLE_ARM", "credential_sha256": sha256(b"arm-secret").hexdigest()}],
        "cameras": [{"source_id": "top", "label": "Top", "role": "overhead", "arm_id": None,
            "image_topic": "/top/image_raw", "device_path": "/dev/v4l/by-path/example-top",
            "token_env": "EXAMPLE_TOP", "credential_sha256": sha256(b"top-secret").hexdigest()}]}]})
    _, tokens = bridge.select_sources(manifest, "example", {"EXAMPLE_ARM": "arm-secret", "EXAMPLE_TOP": "top-secret"})
    signing = "preview-signing-" + "x" * 32
    cache = WorkcellObservations(manifest, {"arm_feedback": tokens["arm_feedback"]})
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=())
    app = create_app(FleetConsole([], []), task_service=tasks, start_task_dispatcher=False,
        site_users={sha256(b"viewer-secret").hexdigest(): {"principal_id": "reader", "role": "viewer"}},
        workcell_observations=cache, vision_lease_secret=signing, cell_job_compiler=None)
    pki = tls._write_pki(tmp_path)
    fleet_port = tls._free_port()
    fleet = tls.FleetThread(app, fleet_port, pki)
    await asyncio.to_thread(fleet.start)
    context = ssl.create_default_context(cafile=pki["ca"])
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(pki["chain"], pki["key"])
    ingest = IngestServer({"top": tokens["top"]}, preview_signer=VisionLeaseSigner(signing))
    ws_server = await ingest.start("127.0.0.1", 0, ssl_context=server_tls)
    vision_port = ws_server.sockets[0].getsockname()[1]
    fleet_url = f"https://127.0.0.1:{fleet_port}"
    camera = bridge.CameraSender(f"wss://127.0.0.1:{vision_port}", "top", tokens["top"], context=context)

    def read(url, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        with urlopen(Request(url, headers=headers), context=context, timeout=2) as response:
            return dict(response.headers), response.read()

    try:
        source = bridge.LatestSource()
        captured_at = time.time() - 0.4
        source.put(captured_at, {"joint1": 0.25})
        sender = bridge.ArmSender(fleet_url, "arm_feedback", tokens["arm_feedback"], context=context)
        await asyncio.to_thread(sender.send, source.latest())
        with pytest.raises(HTTPError) as refused:
            await asyncio.to_thread(read, fleet_url + "/api/fleet/workcell-observations")
        assert refused.value.code == 401
        headers, body = await asyncio.to_thread(read, fleet_url + "/api/fleet/workcell-observations", "viewer-secret")
        arm = json.loads(body)["workcells"][0]["arms"][0]
        assert arm["fresh"] and arm["positions"] == {"joint1": 0.25}
        assert arm["captured_at"] == captured_at and arm["sequence"] == 1 and arm["epoch"] == sender.epoch
        assert headers["Cache-Control"] == "no-store"
        assert b"credential_sha256" not in body and b"arm-secret" not in body

        _, body = await asyncio.to_thread(read, fleet_url + "/api/fleet/vision/sources", "viewer-secret")
        assert json.loads(body) == {"sources": ["top"]}
        request = Request(fleet_url + "/api/fleet/vision/lease", method="POST",
            data=b'{"source_id":"top"}', headers={"Authorization": "Bearer viewer-secret", "Content-Type": "application/json"})
        def lease():
            with urlopen(request, context=context, timeout=2) as response: return json.loads(response.read())
        issued = await asyncio.to_thread(lease)

        encoded = BytesIO()
        Image.new("RGB", (640, 480), "green").save(encoded, format="JPEG")
        jpeg = encoded.getvalue()
        image_source = bridge.LatestSource()
        camera_capture = time.time() - 0.4
        image_source.put(camera_capture, (jpeg, 640, 480))
        image_sample = image_source.latest()
        await asyncio.to_thread(camera.send, image_sample)
        frame = await tls._wait_for(lambda: ingest.latest_frame("top"), 3, "native camera frame")
        assert frame.jpeg == jpeg and frame.header.seq == image_sample.sequence
        assert (frame.header.width, frame.header.height) == (640, 480)
        assert frame.header.age_ms >= 399
        assert abs(frame.captured_at - camera_capture) < 0.25

        headers, body = await asyncio.to_thread(read, f"https://127.0.0.1:{vision_port}" + issued["frame_path"], issued["lease"])
        assert body == jpeg and headers["Cache-Control"] == "no-store"
        assert int(headers["X-Frame-Seq"]) == image_sample.sequence
    finally:
        await asyncio.to_thread(camera.close)
        ws_server.close()
        await ws_server.wait_closed()
        await asyncio.to_thread(fleet.stop)
