import io
import json
import math
import shutil
import subprocess
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


@pytest.mark.parametrize('fps', [None, 1, 10, 60])
def test_native_recording_uses_validated_frame_rate(tmp_path, monkeypatch, fps):
    import native_recording
    commands = []
    process = SimpleNamespace(stdin=io.BytesIO(), wait=lambda timeout: 1)
    def popen(command, **kwargs):
        commands.append(command)
        return process
    monkeypatch.setattr(native_recording.subprocess, 'Popen', popen)
    recorder = native_recording.NativeRecorder(tmp_path / 'rate.mp4', **({} if fps is None else {'fps': fps}))
    command = commands[0]
    assert command[command.index('-framerate') + 1] == str(25 if fps is None else fps)
    assert '-maxrate' not in command and '-bufsize' not in command
    assert command[command.index('-crf') + 1] == '20'
    assert command[command.index('-preset') + 1] == 'ultrafast'
    with pytest.raises(RuntimeError, match='encoder'):
        recorder.close()


@pytest.mark.parametrize('fps', [0, -1, 61, True, 10., float('inf'), float('nan'), '10'])
def test_native_recording_rejects_bad_fps_before_opening_files(tmp_path, fps):
    import native_recording
    with pytest.raises(ValueError, match='fps'):
        native_recording.NativeRecorder(tmp_path / 'rate.mp4', fps=fps)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('rate', [0, -1, True, 320., float('nan'), '320'])
def test_native_recording_rejects_bad_max_bitrate_before_opening_files(tmp_path, rate):
    import native_recording
    with pytest.raises(ValueError, match='bitrate'):
        native_recording.NativeRecorder(tmp_path / 'rate.mp4', max_bitrate_kbps=rate)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg tools unavailable')
def test_capped_native_encoder_preserves_frames_and_long_run_byte_budget(tmp_path):
    import native_recording
    path = tmp_path / 'bounded.mp4'
    fps, frames, rate = 10, 120, 220
    recorder = native_recording.NativeRecorder(path, width=800, height=600, fps=fps, max_bitrate_kbps=rate)
    rng = np.random.default_rng(17)
    try:
        for i in range(frames):
            pixels = rng.integers(0, 256, (600, 800, 4), dtype=np.uint8)
            pixels[:, :, 3] = 255
            recorder.write(pixels,
                render_frame=dict(referenceTimeNumerator=i+1, referenceTimeDenominator=fps),
                render_time=(i+1)/fps, sim_s=i/fps, pose=[0.] * 5)
    finally:
        recorder.close()
    # The one-second VBV burst and mux allowance leave room below the registered 64 MiB cap.
    # Nine gapped containers need about 1,750 s of SDK time; the 2,310 s budget still fits 64 MiB.
    assert rate * 1000 * (2310+1) / 8 + 64*1024 < 64*1024*1024
    assert path.stat().st_size <= rate * 1000 * (frames/fps+1) / 8 + 64*1024
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
        '-show_entries', 'stream=codec_name,width,height,avg_frame_rate,nb_read_frames',
        '-of', 'json', str(path)], check=True, capture_output=True, timeout=60)
    stream = json.loads(probe.stdout)['streams'][0]
    assert (stream['codec_name'], stream['width'], stream['height']) == ('h264', 800, 600)
    assert stream['avg_frame_rate'] == '10/1' and int(stream['nb_read_frames']) == frames
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'],
        check=True, capture_output=True, timeout=60)
    receipts = [json.loads(line) for line in path.with_suffix('.frames.jsonl').read_text().splitlines()]
    assert len(receipts) == frames
    assert receipts[-1]['sim_s'] == (frames-1)/fps
