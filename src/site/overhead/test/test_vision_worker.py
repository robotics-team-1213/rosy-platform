import asyncio
from types import SimpleNamespace

from overhead.project import CameraMap
from overhead.worker import VisionWorker


def _camera():
    return CameraMap(
        source_id="ceiling_north", map_id="site-v1", calibration_revision="cal-v3",
        processor_revision="aruco-v1", corner_marker_ids=(30, 31, 32, 33),
        corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)),
        robot_markers={"rosy_01": 7}, heading_edge=(1, 2),
    )


class _Ingest:
    def __init__(self, frame):
        self.frame = frame

    def latest_frame(self, source_id):
        assert source_id == "ceiling_north"
        return self.frame


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
