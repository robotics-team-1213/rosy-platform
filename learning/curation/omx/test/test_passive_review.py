"""Saved passive review displays genuine retained observations without changing evidence."""
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys

from PIL import Image
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_passive_recording import rig,sample_inputs
import passive_recording as recording
import passive_recording_io
import passive_review


def episode(root,*,keep=False):
    profile,producers,timing=rig()
    config=recording.preflight(profile,producers,timing,now=10.,clock_domain='host-monotonic')
    recorder=recording.Recorder(root,config)
    for frame,(stamp,sequence) in enumerate([(10.,0),(10.2,2)]):
        arms,cameras=sample_inputs(profile,producers,stamp,sequence)
        for event in arms:
            recorder.push_arm(event,received_at=stamp)
        for event in cameras:
            stream=io.BytesIO()
            Image.new('RGB',(16,16),(180,20,40) if event['camera_id']=='top' else (20,40,180)).save(stream,format='JPEG')
            recorder.push_camera(event,stream.getvalue(),received_at=stamp)
        recorder.start(stamp) if frame==0 else recorder.advance(stamp)
    recorder.stop(10.21)
    if keep:
        recorder.keep()
    return recorder,config


@pytest.mark.parametrize('keep',[False,True])
def test_review_reads_original_vectors_timestamps_and_all_retained_views(tmp_path,keep):
    root=tmp_path/'episode'
    recorder,config=episode(root,keep=keep)
    original={path.relative_to(root).as_posix():path.read_bytes() for path in root.rglob('*') if path.is_file()}
    review=passive_review.Review.build(root,config['profile_revision'])
    try:
        summary=review.summary()
        assert summary['frames']==2 and summary['fps']==5
        assert summary['profile_revision']==config['profile_revision']
        assert len(summary['evidence_revision'])==64 and int(summary['evidence_revision'],16)>=0
        assert summary['checked_at']
        assert summary['scope']=='content_integrity_at_load'
        assert summary['physical_learning_verified'] is False
        assert summary['task_outcome']=='unknown'
        assert [arm['id'] for arm in summary['arms']]==['arm_0','arm_1']
        assert [camera['id'] for camera in summary['cameras']]==['top','wrist']
        assert str(root) not in json.dumps(summary)
        row=review.frame(1)
        assert row['frame_index']==1 and row['grid_time']==10.2
        assert row['state']==[.1,.2,1.1,1.2]
        assert row['action']==[.3,.4,1.3,1.4]
        assert row['arms']['arm_0']['state_timestamp']<row['arms']['arm_0']['reference_timestamp']<=row['arms']['arm_0']['received_at']
        assert row['arms']['arm_0']['joint_names']==['j0','j1']
        assert row['cameras']['wrist']['timestamp_semantics']=='host_receive'
        top=review.image(1,'top')
        wrist=review.image(1,'wrist')
        assert top!=wrist
        assert hashlib.sha256(wrist).hexdigest()==row['cameras']['wrist']['sha256']
        assert wrist==(root/row['cameras']['wrist']['path']).read_bytes()
        assert original=={path.relative_to(root).as_posix():path.read_bytes() for path in root.rglob('*') if path.is_file()}
    finally:
        review.close()
    with pytest.raises(ValueError):
        review.frame(0)


@pytest.mark.parametrize('change',['frames','image','config'])
def test_postbuild_evidence_tampering_is_rejected(tmp_path,change):
    root=tmp_path/'episode'
    _,config=episode(root,keep=True)
    review=passive_review.Review.build(root,config['profile_revision'])
    try:
        row=review.frame(0)
        if change=='image':
            (root/row['cameras']['wrist']['path']).write_bytes(b'changed')
            with pytest.raises(ValueError):
                review.image(0,'wrist')
        else:
            (root/('frames.jsonl' if change=='frames' else 'config.json')).write_bytes(b'changed')
            with pytest.raises(ValueError):
                review.frame(0)
    finally:
        review.close()


def test_invalid_selection_profile_and_unclosed_or_discarded_capture_are_refused(tmp_path):
    root=tmp_path/'episode'
    recorder,config=episode(root)
    with pytest.raises(ValueError):
        passive_review.Review.build(root,'0'*64)
    review=passive_review.Review.build(root,config['profile_revision'])
    try:
        for index in (-1,2,True,'0'):
            with pytest.raises(ValueError):
                review.frame(index)
        for camera in ('preview','missing','../top'):
            with pytest.raises(ValueError):
                review.image(0,camera)
    finally:
        review.close()
    recorder.discard()
    with pytest.raises(ValueError):
        passive_review.Review.build(root,config['profile_revision'])
    recorder.invalidate('explicitly invalid capture')
    with pytest.raises(ValueError):
        passive_review.Review.build(root,config['profile_revision'])
    profile,producers,timing=rig()
    opened=recording.Recorder(tmp_path/'open',recording.preflight(profile,producers,timing,now=10.,clock_domain='host-monotonic'))
    try:
        with pytest.raises(ValueError):
            passive_review.Review.build(tmp_path/'open',config['profile_revision'])
    finally:
        opened.discard()


def test_cancelled_background_index_closes_its_sqlite_connection(tmp_path,monkeypatch):
    root=tmp_path/'episode'
    _,config=episode(root)
    opened=[]
    connect=sqlite3.connect
    def tracked_connect(*args,**kwargs):
        connection=connect(*args,**kwargs)
        opened.append(connection)
        return connection
    monkeypatch.setattr(passive_review.sqlite3,'connect',tracked_connect)
    with pytest.raises(ValueError,match='cancel'):
        passive_review.Review.build(root,config['profile_revision'],
            cancelled=lambda:bool(opened and opened[0].total_changes))
    assert opened
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')


@pytest.mark.parametrize('keep',[False,True])
def test_validation_streams_rows_to_callback_and_preserves_list_api(tmp_path,monkeypatch,keep):
    root=tmp_path/'episode'
    _,config=episode(root,keep=keep)
    rows=[]
    with monkeypatch.context() as changes:
        changes.setattr(passive_recording_io,'frames',lambda *_:pytest.fail('validation materialized all rows'))
        if keep:
            seal=passive_recording_io.verify(root,on_frame=rows.append)
        else:
            passive_recording_io.check_draft(root,on_frame=rows.append)
            seal=dict(recording.read_json(root/'draft.json'),config=config)
    assert [row['frame_index'] for row in rows]==[0,1]
    assert isinstance(recording.frames(root,seal),list)


def test_sqlite_capacity_failure_does_not_modify_raw_evidence(tmp_path,monkeypatch):
    root=tmp_path/'episode'
    _,config=episode(root)
    before=recording.hashes(root)
    monkeypatch.setattr(passive_review,'INDEX_BYTES',4096)
    with pytest.raises(ValueError,match='128 MiB'):
        passive_review.Review.build(root,config['profile_revision'])
    assert recording.hashes(root)==before
