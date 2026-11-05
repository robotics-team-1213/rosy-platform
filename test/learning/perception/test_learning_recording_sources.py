"""Only registered causal samples enter the observer; previews confer no readiness."""
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from learning_recording_sources import Sources, read


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def source(tmp_path):
    root = tmp_path/'camera'; root.mkdir()
    desc = dict(kind='camera', source_identity='wrist-device', session_epoch='epoch', clock_domain='clock')
    put(root/'descriptor.json', desc)
    return root, desc, Sources([dict(id='camera-a', kind='camera', label='wrist', root=str(root))])


def event(root, desc, index, image=b'jpeg'):
    value = dict(desc, sequence=index, timestamp=time.monotonic(), jpeg_sha256=hashlib.sha256(image).hexdigest())
    put(root/f'events/{index}.json', value)
    (root/f'events/{index}.jpg').write_bytes(image)
    put(root/'latest.json', value)
    return value


def test_preview_without_provenance_is_not_a_recording_source(tmp_path):
    root, desc, sources = source(tmp_path)
    (root/'preview.jpg').write_bytes(b'preview')
    assert sources.snapshot()[0]['status'] == 'preview_only'
    event(root, desc, 0)
    assert sources.snapshot()[0]['status'] == 'ready'
    put(root/'descriptor.json', dict(desc, session_epoch='restarted'))
    assert sources.snapshot()[0]['status'] == 'preview_only'


def test_sequence_spool_preserves_identical_images_and_rejects_gaps_or_epoch_changes(tmp_path):
    root, desc, sources = source(tmp_path)
    chosen = {'camera-a': ('cameras', 'arm_a_wrist', desc)}
    seen, cursors = [], {}
    recorder = SimpleNamespace(push_camera=lambda sample, data, **kw: seen.append((sample, data)))
    event(root, desc, 0)
    sources.poll(chosen, cursors, recorder)
    sources.poll(chosen, cursors, recorder)
    assert len(seen) == 1
    event(root, desc, 1)
    sources.poll(chosen, cursors, recorder)
    assert len(seen) == 2 and seen[0][1] == seen[1][1]
    assert seen[1][0]['camera_id'] == 'arm_a_wrist'
    event(root, desc, 3)
    with pytest.raises((ValueError, OSError)):
        sources.poll(chosen, cursors, recorder)
    put(root/'descriptor.json', dict(desc, session_epoch='restarted'))
    with pytest.raises(ValueError, match='변경'):
        sources.poll(chosen, cursors, recorder)


def test_bound_source_reads_reject_parent_paths_and_missing_directories(tmp_path):
    with pytest.raises(ValueError):
        read(tmp_path, '../outside')
    with pytest.raises(ValueError):
        Sources([dict(id='wrist', kind='camera', label='wrist', root=str(tmp_path/'missing'))])


def test_local_registry_add_remove_and_replacement_need_no_app_restart(tmp_path):
    registry=tmp_path/'registry';registry.mkdir()
    sources=Sources([],registry=registry)
    assert sources.snapshot()==[]
    root=registry/'wrist'
    put(root/'registration.json',dict(kind='camera',label='wrist'))
    desc=dict(kind='camera',source_identity='device-one',session_epoch='one',clock_domain='clock')
    put(root/'descriptor.json',desc);event(root,desc,0)
    first=sources.snapshot()[0]
    assert first['id']=='wrist' and first['source_identity']=='device-one'
    chosen={'wrist':('cameras','arm_a_wrist',desc)}
    new=dict(desc,source_identity='device-two',session_epoch='two')
    put(root/'descriptor.json',new);event(root,new,0)
    assert sources.snapshot()[0]['source_identity']=='device-two'
    with pytest.raises(ValueError,match='변경'):
        sources.poll(chosen,{},SimpleNamespace())
    (root/'registration.json').unlink()
    assert sources.snapshot()==[]
