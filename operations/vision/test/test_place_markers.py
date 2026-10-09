"""D-564: configured floor place markers are projected like robot markers and sent apart from sightings."""

import asyncio
import json
import math
from types import SimpleNamespace

import httpx

from core_common.protocol.place_markers import PlaceMarkerPayload, PlaceMarkerPose
from rosy_vision.project import CameraMap, project_place_markers
from rosy_vision.publish import SightingPublisher
from rosy_vision.worker import VisionWorker


def _quad(cx, cy, half=2):
    return ((cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half))


def _camera(place_markers=(34, 36)):
    return CameraMap(source_id="ceiling_north", map_id="site-v1", calibration_revision="cal-v3",
                     processor_revision="aruco-v1", corner_marker_ids=(30, 31, 32, 33),
                     corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)),
                     robot_markers={"rosy_01": 7}, heading_edge=(1, 2), place_markers=place_markers)


def _markers():
    # 400x200 px corners map to a 4x2 m rectangle; marker 34 at the middle faces +X, 7 is a robot.
    return {30: _quad(100, 100), 31: _quad(500, 100), 32: _quad(500, 300), 33: _quad(100, 300),
            34: _quad(300, 200, 10), 7: _quad(200, 150, 10), 35: _quad(400, 250, 10)}


def test_projects_only_configured_place_markers_with_heading_and_lineage():
    payload = project_place_markers(_camera(), seq=9, captured_at=50.0, markers=_markers())
    assert [m.marker_id for m in payload.markers] == [34]   # 36 not in view, 35 and 7 not place markers
    marker = payload.markers[0]
    assert math.isclose(marker.x, 2.0, abs_tol=1e-6) and math.isclose(marker.y, 1.0, abs_tol=1e-6)
    assert math.isclose(marker.yaw, 0.0, abs_tol=1e-6)
    assert (payload.map_id, payload.calibration_revision, payload.seq, payload.captured_at) == (
        "site-v1", "cal-v3", 9, 50.0)


def test_no_payload_without_corners_or_configured_markers():
    markers = _markers()
    markers.pop(32)
    assert project_place_markers(_camera(), seq=1, captured_at=1.0, markers=markers) is None
    assert project_place_markers(_camera(place_markers=()), seq=1, captured_at=1.0, markers=_markers()) is None
    assert project_place_markers(_camera(place_markers=(36,)), seq=1, captured_at=1.0, markers=_markers()) is None


class _Ingest:
    def __init__(self):
        self.frame = None

    def latest_frame(self, source_id):
        return self.frame

    def report_markers(self, *_args):
        pass


class _Publisher:
    def __init__(self, fail_places=False):
        self.sent, self.places, self.fail_places = [], [], fail_places

    async def publish(self, sighting):
        self.sent.append(sighting)

    async def publish_place_markers(self, payload):
        self.places.append(payload)
        if self.fail_places:
            raise RuntimeError("rejected")


def _frame(seq, captured_at):
    return SimpleNamespace(header=SimpleNamespace(seq=seq), jpeg=b"f", captured_at=captured_at,
                           received_at=captured_at)


def test_worker_sends_place_markers_at_most_twice_a_second_and_a_rejection_does_not_stop_sightings():
    clock = SimpleNamespace(now=100.0)
    ingest, publisher = _Ingest(), _Publisher(fail_places=True)
    worker = VisionWorker(source_id="ceiling_north", ingest=ingest, camera=_camera(), publisher=publisher,
                          detector=lambda _jpeg: _markers(), clock=lambda: clock.now)

    for seq, now in ((1, 100.0), (2, 100.2), (3, 100.6)):
        clock.now = now
        ingest.frame = _frame(seq, now - 0.05)
        asyncio.run(worker.process_latest())

    assert [s.seq for s in publisher.sent] == [1, 2, 3]
    assert [p.seq for p in publisher.places] == [1, 3]


def test_publisher_posts_place_markers_to_their_own_endpoint_with_the_source_token():
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"markers": []})

    payload = PlaceMarkerPayload(map_id="site-v1", calibration_revision="cal-v3", captured_at=1.0, seq=3,
                                 markers=(PlaceMarkerPose(marker_id=34, x=1.0, y=2.0, yaw=0.5),))

    async def run():
        async with SightingPublisher("http://127.0.0.1:8090", "source-secret",
                                     transport=httpx.MockTransport(handler)) as publisher:
            return await publisher.publish_place_markers(payload)

    assert asyncio.run(run()) == {"markers": []}
    assert observed[0].url.path == "/api/fleet/place-markers"
    assert observed[0].headers["authorization"] == "Bearer source-secret"
    assert json.loads(observed[0].content)["markers"][0]["marker_id"] == 34
