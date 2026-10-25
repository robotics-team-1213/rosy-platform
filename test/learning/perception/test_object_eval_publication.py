"""D-682 publication bindings; mocked proof is not physical MCAP acceptance."""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

import review_eval_bootstrap as bootstrap
import review_evidence as evidence
from review_app import ReviewStore
from store import Store, read_fixed_manifest


def fixture(tmp_path, monkeypatch, *, complete=True, boxes=None):
    (tmp_path / 'scratch').mkdir()
    images = tmp_path / 'images'
    images.mkdir()
    raw = cv2.imencode('.png', np.zeros((24, 32, 3), np.uint8))[1].tobytes()
    (images / '0.png').write_bytes(raw)
    session = tmp_path / 'eval-session'
    session.mkdir()
    selected = dict(bag='bag_0.mcap', topic='/camera/front', log_ns=1000,
                    channel_id=1, message_ordinal=0, header_stamp_ns=1000,
                    width=32, height=24, image_sha256=evidence.sha(raw), decoded_pixels_sha256='a' * 64)
    mcap = dict(session_dir=str(session), metadata_sha256='b' * 64,
                bags=[dict(name='bag_0.mcap', sha256='c' * 64)], frame=selected,
                decoder=dict(mcap='fixture', mcap_ros2='fixture', opencv='fixture'))
    source = dict(index=0, image='0.png', image_sha256=evidence.sha(raw), width=32, height=24,
                  objects=[], source_kind='mcap', source_session=session.name,
                  capture_group='eval-group', fixed_eval_overlap=True, mcap=mcap)
    human = dict(index=0, image_sha256=evidence.sha(raw), review_status='approved',
                 complete_frame_review=complete,
                 boxes=boxes if boxes is not None else [dict(label='person', bbox_xyxy=[0, 0, 10, 10], occluded=True)])
    source_path, human_path = tmp_path / 'source.jsonl', tmp_path / 'human.jsonl'
    source_path.write_bytes(evidence.encoded(source))
    human_path.write_bytes(evidence.encoded(human))
    review = ReviewStore(tmp_path / 'state', source_path, human_path, images)
    with review.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('workspace_kind','evaluation')")
    registry = Store(tmp_path / 'store')
    registry.reserve_eval_source(session.name, 'eval-group')
    calls = []
    def prove(session_dir, selectors, scratch, *, expected):
        assert session_dir == str(session) and expected == mcap
        calls.append(selectors)
        return dict(frames=[selected], decoder=mcap['decoder'])
    monkeypatch.setattr(bootstrap, 'prove_frames', prove)
    return registry, review, calls


def test_object_publication_needs_no_pixel_approval_and_keeps_review_hash(tmp_path, monkeypatch):
    registry, review, calls = fixture(tmp_path, monkeypatch)
    assert evidence.decisions(review)['frames'][0]['mask_decision'] == 'pending'
    result = bootstrap.publish(registry.root, review.state, 'objects', tmp_path / 'scratch', target='objects')
    folder = Path(result['path'])
    manifest = read_fixed_manifest(folder)
    assert manifest['task'] == 'object_det' and manifest['purpose'] == 'eval'
    assert result['training_admission'] is False and len(calls) == 2
    frame = manifest['frames'][0]
    authority = json.loads((folder / 'authority.json').read_bytes())['frames'][0]
    assert evidence.sha(evidence.encoded(frame['review'])) == authority['object_review_sha256']
    assert evidence.sha(evidence.encoded(frame['source'])) == authority['source_sha256']
    assert frame['review']['boxes'][0]['occluded'] is True and frame['split'] == 'eval'
    assert (folder / frame['image']).read_bytes() == review.image(0).read_bytes()
    with pytest.raises(ValueError, match='cannot export training'):
        review.prepare()


def test_explicit_complete_empty_negative_can_publish(tmp_path, monkeypatch):
    registry, review, _ = fixture(tmp_path, monkeypatch, boxes=[])
    result = bootstrap.publish(registry.root, review.state, 'negative', tmp_path / 'scratch', target='objects')
    assert read_fixed_manifest(result['path'])['frames'][0]['review']['boxes'] == []


def test_incomplete_review_refuses_before_source_proof(tmp_path, monkeypatch):
    registry, review, calls = fixture(tmp_path, monkeypatch, complete=False)
    with pytest.raises(ValueError, match='approved.*object|complete.*object'):
        bootstrap.ready(registry.root, review.state, tmp_path / 'scratch', target='objects')
    assert not calls


def test_provisional_model_draft_is_refused_until_a_person_confirms_it(tmp_path, monkeypatch):
    # D-857 §4: a model draft (임시) never reaches evaluation; a person's 「맞음」 makes it 확정.
    registry, review, calls = fixture(tmp_path, monkeypatch)
    boxes = [dict(label='person', bbox_xyxy=[1, 1, 9, 9])]
    with review.connect() as db:
        db.execute('INSERT INTO object_drafts VALUES (?,?,?,?,?)', (0, 'd' * 64, json.dumps(boxes), 'model', 'e' * 64))
    review.update(0, dict(version=review.get(0)['version'], action='apply_object_draft', draft_sha256='d' * 64))
    assert review.get(0)['review']['review_origin'] == 'model_draft_pending_human'
    with pytest.raises(ValueError, match='complete approved object review'):
        bootstrap.ready(registry.root, review.state, tmp_path / 'scratch', target='objects')
    assert not calls
    review.update(0, dict(version=review.get(0)['version'], action='approve', complete_frame_review=True))
    result = bootstrap.publish(registry.root, review.state, 'confirmed', tmp_path / 'scratch', target='objects')
    assert read_fixed_manifest(result['path'])['frames'][0]['review']['boxes'] == boxes


def test_object_publication_preserves_default_pixel_gate(tmp_path, monkeypatch):
    registry, review, _ = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='pixel classes'):
        bootstrap.ready(registry.root, review.state, tmp_path / 'scratch')


def test_missing_reservation_is_refused(tmp_path, monkeypatch):
    registry, review, calls = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(Store, 'eval_reservations', lambda self: {})
    with pytest.raises(ValueError, match='reserved'):
        bootstrap.ready(registry.root, review.state, tmp_path / 'scratch', target='objects')
    assert not calls


def test_review_change_during_proof_refuses_publication(tmp_path, monkeypatch):
    registry, review, _ = fixture(tmp_path, monkeypatch)
    original = bootstrap.prove_frames
    def mutate(*args, **kwargs):
        proof = original(*args, **kwargs)
        frame = review.get(0)
        review.update(0, dict(version=frame['version'], action='save', boxes=frame['review']['boxes']))
        return proof
    monkeypatch.setattr(bootstrap, 'prove_frames', mutate)
    with pytest.raises(ValueError, match='authority changed'):
        bootstrap.publish(registry.root, review.state, 'changed', tmp_path / 'scratch', target='objects')
    assert not list(registry.evalsets_dir.rglob('manifest.json'))


def test_object_publication_is_idempotent_and_class_file_is_sealed(tmp_path, monkeypatch):
    registry, review, _ = fixture(tmp_path, monkeypatch)
    first = bootstrap.publish(registry.root, review.state, 'objects', tmp_path / 'scratch', target='objects')
    second = bootstrap.publish(registry.root, review.state, 'objects', tmp_path / 'scratch', target='objects')
    assert first['content_sha'] == second['content_sha']
    folder = Path(first['path'])
    (folder / 'object-classes.json').write_bytes(b'changed')
    with pytest.raises(ValueError):
        read_fixed_manifest(folder)


@pytest.mark.parametrize('index', [None, True, 1, '0'])
def test_invalid_class_indices_refuse_before_proof(tmp_path, monkeypatch, index):
    import class_sets
    registry, review, calls = fixture(tmp_path, monkeypatch)
    record = class_sets.object_set(review)
    record['classes'][0]['index'] = index
    with review.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('object_class_set',?)", (json.dumps(record),))
    with pytest.raises(ValueError, match='classes'):
        bootstrap.ready(registry.root, review.state, tmp_path / 'scratch', target='objects')
    assert not calls


def test_truncated_source_proof_cannot_publish(tmp_path, monkeypatch):
    registry, review, _ = fixture(tmp_path, monkeypatch)
    original = bootstrap.prove_frames
    def truncate(*args, **kwargs):
        proof = original(*args, **kwargs)
        return dict(proof, frames=[])
    monkeypatch.setattr(bootstrap, 'prove_frames', truncate)
    with pytest.raises(ValueError, match='proof.*count'):
        bootstrap.publish(registry.root, review.state, 'truncated', tmp_path / 'scratch', target='objects')


def test_publication_reproves_actual_synthetic_mcap_bytes(tmp_path, monkeypatch):
    pytest.importorskip('mcap_ros2')
    from mcap_ros2.writer import Writer
    from test_dataset_extract import IMAGE_DEF
    original_prove = bootstrap.prove_frames
    registry, mock_review, _ = fixture(tmp_path, monkeypatch)
    source = mock_review.get(0)['source']
    session = Path(source['mcap']['session_dir'])
    bag = session / 'bag'
    bag.mkdir()
    with (bag / 'bag_0.mcap').open('wb') as stream:
        writer = Writer(stream)
        definition = writer.register_msgdef('sensor_msgs/msg/Image', IMAGE_DEF)
        writer.write_message('/camera/front', definition, {
            'header': {'stamp': {'sec': 0, 'nanosec': 1000}, 'frame_id': 'camera'},
            'height': 24, 'width': 32, 'encoding': 'bgr8', 'is_bigendian': 0,
            'step': 96, 'data': [0] * (24 * 32 * 3)}, 1000, 1000)
        writer.finish()
    (bag / 'metadata.yaml').write_text('rosbag2_bagfile_information:\n  relative_file_paths:\n    - bag_0.mcap\n')
    proof = original_prove(session, [dict(topic='/camera/front', log_ns=1000,
                           image=mock_review.image(0))], tmp_path / 'scratch')
    source['mcap'] = dict(session_dir=str(session), metadata_sha256=proof['metadata_sha256'],
                         bags=proof['bags'], frame=proof['frames'][0], decoder=proof['decoder'])
    source['image'] = '0.png'
    (tmp_path / 'source.jsonl').write_bytes(evidence.encoded(source))
    actual = ReviewStore(tmp_path / 'actual-state', tmp_path / 'source.jsonl',
                        tmp_path / 'human.jsonl', tmp_path / 'images')
    with actual.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('workspace_kind','evaluation')")
    monkeypatch.setattr(bootstrap, 'prove_frames', original_prove)
    result = bootstrap.publish(registry.root, actual.state, 'actual-synthetic',
                               tmp_path / 'scratch', target='objects')
    assert read_fixed_manifest(result['path'])['frames'][0]['source']['mcap']['bags'] == proof['bags']
    with (bag / 'bag_0.mcap').open('ab') as stream:
        stream.write(b'drift')
    with pytest.raises(ValueError, match='bag hash'):
        bootstrap.ready(registry.root, actual.state, tmp_path / 'scratch', target='objects')
