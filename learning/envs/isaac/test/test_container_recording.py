"""Recording admission needs frame chronology as well as a decodable MP4."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import container_recording as recording
from mapped_stack_fixture import container_fixture


def evidence(tmp_path, monkeypatch, change=None):
    rows = [dict(video_frame=i, render_frame=dict(referenceTimeNumerator=i+1, referenceTimeDenominator=1),
        render_time=float(i+1), sim_s=i/10, pose=[0.]*5) for i in range(3)]
    if change:
        rows[1].update(change)
    (tmp_path/'mapped-video.mp4').write_bytes(b'video')
    (tmp_path/'mapped-video.frames.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    (tmp_path/'mapped-video.encoder.log').write_bytes(b'')
    items = []
    for ident, name, media in [('mapped-video','mapped-video.mp4','video/mp4'),
        ('mapped-video-frames','mapped-video.frames.jsonl','application/octet-stream'),
        ('mapped-video-encoder','mapped-video.encoder.log','text/plain')]:
        raw = (tmp_path/name).read_bytes()
        items.append(dict(id=ident,name=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),media_type=media))
    stream = dict(codec_name='h264',width=800,height=600,avg_frame_rate='10/1',nb_frames='3')
    monkeypatch.setattr(recording.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps({'streams':[stream]}).encode()))
    return dict(file='mapped-video.mp4',fps=10,frames=3,last_tick=24,artifacts=items)


def test_video_requires_complete_verified_bytes_and_physics_coverage(tmp_path,monkeypatch):
    fixture=container_fixture(layers=1,case='nominal')
    video=evidence(tmp_path,monkeypatch)
    assert recording.verify_video(tmp_path,video,fixture) == video
    video['last_tick']=12
    with pytest.raises(ValueError,match='cover'):
        recording.verify_video(tmp_path,video,fixture)


@pytest.mark.parametrize('change',[dict(render_time=float('nan')),
    dict(render_frame=dict(referenceTimeNumerator=1,referenceTimeDenominator=1)),dict(pose=[float('inf')]*5)])
def test_forged_or_nonfinite_renderer_receipts_are_rejected(tmp_path,monkeypatch,change):
    video=evidence(tmp_path,monkeypatch,change)
    with pytest.raises(ValueError,match='receipt'):
        recording.verify_video(tmp_path,video,container_fixture(layers=1,case='nominal'))


def test_recording_reads_native_render_product_even_when_camera_cache_is_initial(tmp_path, monkeypatch):
    import numpy as np
    sys.path.insert(0, str(recording.ROOT/'tools/sim/isaac'))
    import native_recording
    seen=[]
    options=[]
    def recorder(*args, **kwargs):
        options.append(kwargs)
        return SimpleNamespace(frames=0, write=lambda rgba, **values: seen.append(values))
    monkeypatch.setattr(native_recording, 'NativeRecorder', recorder)
    camera=SimpleNamespace(get_rgba=lambda:np.zeros((600,800,4),dtype=np.uint8),
        get_current_frame=lambda:dict(rendering_frame=0,rendering_time=0))
    calls=[]
    stamps=iter([123,123,123,124])
    def reference():
        calls.append('sync-reference')
        return dict(referenceTimeNumerator=next(stamps),referenceTimeDenominator=10)
    value=recording.ContainerRecording(tmp_path,SimpleNamespace(current_time=0.,render=lambda:calls.append('render')),camera,
        container_fixture(layers=1,case='nominal')['recording'],reference)
    assert options == [dict(width=800, height=600, fps=10, max_bitrate_kbps=220)]
    value.write(0,[0.]*5)
    value.write(12,[0.]*5)
    assert calls == ['render','sync-reference']*4
    assert seen[0]['render_frame']['referenceTimeNumerator'] == 123
    assert seen[1]['render_frame']['referenceTimeNumerator'] == 124
    assert seen[0]['render_time'] == 12.3
    assert seen[0]['sim_s'] == 0.
    value.reference=lambda:dict(referenceTimeNumerator=124,referenceTimeDenominator=10)
    with pytest.raises(ValueError,match='capture budget'):
        value.write(24,[0.]*5)
