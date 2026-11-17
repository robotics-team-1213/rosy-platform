"""Vision to Fleet POSTs: age re-check, anchors off the detections path, stats line, pooled-connection limits."""

import asyncio
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from rosy_vision import cli, publish
from rosy_vision.post_guard import MAX_POST_AGE_S, PostGuard
from rosy_vision.track import anchor_feed, fleet_client
from rosy_vision.track.anchor_head_tracker import AnchorHeadTracker
from rosy_vision.track.fleet_client import TrackClient
from rosy_vision.track.model import Calibration, Detection, DetectorResult
from rosy_vision.track.worker import TrackWorker
from rosy_vision.worker import VisionWorker

from test_vision_worker import _Ingest as _VIngest, _Publisher as _VPublisher, _camera as _vcamera, _frame as _vframe, _markers
from test_overhead_track_worker import CAMERA, CONFIG, FOUND, JPEG, _Client, _Detector, _frame, _Ingest


class _Now:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def _count(guard):
    return (guard.posted, guard.dropped_stale, guard.post_errors, guard.last_post_age_ms)


def test_guard_posts_fresh_drops_stale_without_calling_and_counts_errors():
    now = _Now()
    guard = PostGuard("ceiling_north", now)
    calls = []

    async def call():
        calls.append(1)
        now.now += 0.05
        return "ok"

    async def boom():
        raise httpx.ReadTimeout("x")

    async def run():
        assert await guard.post(99.9, call) == "ok"                       # 0.1 s old
        assert await guard.post(100.0 - MAX_POST_AGE_S - 0.01, call) is None  # stale: call() is never made
        with pytest.raises(httpx.ReadTimeout):
            await guard.post(now.now, boom)
    asyncio.run(run())
    assert calls == [1]
    assert _count(guard) == (1, 1, 1, 150)
    assert guard.stats_line() == ("ceiling_north: fleet_posts posted=1 dropped_stale=1 post_errors=1 "
                                  "last_post_age_ms=150")


def _worker(now, detector, client=None, **kw):
    return TrackWorker(camera=CAMERA, ingest=_Ingest(), client=client or _Client(configs=[CONFIG]),
                       detector=detector, clock=now, auto_tune=False, **kw)


class _SlowDetector(_Detector):
    """Detection takes ``cost_s`` of the shared clock, like a loaded N150."""

    def __init__(self, now, cost_s):
        super().__init__(FOUND)
        self.now, self.cost_s = now, cost_s

    def detect(self, frame, calib):
        self.now.now += self.cost_s
        return super().detect(frame, calib)


@pytest.mark.parametrize("cost_s,published", [(0.1, 1), (0.9, 0)])
def test_detections_that_aged_during_processing_are_dropped_not_posted(cost_s, published):
    now = _Now()
    worker = _worker(now, _SlowDetector(now, cost_s))
    try:
        asyncio.run(worker.refresh_config())
        asyncio.run(worker.process(_frame(captured_at=99.9), {}))
    finally:
        worker.close()
    assert len(worker.client.published) == published
    assert (worker.guard.posted, worker.guard.dropped_stale) == (published, 1 - published)


def test_a_stale_marker_sighting_is_not_posted_and_a_fresh_one_is():
    now = _Now(110.0)
    sent = []

    class _Sightings:
        async def publish(self, sighting):
            sent.append(sighting)

    worker = TrackWorker(camera=CAMERA, ingest=_Ingest(), client=_Client(), clock=now, sightings=_Sightings(),
                         detector=_Detector(), auto_tune=False)
    stale = SimpleNamespace(captured_at=100.0, robot_id="rosy_01")
    fresh = SimpleNamespace(captured_at=109.8, robot_id="rosy_02")
    try:
        worker.anchors.sightings = (stale, fresh)
        asyncio.run(worker._publish_sightings(CAMERA, None, _frame(), {}, frozenset()))
    finally:
        worker.close()
    assert sent == [fresh] and _count(worker.guard)[:2] == (1, 1)


def test_vision_worker_drops_a_sighting_that_aged_and_shares_the_trackers_counters():
    now = _Now()
    publisher = _VPublisher()

    def slow_detector(_jpeg):
        now.now += 0.5  # 0.25 s old at the check in process_latest, 0.75 s old at the POST: still fresh
        return _markers()

    def slower_detector(_jpeg):
        now.now += 0.7
        return _markers()
    tracker = _worker(now, _Detector())
    try:
        for detector, sent in ((slow_detector, 1), (slower_detector, 0)):
            now.now = 100.0
            worker = VisionWorker(source_id="ceiling_north", ingest=_VIngest(_vframe()), camera=_vcamera(),
                                  publisher=publisher, detector=detector, clock=now, tracker=tracker)
            before = len(publisher.sent)
            asyncio.run(worker.process_latest())
            assert len(publisher.sent) - before == sent
        assert worker.guard is tracker.guard
        assert _count(worker.guard)[:2] == (1, 1)
    finally:
        tracker.close()


class _States:
    """Stand-in head tracker: one OMX arm and two Pinkies, only one of them with its marker."""

    def step(self, image, captured_at, calibration, result, **kwargs):
        return result, (), [{"target_id": "arm_a", "kind": "omx_ai"}, {"target_id": "rosy_46", "kind": "pinky"},
                            {"target_id": "rosy_45", "kind": "pinky"}]

    def marker_seen(self, target_id):
        return target_id == "rosy_46"


class _AnchorClient(_Client):
    def __init__(self, hang=False):
        super().__init__(configs=[CONFIG])
        self.anchors, self.hang, self.order = [], hang, []

    async def publish(self, payload):
        self.order.append("detections")
        return await super().publish(payload)

    async def publish_anchors(self, body):
        self.order.append("anchors")
        self.anchors.append(body)
        if self.hang:
            await asyncio.Event().wait()


def test_anchors_go_after_the_detections_without_the_markerless_pinky_guess():
    now = _Now()
    client = _AnchorClient()
    worker = _worker(now, _Detector(), client)
    worker.anchors.tracker = _States()

    async def run():
        await worker.refresh_config()
        await worker.process(_frame(captured_at=99.9), {})
        await asyncio.sleep(0.01)
    try:
        asyncio.run(run())
    finally:
        worker.close()
    assert client.order == ["detections", "anchors"]
    (body,) = client.anchors
    assert [t["target_id"] for t in body["targets"]] == ["arm_a", "rosy_46"]
    assert (body["source_id"], body["map_id"], body["captured_at"]) == ("ceiling_north", "map_v2_fleet", 99.9)


def test_a_hung_anchors_post_never_delays_the_detections_and_times_out_counted(monkeypatch):
    monkeypatch.setattr(anchor_feed, "POST_TIMEOUT_S", 0.05)
    now = _Now()
    client = _AnchorClient(hang=True)
    worker = _worker(now, _Detector(), client)
    worker.anchors.tracker = _States()

    async def run():
        await worker.refresh_config()
        first = await worker.process(_frame(seq=1, captured_at=99.9), {})
        await asyncio.sleep(0.01)
        assert first is not None and client.published == [first]   # detections out while anchors hang
        worker.anchors._next_at = 0.0
        await worker.process(_frame(seq=2, captured_at=99.95), {})  # previous send in flight: not queued
        assert len(client.anchors) == 1 and len(client.published) == 2
        await asyncio.sleep(0.15)
    try:
        asyncio.run(run())
    finally:
        worker.close()
    assert worker.guard.post_errors == 1


def test_anchors_are_stepped_at_most_once_a_second_and_a_stale_state_is_dropped():
    now = _Now()
    guard = PostGuard("ceiling_north", now)
    client = _AnchorClient()
    feed = anchor_feed.AnchorFeed("ceiling_north", "map_v2_fleet", client, guard, now)
    feed.tracker = _States()
    result = DetectorResult((), "OK")
    args = (None, 99.9, None, result)
    kw = {"processor_revision": "p", "seq": 1}

    async def run():
        feed.step(*args, **kw)
        feed.send()
        await asyncio.sleep(0.01)
        feed.step(*args, **kw)           # same second: tracker not run, nothing pending
        feed.send()
        await asyncio.sleep(0.01)
        assert len(client.anchors) == 1
        now.now += 1.5
        feed.step(None, 100.0, None, result, **kw)   # captured 1.5 s ago by the time it is sent
        feed.send()
        await asyncio.sleep(0.01)
    asyncio.run(run())
    assert len(client.anchors) == 1 and guard.dropped_stale == 1


def _calibration():
    return Calibration("ceiling_north", "map_v2_fleet", "cal-v3", tuple(np.diag([.0025, .0025, 1.]).ravel()),
                       (640, 360), (0.0, 0.0, 1.6, 0.9), 60.0)


@pytest.mark.parametrize("marker_id,seen", [(None, False), (9, True)])
def test_a_pinky_without_its_own_marker_is_a_home_guess_never_a_sighting(marker_id, seen):
    tracker = AnchorHeadTracker()
    tracker.update_from_config({"robot_markers": {"rosy_46": 9}, "anchors": [
        {"target_id": "rosy_46", "kind": "pinky", "base_x": 0.5, "base_y": 0.4, "updated_at": 1.0}]})
    result = DetectorResult((Detection(0.5, 0.4, 0.16, 0.9, marker_id),), "OK")
    image = np.full((360, 640, 3), 120, np.uint8)
    _, sightings, _ = tracker.step(image, 100.0, _calibration(), result, source_id="ceiling_north",
                                   map_id="map_v2_fleet", processor_revision="p", seq=1)
    assert tracker.marker_seen("rosy_46") is seen
    if not seen:
        assert sightings == ()


def test_stats_block_per_source_has_ingest_line_and_post_counters():
    snap = {"frames": 9, "rx_fps": 3.0, "bytes_per_s": 100, "age_ms_p50": 20, "age_ms_max": 40,
            "dropped_bad_header": 0, "oversize": 0, "last_seq": 8, "seq_gaps": 0}
    ingest = SimpleNamespace(stats=lambda source: snap if source == "ceiling_north" else None)
    guard = PostGuard("ceiling_north", _Now())
    guard.posted, guard.dropped_stale, guard.post_errors, guard.last_post_age_ms = 5, 2, 1, 130
    other = PostGuard("bench", _Now())
    workers = [SimpleNamespace(source_id="ceiling_north", guard=guard), SimpleNamespace(source_id="bench", guard=other)]
    assert cli._vision_stats_lines(ingest, workers) == [
        cli._format_stats_line("ceiling_north", snap),
        "ceiling_north: fleet_posts posted=5 dropped_stale=2 post_errors=1 last_post_age_ms=130",
        "bench: no camera connected",
        "bench: fleet_posts posted=0 dropped_stale=0 post_errors=0 last_post_age_ms=-"]
    assert cli.VISION_STATS_INTERVAL_S == 30.0


def test_pooled_connections_expire_before_fleet_and_caddy_close_them(monkeypatch):
    seen = []

    class _Spy:
        def __init__(self, **kwargs):
            seen.append(kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Spy)
    TrackClient("http://fleet:8090", "tok")
    publish.SightingPublisher("http://fleet:8090", "tok")
    assert len(seen) == 2
    for kwargs in seen:
        assert kwargs["limits"].keepalive_expiry == fleet_client.KEEPALIVE_EXPIRY_S
    assert fleet_client.KEEPALIVE_EXPIRY_S <= 30.0  # Fleet's uvicorn keep-alive is 75 s, Caddy's idle pool ~90 s


def test_publish_anchors_posts_with_the_source_token_and_retries_one_dropped_connection():
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(200, json={"accepted": True, "count": 1})

    async def run():
        async with TrackClient("http://127.0.0.1:8090", "source-secret",
                               transport=httpx.MockTransport(handler)) as client:
            return await client.publish_anchors({"targets": []})
    assert asyncio.run(run()) == {"accepted": True, "count": 1}
    assert [(r.method, r.url.path) for r in seen] == [("POST", "/api/fleet/detections/anchors")] * 2
    assert seen[1].headers["authorization"] == "Bearer source-secret"
