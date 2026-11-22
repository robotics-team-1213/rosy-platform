from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

from core_common.observation_snapshot import SnapshotChannel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "robot" / "omx"))
sys.path.insert(0, str(ROOT / "operations" / "overhead"))
from workcell_observation_bridge import SourceWorker
from workcell_observation_sources import NativeSource


def test_camera_snapshot_read_count_is_per_camera_for_shared_destinations():
    clock = SimpleNamespace(value=0.0)
    reads = []

    def read():
        reads.append(clock.value)
        return {"kind": "jpeg", "payload": b"jpeg", "captured_at": 100 + clock.value,
                "monotonic": 10 + clock.value}

    def make_source():
        source = NativeSource("/test/camera")
        source.channel = SimpleNamespace(read=read)
        source.wall = lambda: 100 + clock.value
        source.monotonic = lambda: 10 + clock.value
        return source

    destinations, ticks = 4, 10
    individual = [make_source() for _ in range(destinations)]
    for tick in range(ticks):
        clock.value = tick / 25
        assert all(source.latest().sequence == tick + 1 for source in individual)
    assert len(reads) == ticks * destinations

    reads.clear()
    shared = make_source()
    for tick in range(ticks):
        clock.value = tick / 25
        samples = [shared.latest() for _ in range(destinations)]
        assert all(sample.sequence == tick + 1 for sample in samples)
        assert all(sample.value is samples[0].value for sample in samples)
    assert len(reads) == ticks
    clock.value += 2.001
    shared.channel = SimpleNamespace(read=lambda: None)
    assert shared.latest() is None


def test_stalled_camera_destination_does_not_hold_new_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OBSERVATION_DIR", str(tmp_path))
    channel = SnapshotChannel("/test/camera")
    source = NativeSource("/test/camera")
    stop, stalled, release, recovered = [threading.Event() for _ in range(4)]
    frames = (b"one", b"two", b"three")
    seen = {jpeg: threading.Event() for jpeg in frames}
    received = []

    def send_slow(sample):
        received.append(sample.value[0])
        if len(received) == 1:
            stalled.set()
            if release.wait(3):
                raise OSError("destination stalled")
        recovered.set()

    def send_fast(sample):
        seen[sample.value[0]].set()

    workers = [SourceWorker(source, send) for send in (send_slow, send_fast)]
    threads = [threading.Thread(target=worker.run, args=(stop,), daemon=True) for worker in workers]
    for thread in threads:
        thread.start()
    try:
        channel.write("jpeg", frames[0], captured_at=time.time())
        assert stalled.wait(2)
        assert seen[frames[0]].wait(2)
        for jpeg in frames[1:]:
            channel.write("jpeg", jpeg, captured_at=time.time())
            assert seen[jpeg].wait(2)
        assert received == [frames[0]]
        release.set()
        assert recovered.wait(2)
        assert received == [frames[0], frames[-1]]
    finally:
        stop.set()
        release.set()
        for thread in threads:
            thread.join(timeout=3)
    assert not any(thread.is_alive() for thread in threads)
