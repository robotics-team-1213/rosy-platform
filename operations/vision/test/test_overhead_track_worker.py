"""D-457 2-4: one tracking step per fresh frame, hooked after the ArUco step of VisionWorker."""

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from rosy_vision.project import CameraMap
from rosy_vision.track.fleet_client import TrackPublishError
from rosy_vision.track.model import Detection, DetectorResult
from rosy_vision.track.worker import TrackWorker, build_payload
from rosy_vision.worker import VisionWorker

FIXTURE = json.loads((Path(__file__).resolve().parents[3]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}
CONFIG = FIXTURE["config_example"]
CAMERA = CameraMap(
    source_id="ceiling_north", map_id="map_v2_fleet", calibration_revision="cal-v3",
    processor_revision="aruco-v1", corner_marker_ids=(30, 31, 32, 33),
    corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)), robot_markers={"rosy_01": 7},
)
JPEG = cv2.imencode(".jpg", np.full((360, 640, 3), 120, np.uint8))[1].tobytes()
FOUND = DetectorResult((Detection(1.2345, 0.4321, 0.181, 0.83), Detection(2.5, 1.0, 0.2, 0.5)), "OK")


def _quad(cx, cy, half=2):
    return ((cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half))


MARKERS = {30: _quad(100, 100), 31: _quad(500, 100), 32: _quad(500, 300), 33: _quad(100, 300),
           7: _quad(300, 200, 10)}


class _Detector:
    processor_revision = "background-blob/1"

    def __init__(self, result=FOUND):
        self.result = result
        self.calls = []
        self.resets = 0
        self.threads = set()

    def detect(self, frame, calib):
        self.threads.add(threading.get_ident())
        self.calls.append((frame, calib))
        return self.result

    def reset(self):
        self.threads.add(threading.get_ident())
        self.resets += 1


class _Client:
    def __init__(self, configs=(), error=None):
        self.configs = list(configs)
        self.published = []
        self.error = error

    async def publish(self, payload):
        self.published.append(payload)
        if self.error is not None:
            raise self.error
        return {"accepted": True}

    async def fetch_config(self):
        return self.configs.pop(0)

    async def publish_identity(self, body):
        self.identity = getattr(self, "identity", []) + [body]
        return {"accepted": True}


class _Ingest:
    def __init__(self, lens=None, frame=None):
        self.lens = lens
        self.frame = frame
        self.reports = []

    def source_lens(self, source_id):
        assert source_id == "ceiling_north"
        return self.lens

    def latest_frame(self, source_id):
        return self.frame

    def report_markers(self, source_id, corners_seen, robots_seen):
        self.reports.append((source_id, list(corners_seen), list(robots_seen)))

    def report_calibration(self, source_id, record, map_id):
        self.calibration = (source_id, record, map_id)


def test_robot_marker_uses_approved_fit_when_corners_absent_even_during_blob_learning():
    client = _Client()
    detector = _Detector(DetectorResult((), "LEARNING"))
    worker = TrackWorker(camera=CAMERA, ingest=_Ingest(), client=client, detector=detector,
                         decode=lambda jpeg: np.full((360, 640, 3), 120, np.uint8))
    quad = ((98, 48), (102, 48), (102, 52), (98, 52))
    record = CONFIG["calibration"]
    calibration, result = worker._detect(JPEG, 99.75, {7: quad}, record, None, None)
    assert calibration.revision == record["calibration_revision"]
    assert result.status == "OK"
    assert len(result.detections) == 1
    assert result.detections[0].marker_id == 7
    assert (result.detections[0].x, result.detections[0].y) == pytest.approx((1, 3.1))
    _, fallback = worker._detect(JPEG, 100, {}, record, None, None)
    assert fallback.status == "LEARNING" and not fallback.detections


def test_marker_frame_retains_blobs_for_single_deduplication_in_fleet():
    detector = _Detector(DetectorResult((Detection(1, 3.1, .165, .8),
                                        Detection(1.22, 3.1, .26, .8)), "OK"))
    worker = TrackWorker(camera=CAMERA, ingest=_Ingest(), client=_Client(), detector=detector,
                         decode=lambda jpeg: np.full((360, 640, 3), 120, np.uint8))
    quad = ((98, 48), (102, 48), (102, 52), (98, 52))
    _, result = worker._detect(JPEG, 99.75, {7: quad}, CONFIG["calibration"], None, None)
    assert len(result.detections) == 3
    assert [d.x for d in result.detections if d.marker_id is None] == [1, 1.22]



def test_an_unassigned_robot_sticker_is_sent_and_other_ids_are_not():
    # D-575: id 41 (D-562 robot range) has no robot in robot_markers yet; Fleet shows it
    # as an unknown robot. A game marker (12) on the floor is not a robot.
    worker = TrackWorker(camera=CAMERA, ingest=_Ingest(), client=_Client(),
                         detector=_Detector(DetectorResult((), "OK")),
                         decode=lambda jpeg: np.full((360, 640, 3), 120, np.uint8))
    markers = {7: ((98, 48), (102, 48), (102, 52), (98, 52)),
               41: ((198, 48), (202, 48), (202, 52), (198, 52)),
               12: ((298, 48), (302, 48), (302, 52), (298, 52))}
    _, result = worker._detect(JPEG, 99.75, markers, CONFIG["calibration"], None, None)
    assert sorted(d.marker_id for d in result.detections) == [7, 41]

def _frame(seq=1, captured_at=99.75, jpeg=JPEG):
    return SimpleNamespace(header=SimpleNamespace(seq=seq), jpeg=jpeg, captured_at=captured_at,
                           received_at=100.0)


@pytest.fixture
def make_worker():
    """TrackWorker factory; every worker's detection thread is stopped on teardown."""
    workers = []

    def make(*, configs=(), lens=None, detector=None, error=None, clock=None):
        client = _Client(configs, error)
        extra = {} if clock is None else {"clock": clock}
        worker = TrackWorker(camera=CAMERA, ingest=_Ingest(lens), client=client,
                             detector=detector or _Detector(), **extra)
        workers.append(worker)
        return worker, client

    yield make
    for worker in workers:
        worker.close()


def test_payload_builder_matches_the_shared_vector():
    payload = build_payload(source_id="ceiling_north", map_id="map_v2_fleet",
                            calibration_revision="paint-3f9a1c2b7d40",
                            processor_revision="background-blob/1", captured_at=1790000000.25,
                            seq=41, result=FOUND)
    assert payload.model_dump(mode="json") == CASES["ok_two_detections"]["payload"]


def test_without_calibration_the_payload_says_so_and_the_detector_is_not_run(make_worker):
    detector = _Detector()
    worker, client = make_worker(detector=detector)
    payload = asyncio.run(worker.process(_frame(), {}))
    assert (payload.status, payload.calibration_revision, payload.detections) == (
        "CALIBRATION_REQUIRED", None, ())
    assert detector.calls == [] and client.published == [payload]


def test_the_approved_record_is_used_when_markers_are_missing(make_worker):
    detector = _Detector()
    worker, client = make_worker(configs=[CONFIG], detector=detector)
    asyncio.run(worker.refresh_config())
    payload = asyncio.run(worker.process(_frame(), {}))
    assert payload.calibration_revision == "paint-3f9a1c2b7d40"
    assert [(d.x, d.y) for d in payload.detections] == [(1.2345, 0.4321), (2.5, 1.0)]
    assert detector.calls[0][1].image_size == (640, 360)
    assert detector.calls[0][0].captured_at == 99.75


def test_the_read_record_is_handed_to_the_ingest_for_the_map_plane(make_worker):
    """D-560: the ingest warps the map plane with the record tracking reads, no second client."""
    worker, _ = make_worker(configs=[CONFIG])
    asyncio.run(worker.refresh_config())
    assert worker.ingest.calibration == ("ceiling_north", CONFIG["calibration"], "map_v2_fleet")


def test_a_config_without_calibration_clears_the_ingest_record(make_worker):
    worker, _ = make_worker(configs=[CONFIG, {**CONFIG, "calibration": None}])
    asyncio.run(worker.refresh_config())
    asyncio.run(worker.refresh_config())
    assert worker.ingest.calibration == ("ceiling_north", None, "map_v2_fleet")


def test_the_approved_record_wins_over_corner_markers(make_worker):
    # D-595: the accepted record is frozen; four corner markers in the frame never re-fit it.
    detector = _Detector()
    worker, _ = make_worker(configs=[CONFIG], detector=detector)
    asyncio.run(worker.refresh_config())
    payload = asyncio.run(worker.process(_frame(), MARKERS))
    assert payload.calibration_revision == CONFIG["calibration"]["calibration_revision"]


def test_corner_markers_calibrate_only_without_a_record(make_worker):
    detector = _Detector()
    worker, _ = make_worker(configs=[{**CONFIG, "calibration": None}], detector=detector)
    asyncio.run(worker.refresh_config())
    payload = asyncio.run(worker.process(_frame(), MARKERS))
    assert payload.calibration_revision == "cal-v3"
    assert detector.calls[0][1].track_bounds_m == (0.0, 0.0, 4.0, 2.0)


def test_a_new_lens_invalidates_the_record(make_worker):
    worker, _ = make_worker(configs=[CONFIG], lens={"kind": "wide", "focal_mm": 2.2, "hfov_deg": 120.0})
    asyncio.run(worker.refresh_config())
    assert asyncio.run(worker.process(_frame(), {})).status == "CALIBRATION_REQUIRED"


def test_relearn_counter_resets_the_detector_once_per_change(make_worker):
    detector = _Detector()
    worker, _ = make_worker(configs=[CONFIG, {**CONFIG, "relearn_seq": 1}, {**CONFIG, "relearn_seq": 1}],
                        detector=detector)
    for seq in (1, 2, 3):
        asyncio.run(worker.refresh_config())
        asyncio.run(worker.process(_frame(seq=seq, captured_at=99.75 + seq), {}))
    assert detector.resets == 1


def test_an_operator_relearn_calls_relearn_when_the_detector_keeps_backgrounds(make_worker):
    """D-539: the operator relearn is the empty-track statement the detector may keep."""
    class _Keeping(_Detector):
        relearns = 0

        def relearn(self):
            self.relearns += 1

    detector = _Keeping()
    worker, _ = make_worker(configs=[CONFIG, {**CONFIG, "relearn_seq": 1}], detector=detector)
    for seq in (1, 2):
        asyncio.run(worker.refresh_config())
        asyncio.run(worker.process(_frame(seq=seq, captured_at=99.75 + seq), {}))
    assert (detector.relearns, detector.resets) == (1, 0)


def test_a_lower_relearn_counter_is_a_new_baseline_not_a_relearn(make_worker):
    """A Fleet restart starts the counter at 0 again; only an increase asks for a relearn."""
    detector = _Detector()
    worker, _ = make_worker(configs=[{**CONFIG, "relearn_seq": value} for value in (3, 0, 1)],
                            detector=detector)
    for seq in (1, 2, 3):
        asyncio.run(worker.refresh_config())
        asyncio.run(worker.process(_frame(seq=seq, captured_at=99.75 + seq), {}))
    assert detector.resets == 1


def test_a_failed_reset_is_tried_again_on_the_next_frame(make_worker):
    class _FailOnce(_Detector):
        def reset(self):
            super().reset()
            if self.resets == 1:
                raise RuntimeError("reset failed")

    detector = _FailOnce()
    worker, _ = make_worker(configs=[CONFIG, {**CONFIG, "relearn_seq": 1}, {**CONFIG, "relearn_seq": 1}],
                            detector=detector)
    asyncio.run(worker.refresh_config())
    asyncio.run(worker.process(_frame(seq=1), {}))
    asyncio.run(worker.refresh_config())
    with pytest.raises(RuntimeError):
        asyncio.run(worker.process(_frame(seq=2, captured_at=100.0), {}))
    asyncio.run(worker.refresh_config())
    asyncio.run(worker.process(_frame(seq=3, captured_at=100.5), {}))
    assert detector.resets == 2


def test_sequence_counts_up_per_published_frame(make_worker):
    worker, client = make_worker()
    for seq in (5, 1, 9):
        asyncio.run(worker.process(_frame(seq=seq), {}))
    assert [payload.seq for payload in client.published] == [0, 1, 2]


def test_a_rejected_publish_is_logged_not_raised(make_worker, caplog):
    worker, _ = make_worker(error=TrackPublishError(409, "CALIBRATION_MISMATCH", "no"))
    with caplog.at_level(logging.WARNING, logger="rosy_vision.track"):
        payload = asyncio.run(worker.process(_frame(), {}))
    assert payload.status == "CALIBRATION_REQUIRED"
    assert "CALIBRATION_MISMATCH" in caplog.text


def test_repeated_rejections_are_logged_on_change_and_then_every_30_s(make_worker, caplog):
    now = [0.0]
    worker, client = make_worker(error=TrackPublishError(409, "DETECTION_STALE", "old"),
                                 clock=lambda: now[0])

    def step(at, seq):
        now[0] = at
        asyncio.run(worker.process(_frame(seq=seq, captured_at=99.75 + seq), {}))

    with caplog.at_level(logging.WARNING, logger="rosy_vision.track"):
        for seq, at in enumerate((0.0, 1.0, 29.0), 1):
            step(at, seq)
        assert len(caplog.records) == 1
        step(31.0, 4)
        assert len(caplog.records) == 2 and "still failing" in caplog.records[1].getMessage()
        client.error = TrackPublishError(409, "DETECTION_OUT_OF_ORDER", "order")
        step(32.0, 5)
        assert len(caplog.records) == 3 and "DETECTION_OUT_OF_ORDER" in caplog.records[2].getMessage()
        client.error = None
        step(33.0, 6)
        client.error = TrackPublishError(409, "DETECTION_OUT_OF_ORDER", "order")
        step(34.0, 7)
    assert len(caplog.records) == 4


def test_repeated_config_failures_are_logged_once(make_worker, caplog):
    worker, client = make_worker(clock=lambda: 5.0)

    async def broken():
        raise TrackPublishError(503, "CONFIG_HTTP_ERROR", "down")

    client.fetch_config = broken
    with caplog.at_level(logging.WARNING, logger="rosy_vision.track"):
        for _ in range(3):
            asyncio.run(worker.refresh_config())
    assert len(caplog.records) == 1 and "CONFIG_HTTP_ERROR" in caplog.text


def test_config_read_failure_keeps_the_last_good_config(make_worker):
    worker, client = make_worker(configs=[CONFIG])
    asyncio.run(worker.refresh_config())

    async def broken():
        raise TrackPublishError(503, "CONFIG_HTTP_ERROR", "down")

    client.fetch_config = broken
    asyncio.run(worker.refresh_config())
    assert worker.config == CONFIG


def test_an_undecodable_frame_publishes_nothing(make_worker):
    worker, client = make_worker(configs=[CONFIG])
    asyncio.run(worker.refresh_config())
    assert asyncio.run(worker.process(_frame(jpeg=b"not a jpeg"), {})) is None
    assert client.published == []


def test_detection_runs_off_the_event_loop_on_one_thread(make_worker):
    """2026-10-01 starvation lesson: the event loop keeps turning while the detector works."""

    class _Slow(_Detector):
        def detect(self, frame, calib):
            time.sleep(0.3)
            return super().detect(frame, calib)

    detector = _Slow()
    worker, _ = make_worker(configs=[CONFIG, {**CONFIG, "relearn_seq": 1}], detector=detector)

    async def scenario():
        ticks = 0
        for seq in (1, 2):
            await worker.refresh_config()
            task = asyncio.create_task(worker.process(_frame(seq=seq, captured_at=99.75 + seq), {}))
            while not task.done():
                ticks += 1
                await asyncio.sleep(0.01)
            assert (await task).status == "OK"
        return ticks

    assert asyncio.run(scenario()) >= 20
    assert detector.resets == 1 and len(detector.threads) == 1
    assert threading.get_ident() not in detector.threads


def test_a_frame_arriving_while_the_detector_is_busy_is_skipped(make_worker):
    gate = threading.Event()

    started = threading.Event()

    class _Blocking(_Detector):
        def detect(self, frame, calib):
            started.set()
            gate.wait(2.0)
            return super().detect(frame, calib)

    detector = _Blocking()
    worker, client = make_worker(configs=[CONFIG], detector=detector)

    async def scenario():
        await worker.refresh_config()
        first = asyncio.create_task(worker.process(_frame(seq=1), {}))
        assert await asyncio.to_thread(started.wait, 2.0)
        second = await worker.process(_frame(seq=2, captured_at=100.0), {})
        gate.set()
        return second, await first

    second, first = asyncio.run(scenario())
    assert second is None and first.status == "OK"
    assert len(detector.calls) == 1 and [p.seq for p in client.published] == [0]


def test_vision_worker_hands_each_fresh_frame_and_its_markers_to_the_tracker():
    calls = []

    class _Tracker:
        async def process(self, frame, markers, *_):
            calls.append((frame.header.seq, sorted(markers)))

    class _Publisher:
        async def publish(self, sighting):
            return {"seq": sighting.seq}

    worker = VisionWorker(source_id="ceiling_north", ingest=_Ingest(frame=_frame()), camera=CAMERA,
                          publisher=_Publisher(), detector=lambda _jpeg: MARKERS,
                          clock=lambda: 100.0, tracker=_Tracker())
    asyncio.run(worker.process_latest())
    asyncio.run(worker.process_latest())
    assert calls == [(1, [7, 30, 31, 32, 33])]


def test_a_rejected_sighting_does_not_skip_tracking():
    calls = []

    class _Tracker:
        async def process(self, frame, markers, *_):
            calls.append(frame.header.seq)

    class _Publisher:
        async def publish(self, sighting):
            raise RuntimeError("sighting rejected")

    worker = VisionWorker(source_id="ceiling_north", ingest=_Ingest(frame=_frame()), camera=CAMERA,
                          publisher=_Publisher(), detector=lambda _jpeg: MARKERS,
                          clock=lambda: 100.0, tracker=_Tracker())
    with pytest.raises(RuntimeError):
        asyncio.run(worker.process_latest())
    assert calls == [1]


def test_a_tracker_error_is_logged_and_does_not_mask_the_sighting_error(caplog):
    class _Tracker:
        async def process(self, frame, markers, *_):
            raise ValueError("tracker broke")

    class _Publisher:
        def __init__(self, error):
            self.error = error

        async def publish(self, sighting):
            if self.error is not None:
                raise self.error
            return {"seq": sighting.seq}

    def vision(error):
        return VisionWorker(source_id="ceiling_north", ingest=_Ingest(frame=_frame()), camera=CAMERA,
                            publisher=_Publisher(error), detector=lambda _jpeg: MARKERS,
                            clock=lambda: 100.0, tracker=_Tracker())

    with caplog.at_level(logging.ERROR, logger="rosy_vision"):
        with pytest.raises(RuntimeError, match="sighting rejected"):
            asyncio.run(vision(RuntimeError("sighting rejected")).process_latest())
        assert len(asyncio.run(vision(None).process_latest())) == 1
    assert caplog.text.count("error_type=ValueError") == 2
    assert "tracker broke" not in caplog.text


def test_an_identity_challenge_is_answered_once_after_its_window_with_numbers_only(make_worker):
    # D-472: grey frames, no blink -> ambiguous "none"; one verdict per request id, no image.
    challenge = {"request_id": "req-1", "color": "blue", "not_before": 100.0, "not_after": 104.0}
    worker, client = make_worker(configs=[{**CONFIG, "identity_challenge": challenge}])
    asyncio.run(worker.refresh_config())
    for i in range(16):
        asyncio.run(worker.process(_frame(seq=i, captured_at=100.0 + i * 0.3), {}))
    (body,) = client.identity
    assert (body["request_id"], body["state"], body["reason"]) == ("req-1", "ambiguous", "none")
    assert body["evidence"]["frames"] == 14 and body["source_id"] == "ceiling_north"
    assert not any(isinstance(v, (bytes, bytearray)) for v in body.values())
    asyncio.run(worker.process(_frame(seq=17, captured_at=105.0), {}))
    assert len(client.identity) == 1


def test_frames_before_the_challenge_arrives_still_fill_the_window(make_worker):
    # Site 2026-10-09: the challenge reaches vision on the 2 s config read, after its window opened.
    # Sampling only from then left the head of the window empty -> every verdict frames_missing.
    challenge = {"request_id": "req-2", "color": "blue", "not_before": 100.0, "not_after": 104.0}
    worker, client = make_worker(configs=[CONFIG, {**CONFIG, "identity_challenge": challenge}])
    asyncio.run(worker.refresh_config())                      # no challenge yet
    for i in range(8):                                        # 100.0 .. 102.1 s, before vision knows
        asyncio.run(worker.process(_frame(seq=i, captured_at=100.0 + i * 0.3), {}))
    asyncio.run(worker.refresh_config())                      # the challenge arrives late
    for i in range(8, 16):
        asyncio.run(worker.process(_frame(seq=i, captured_at=100.0 + i * 0.3), {}))
    (body,) = client.identity
    assert body["reason"] != "frames_missing" and body["evidence"]["frames"] == 14


def test_fleet_robot_regions_reach_the_detector_and_unknown_floor_rides_the_payload(make_worker):
    """D-600: ``occupied`` is handed over before the step; ``unknown_floor`` goes out with OK only."""
    class _Masking(_Detector):
        unknown_floor = ((1.2, 0.4, 0.12),)

        def set_occupied(self, regions):
            self.regions = regions

    detector = _Masking()
    worker, client = make_worker(configs=[{**CONFIG, "occupied": [{"x": 1.0, "y": 0.5, "radius_m": 0.12}]}],
                                 detector=detector)
    asyncio.run(worker.refresh_config())
    asyncio.run(worker.process(_frame(), MARKERS))
    assert detector.regions == [{"x": 1.0, "y": 0.5, "radius_m": 0.12}]
    sent = client.published[-1].model_dump(mode="json")
    assert sent["unknown_floor"] == [{"x": 1.2, "y": 0.4, "radius_m": 0.12}]
    learning = build_payload(source_id="ceiling_north", map_id="map_v2_fleet", calibration_revision="r",
                             processor_revision="background-blob/1", captured_at=1.0, seq=0,
                             result=DetectorResult((), "LEARNING"), unknown_floor=((1.0, 1.0, 0.1),))
    assert "unknown_floor" not in learning.model_dump(mode="json")


class _HoldingDetector(_Detector):
    def __init__(self):
        super().__init__()
        self.holds = []

    def hold(self, until):
        self.holds.append(until)


def test_two_parallel_challenges_are_each_answered_and_hold_the_background(make_worker):
    # D-596: identity_challenges carries one open request per colour; the detector is held through both.
    blue = {"request_id": "req-b", "color": "blue", "not_before": 100.0, "not_after": 104.0}
    amber = {"request_id": "req-a", "color": "amber", "not_before": 101.0, "not_after": 105.0}
    detector = _HoldingDetector()
    worker, client = make_worker(configs=[{**CONFIG, "identity_challenge": blue,
                                           "identity_challenges": [blue, amber, blue]}], detector=detector)
    asyncio.run(worker.refresh_config())
    for i in range(20):
        asyncio.run(worker.process(_frame(seq=i, captured_at=100.0 + i * 0.3), {}))
    assert sorted(body["request_id"] for body in client.identity) == ["req-a", "req-b"]
    assert set(detector.holds) == {105.0}
    assert all(body["processor_revision"] == "led-identity/2" for body in client.identity)
