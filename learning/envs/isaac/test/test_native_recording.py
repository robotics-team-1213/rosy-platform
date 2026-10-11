import io
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tools/sim/isaac'))
from map_task import QPolicy


def test_frozen_policy_round_trip_and_evaluation_never_updates():
    p = QPolicy(seed=17)
    p.update((2, 1), 3, 2., (2, 1), terminated=True)
    data = json.loads(json.dumps(p.export()))
    assert hasattr(QPolicy, 'restore'), 'frozen policy evaluation must validate saved Q data'
    q = QPolicy.restore(data)
    assert q.choose((2, 1), explore=False) == 3
    assert q.export() == p.export()


@pytest.mark.parametrize('change', [dict(updates=0), dict(updates=True), dict(gains=[1]),
    dict(q={'7,0': [1., 0., 0., 0.]}), dict(q={'0,0': [math.nan, 0., 0., 0.]}),
    dict(q={'0,0': [True, 0., 0., 0.]}), dict(q={'0,0': [0., 0., 0., 0.]})])
def test_saved_policy_refuses_untrained_or_invalid_data(change):
    assert hasattr(QPolicy, 'restore'), 'saved policy validation is missing'
    p = QPolicy(seed=17)
    p.update((2, 1), 3, 2., (2, 1), terminated=True)
    data = {**json.loads(json.dumps(p.export())), **change}
    with pytest.raises(ValueError):
        QPolicy.restore(data)


def test_native_frames_are_tied_to_renderer_and_encoder_failure_is_not_success(tmp_path, monkeypatch):
    import importlib.util
    assert importlib.util.find_spec('native_recording'), 'native frame recording is missing'
    import native_recording
    process = SimpleNamespace(stdin=io.BytesIO(), wait=lambda timeout: 1)
    monkeypatch.setattr(native_recording.subprocess, 'Popen', lambda *args, **kwargs: process)
    recorder = native_recording.NativeRecorder(tmp_path / 'test.mp4', width=2, height=2)
    pixels = np.arange(16, dtype=np.uint8).reshape(2, 2, 4)
    frame = dict(referenceTimeNumerator=4, referenceTimeDenominator=1)
    recorder.write(pixels, render_frame=frame, render_time=1., sim_s=0., pose=[0.] * 5)
    with pytest.raises(ValueError, match='fresh'):
        recorder.write(pixels, render_frame=frame, render_time=1., sim_s=.2, pose=[0.] * 5)
    with pytest.raises(ValueError, match='frame'):
        recorder.write(pixels[:1], render_frame=frame, render_time=1.2, sim_s=.2, pose=[0.] * 5)
    with pytest.raises(RuntimeError, match='encoder'):
        recorder.close()
    receipt = json.loads((tmp_path / 'test.frames.jsonl').read_text().splitlines()[0])
    assert receipt['render_frame'] == frame and receipt['sim_s'] == 0.
    assert receipt['pose'] == [0.] * 5


def test_encoder_is_reaped_even_when_pipe_close_raises(tmp_path, monkeypatch):
    import native_recording
    waited = []
    class Pipe:
        def close(self):
            raise BrokenPipeError('encoder stopped')
    process = SimpleNamespace(stdin=Pipe(), wait=lambda timeout: waited.append(timeout) or 1)
    monkeypatch.setattr(native_recording.subprocess, 'Popen', lambda *args, **kwargs: process)
    recorder = native_recording.NativeRecorder(tmp_path / 'failed.mp4')
    with pytest.raises(RuntimeError, match='encoder'):
        recorder.close()
    assert waited == [60]
    assert recorder.receipts.closed and recorder.errors.closed
