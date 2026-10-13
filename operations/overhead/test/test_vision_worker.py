import asyncio
from types import SimpleNamespace

from games.field.homography import fit

from rosy_vision.field_calib import FieldCalibrator
from rosy_vision.project import CameraMap
from rosy_vision.worker import VisionWorker

WORLD = ((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0))
FIELD_QUAD = ((100.0, 100.0), (500.0, 100.0), (500.0, 300.0), (100.0, 300.0))
FIELD_SIZE = (640, 480)


def _camera(**overrides):
    args = dict(
        source_id="ceiling_north", map_id="site-v1", calibration_revision="cal-v3",
        processor_revision="aruco-v1", corner_marker_ids=(30, 31, 32, 33),
        corner_world_m=WORLD, robot_markers={"rosy_01": 7}, heading_edge=(1, 2),
    )
    args.update(overrides)
    return CameraMap(**args)


def _field_camera():
    return _camera(corner_marker_ids=None, calibration_source="field_boundary")


def _map_to_image_matrix():
    h = fit(WORLD, FIELD_QUAD).h
    return [list(h[0:3]), list(h[3:6]), list(h[6:9])]


def _field_detection(corners=FIELD_QUAD):
    proposal = SimpleNamespace(corners=corners, confidence=0.9)
    return SimpleNamespace(proposal=proposal, reason="", image_size=FIELD_SIZE)


class _Ingest:
    def __init__(self, frame):
        self.frame = frame
        self.reports = []
        self.field_reports = []

    def latest_frame(self, source_id):
        assert source_id == "ceiling_north"
        return self.frame

    def report_markers(self, source_id, corners_seen, robots_seen):
        self.reports.append((source_id, list(corners_seen), list(robots_seen)))

    def report_field(self, source_id, report):
        self.field_reports.append((source_id, report))


class _Publisher:
    def __init__(self):
        self.sent = []

    async def publish(self, sighting):
        self.sent.append(sighting)
        return {"seq": sighting.seq}


def _markers():
    def quad(cx, cy, half=2):
        return ((cx-half, cy-half), (cx+half, cy-half),
                (cx+half, cy+half), (cx-half, cy+half))
    return {30: quad(100, 100), 31: quad(500, 100), 32: quad(500, 300),
            33: quad(100, 300), 7: quad(300, 200, 10)}


def _frame(seq=1, captured_at=99.75, received_at=100.0):
    return SimpleNamespace(
        header=SimpleNamespace(seq=seq), jpeg=b"frame",
        captured_at=captured_at, received_at=received_at,
    )


def test_worker_processes_each_fresh_latest_frame_once():
    publisher = _Publisher()
    worker = VisionWorker(
        source_id="ceiling_north", ingest=_Ingest(_frame()), camera=_camera(),
        publisher=publisher, detector=lambda _jpeg: _markers(), clock=lambda: 100.0,
    )

    first = asyncio.run(worker.process_latest())
    duplicate = asyncio.run(worker.process_latest())

    assert [row.seq for row in first] == [1]
    assert duplicate == ()
    assert [row.seq for row in publisher.sent] == [1]


def test_worker_does_not_process_stale_or_wrong_source_frames():
    publisher = _Publisher()
    stale = VisionWorker(
        source_id="ceiling_north", ingest=_Ingest(_frame(captured_at=98.0)),
        camera=_camera(), publisher=publisher,
        detector=lambda _jpeg: (_ for _ in ()).throw(AssertionError("stale frame decoded")),
        clock=lambda: 100.0, max_age_s=1.0,
    )
    wrong_source = VisionWorker(
        source_id="other", ingest=_Ingest(_frame()), camera=_camera(),
        publisher=publisher,
    )

    assert asyncio.run(stale.process_latest()) == ()
    assert asyncio.run(wrong_source.process_latest()) == ()
    assert publisher.sent == []


def test_worker_run_loop_stops_after_signal_and_publishes_latest_frame():
    async def run():
        stop = asyncio.Event()

        class StopPublisher(_Publisher):
            async def publish(self, sighting):
                result = await super().publish(sighting)
                stop.set()
                return result

        publisher = StopPublisher()
        worker = VisionWorker(
            source_id="ceiling_north", ingest=_Ingest(_frame()), camera=_camera(),
            publisher=publisher, detector=lambda _jpeg: _markers(), clock=lambda: 100.0,
        )
        await worker.run(stop_event=stop, poll_interval_s=0.01)
        return publisher.sent

    assert [row.seq for row in asyncio.run(run())] == [1]


def test_worker_reports_only_configured_marker_ids_for_installer_status():
    ingest = _Ingest(_frame())
    seen = {k: v for k, v in _markers().items() if k != 32}
    seen[45] = seen[30]  # an unconfigured marker is never reported
    worker = VisionWorker(
        source_id="ceiling_north", ingest=ingest, camera=_camera(),
        publisher=_Publisher(), detector=lambda _jpeg: seen, clock=lambda: 100.0,
    )

    asyncio.run(worker.process_latest())

    assert ingest.reports == [("ceiling_north", [30, 31, 33], ["rosy_01"])]


class _PaintRegistrar:
    """Accepted D-375 registration result as an async callable."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, _jpeg):
        self.calls += 1
        return SimpleNamespace(
            accepted=True, image_size=FIELD_SIZE,
            registration=SimpleNamespace(map_to_image=_map_to_image_matrix()),
        )


def test_field_source_publishes_only_once_orientation_resolves():
    async def run():
        ingest = _Ingest(_frame(seq=1))
        publisher = _Publisher()
        paint = _PaintRegistrar()
        worker = VisionWorker(
            source_id="ceiling_north", ingest=ingest, camera=_field_camera(),
            publisher=publisher, detector=lambda _jpeg: {7: _markers()[7]},
            clock=lambda: 100.0, calibrator=FieldCalibrator(WORLD),
            field_detector=lambda _jpeg: _field_detection(), paint_registrar=paint,
        )
        await worker.process_latest()          # detection feeds the calibrator; no sighting yet
        await worker._paint_task               # the paint registration resolves the orientation
        ingest.frame = _frame(seq=2)
        await worker.process_latest()          # now the cached homography projects the robot
        return publisher.sent, ingest.field_reports, paint.calls

    sent, reports, paint_calls = asyncio.run(run())
    assert [row.seq for row in sent] == [2]
    assert sent[0].calibration_source == "field_boundary"
    assert sent[0].corner_marker_ids is None
    assert 0.0 <= sent[0].x <= 4.0 and 0.0 <= sent[0].y <= 2.0
    assert paint_calls == 1
    assert [report["state"] for _, report in reports][0] == "orientation_pending"
    assert reports[-1][1]["state"] == "calibrated"


def test_field_source_reports_no_corner_markers_and_reuses_the_cached_quad():
    async def run():
        ingest = _Ingest(_frame(seq=1))
        calls = []

        def field_detector(_jpeg):
            calls.append(_jpeg)
            return _field_detection()

        worker = VisionWorker(
            source_id="ceiling_north", ingest=ingest, camera=_field_camera(),
            publisher=_Publisher(), detector=lambda _jpeg: {7: _markers()[7]},
            clock=lambda: 100.0, calibrator=FieldCalibrator(WORLD),
            field_detector=field_detector, field_interval_s=60.0,
        )
        await worker.process_latest()
        ingest.frame = _frame(seq=2)
        await worker.process_latest()
        return ingest, calls

    ingest, calls = asyncio.run(run())
    # Cadence 60 s: the second frame reuses the cached quad without a new detection.
    assert len(calls) == 1
    assert ingest.reports[-1] == ("ceiling_north", [], ["rosy_01"])


def test_field_source_without_detection_publishes_nothing():
    async def run():
        ingest = _Ingest(_frame(seq=1))
        publisher = _Publisher()
        worker = VisionWorker(
            source_id="ceiling_north", ingest=ingest, camera=_field_camera(),
            publisher=publisher, detector=lambda _jpeg: {7: _markers()[7]},
            clock=lambda: 100.0, calibrator=FieldCalibrator(WORLD),
            field_detector=lambda _jpeg: SimpleNamespace(proposal=None, reason="no field",
                                                         image_size=FIELD_SIZE),
        )
        await worker.process_latest()
        return publisher.sent, ingest.field_reports

    sent, reports = asyncio.run(run())
    assert sent == []
    assert reports[-1][1]["state"] == "no_field"
