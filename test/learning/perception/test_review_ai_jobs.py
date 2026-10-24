"""AI execution publishes candidates without overwriting or approving human labels."""
import base64
import hashlib
import json
import sys
import threading
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace

import cv2
import numpy as np
import pytest

from test_review_app import open_store
from test_review_return import fixture_inputs
from test_pixel_draft_import import V13_CLASSES
import class_sets
from review_app import ReviewStore
import review_masks
from review_ai_jobs import Jobs
from vision_review_drafts import CLASSES
from vlm_mask_feedback import read_current_feedback


def workspace(tmp_path):
    source, human, images = fixture_inputs(tmp_path, approved=False)
    binding = class_sets.from_data_yaml(json.dumps({'names': list(CLASSES)}).encode(), 'detect')
    store = ReviewStore(tmp_path / 'state', source, human, images, object_classes=binding)
    review_masks.bind_classes(store, V13_CLASSES)
    human = np.full((24, 32), 255, np.uint8)
    human[:, 0] = 0
    path, digest = review_masks.freeze(store, review_masks.encode(human))
    with store.connect() as db:
        db.execute("INSERT INTO masks(frame,version,status,path,sha256) VALUES (0,1,'pending',?,?)", (path, digest))
    return store


def finished(jobs, frame=0):
    jobs.thread.join(timeout=5)
    assert not jobs.thread.is_alive()
    return jobs.status(frame)['jobs'][0]


def test_missing_configuration_disables_actions(tmp_path):
    store = workspace(tmp_path)
    jobs = Jobs(store)
    try:
        assert not jobs.status(0)['available']
        with pytest.raises(ValueError):
            jobs.create(0, 'object_draft', 1, 'human-a')
    finally:
        jobs.close()


@pytest.mark.parametrize('action', ['pixel_draft', 'mask_check'])
def test_whole_road_semantic_refuses_lane_only_ai_before_execution(tmp_path, action):
    store = workspace(tmp_path)
    binding = review_masks.classes(store)
    next(entry for entry in binding['classes'] if entry['name'] == 'drivable')['semantic'] = 'road_surface/1'
    with store.connect() as db:
        db.execute("UPDATE metadata SET value=? WHERE key='pixel_classes'", (json.dumps(binding),))
    called = []
    jobs = Jobs(store, backend=lambda *_: called.append(True))
    try:
        availability = jobs.status(0)['actions'][action]
        assert not availability['available'] and 'road_surface/1' in availability['reason']
        with pytest.raises(ValueError, match='road_surface/1'):
            jobs.create(0, action, 1, 'human-a')
        assert not called and not jobs.status(0)['jobs']
    finally:
        jobs.close()


def test_object_candidate_and_requester_survive_reopen_without_review_change(tmp_path):
    store = workspace(tmp_path)
    before = store.get(0)
    jobs = Jobs(store, backend=lambda *_: {'boxes': [{'label': 'person', 'bbox_xyxy': [1, 1, 12, 12]}]})
    try:
        jobs.create(0, 'object_draft', 1, 'human-a')
        done = finished(jobs)
        assert done['state'] == 'succeeded'
        assert done['actor'] == 'human-a' and done['model_digest'] == 'test-backend'
        assert done['classes_sha256'] == class_sets.object_set(store)['sha256']
        assert store.get(0) == before
        assert store.object_drafts(0)[0]['sha256'] == done['result']['candidate_sha256']
    finally:
        jobs.close()
    reopened = Jobs(store)
    try:
        assert reopened.status(0)['jobs'][0] == done
    finally:
        reopened.close()


def test_stale_version_does_not_publish(tmp_path):
    store = workspace(tmp_path)
    started, release = threading.Event(), threading.Event()
    def backend(*_):
        started.set(); assert release.wait(5)
        return {'boxes': []}
    jobs = Jobs(store, backend=backend)
    try:
        jobs.create(0, 'object_draft', 1, 'human-a')
        assert started.wait(5)
        with store.lock, store.connect() as db:
            db.execute('UPDATE frames SET version=2 WHERE id=0')
        release.set()
        assert finished(jobs)['state'] == 'stale'
        assert not store.object_drafts(0)
    finally:
        release.set(); jobs.close()


def test_cancel_prevents_publication_and_records_canceller(tmp_path):
    store = workspace(tmp_path)
    started = threading.Event()
    def backend(snapshot, cancel):
        started.set(); assert cancel.wait(5)
        return {'boxes': []}
    jobs = Jobs(store, backend=backend)
    try:
        job = jobs.create(0, 'object_draft', 1, 'human-a')
        assert started.wait(5)
        with pytest.raises(ValueError, match='실행 중'):
            jobs.create(0, 'object_draft', 1, 'human-b')
        jobs.cancel(job['id'], 'human-b')
        done = finished(jobs)
        assert done['state'] == 'cancelled' and done['cancelled_by'] == 'human-b'
        assert not store.object_drafts(0)
    finally:
        jobs.close()


@pytest.mark.parametrize('result', [{'boxes': [{'label': 'invented', 'bbox_xyxy': [1, 1, 12, 12]}]},
                                    {'boxes': [{'label': 'person', 'bbox_xyxy': [1, 1, 999, 999]}]}])
def test_invalid_model_boxes_fail_closed(tmp_path, result):
    store = workspace(tmp_path)
    jobs = Jobs(store, backend=lambda *_: result)
    try:
        jobs.create(0, 'object_draft', 1, 'human-a')
        assert finished(jobs)['state'] == 'failed'
        assert not store.object_drafts(0)
    finally:
        jobs.close()


@pytest.mark.parametrize('changes_human', [False, True])
def test_pixel_draft_preserves_human_pixels_and_never_applies(tmp_path, changes_human):
    store = workspace(tmp_path)
    before = review_masks.get(store, 0)
    human = review_masks.pixels(store, before)
    proposal = human.copy()
    proposal[:, 1] = 0
    if changes_human:
        proposal[:, 0] = 255
    jobs = Jobs(store, backend=lambda *_: {'mask': base64.b64encode(review_masks.encode(proposal)).decode()})
    try:
        jobs.create(0, 'pixel_draft', 1, 'human-a')
        assert finished(jobs)['state'] == ('failed' if changes_human else 'succeeded')
        current = review_masks.get(store, 0)
        assert current['version'] == before['version'] and current['status'] == 'pending'
        assert np.array_equal(review_masks.pixels(store, current), human)
        assert len(current['draft_candidates']) == (0 if changes_human else 1)
    finally:
        jobs.close()


def test_per_frame_feedback_readback_without_approval(tmp_path):
    store = workspace(tmp_path)
    before = review_masks.get(store, 0)
    jobs = Jobs(store, backend=lambda *_: {'feedback': {'verdict': 'concern',
        'issue': 'missed_visible_road', 'note': 'Check visible floor'}})
    try:
        job = jobs.create(0, 'mask_check', 1, 'human-a')
        assert finished(jobs)['state'] == 'succeeded'
        result = read_current_feedback(store.state, 0)
        assert result['current'] and result['requested_by'] == 'human-a' and result['job_id'] == job['id']
        assert result['feedback']['verdict'] == 'concern'
        assert review_masks.get(store, 0) == before
    finally:
        jobs.close()


def test_restart_marks_abandoned_job_terminal(tmp_path):
    store = workspace(tmp_path)
    jobs = Jobs(store)
    with store.connect() as db:
        jobs._write(db, {'id': 'abandoned', 'frame': 0, 'state': 'running'})
    jobs.close()
    reopened = Jobs(store)
    try:
        assert reopened.status(0)['jobs'][0]['state'] == 'failed'
    finally:
        reopened.close()


def test_second_manager_cannot_execute_or_interrupt_first(tmp_path):
    store = workspace(tmp_path)
    first = Jobs(store, backend=lambda *_: {'boxes': []})
    second = Jobs(store, backend=lambda *_: {'boxes': []})
    try:
        assert not second.status(0)['available']
        assert first.status(0)['available']
    finally:
        second.close(); first.close()


def test_nonowning_manager_cannot_cancel_running_owner(tmp_path):
    store = workspace(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def backend(*_):
        entered.set(); assert release.wait(5)
        return {'boxes': []}
    owner = Jobs(store, backend=backend)
    other = Jobs(store, backend=backend)
    try:
        job = owner.create(0, 'object_draft', 1, 'human-a')
        assert entered.wait(5)
        with pytest.raises(ValueError, match='소유권'):
            other.cancel(job['id'], 'human-a')
        assert other.status(0)['jobs'][0]['state'] == 'running'
        release.set()
        assert finished(owner)['state'] == 'succeeded'
    finally:
        release.set(); other.close(); owner.close()


def test_object_class_binding_change_discards_inflight_result(tmp_path):
    store = workspace(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def backend(*_):
        entered.set(); assert release.wait(5)
        return {'boxes': []}
    jobs = Jobs(store, backend=backend)
    try:
        jobs.create(0, 'object_draft', 1, 'human-a')
        assert entered.wait(5)
        with store.lock, store.connect() as db:
            db.execute("UPDATE metadata SET value=? WHERE key='object_class_set'",
                       (json.dumps(class_sets.legacy_object_set()),))
        release.set()
        assert finished(jobs)['state'] == 'stale'
        assert not store.object_drafts(0)
    finally:
        release.set(); jobs.close()


def test_default_six_class_workspace_does_not_reinterpret_model_obstacle(tmp_path):
    store = open_store(tmp_path)
    store.update(0, {'version': 1, 'action': 'reopen'})
    jobs = Jobs(store, backend=lambda *_: {'boxes': []})
    try:
        assert store.object_classes() == tuple(name for name in CLASSES if name != 'obstacle')
        assert not jobs.status(0)['actions']['object_draft']['available']
        with pytest.raises(ValueError):
            jobs.create(0, 'object_draft', store.get(0)['version'], 'human-a')
    finally:
        jobs.close()


def test_worker_checks_model_digest_before_inference(tmp_path, monkeypatch):
    import review_ai_worker
    monkeypatch.setattr(review_ai_worker.feedback, '_get_json', lambda *_: {'models': [
        {'name': review_ai_worker.objects.MODEL, 'digest': 'different'}]})
    with pytest.raises(ValueError, match='digest'):
        review_ai_worker.execute({}, {'model_digest': 'expected'}, tmp_path)


@pytest.mark.parametrize('action', ['object_draft', 'mask_check'])
def test_fixed_worker_adapters_execute_against_pinned_model(tmp_path, monkeypatch, action):
    import review_ai_worker as worker
    store = workspace(tmp_path)
    jobs = Jobs(store, backend=lambda *_: {})
    calls = []
    def request(url, payload=None):
        calls.append(url)
        if url.endswith('/api/tags'):
            return {'models': [{'name': worker.objects.MODEL, 'digest': 'pinned'}]}
        return {'message': {'content': json.dumps({'verdict': 'concern', 'issue': 'uncertain_visibility', 'note': 'Inspect edge'})}}
    monkeypatch.setattr(worker.feedback, '_get_json', request)
    monkeypatch.setattr(worker.objects, 'ask', lambda *args: {'boxes': [
        {'label': 'person', 'bbox_xyxy': [100, 100, 800, 800], 'reason': 'visible'}]})
    try:
        snapshot = jobs._snapshot(0, action, 1)
        result = worker.execute(snapshot, {'model_digest': 'pinned'}, tmp_path)
        if action == 'object_draft':
            assert result['boxes'][0]['label'] == 'person'
        else:
            assert result['feedback']['verdict'] == 'concern'
        assert calls[0] == 'http://127.0.0.1:11434/api/tags'
    finally:
        jobs.close()


def test_fixed_pixel_worker_adapter_preserves_human_pixels_with_sam_stub(tmp_path, monkeypatch):
    import review_ai_worker as worker
    store = workspace(tmp_path)
    jobs = Jobs(store, backend=lambda *_: {})
    checkpoint = tmp_path / 'sam.pt'
    checkpoint.write_bytes(b'pinned fixture checkpoint')
    monkeypatch.setattr(worker.feedback, '_get_json', lambda *_: {'models': [
        {'name': worker.objects.MODEL, 'digest': 'pinned'}]})
    monkeypatch.setattr(worker.completion, 'ask', lambda *_: {'background': [[1, 0]], 'drivable': []})
    monkeypatch.setattr(worker.completion.qwen_points, 'unload', lambda *_: None)
    torch = ModuleType('torch')
    torch.inference_mode = nullcontext
    sam3 = ModuleType('sam3')
    builder = ModuleType('sam3.model_builder')
    built = []
    def build(**kwargs):
        built.append(kwargs)
        return SimpleNamespace(tracker=SimpleNamespace(), detector=SimpleNamespace(backbone=object()))
    builder.build_sam3_video_model = build
    monkeypatch.setitem(sys.modules, 'torch', torch)
    monkeypatch.setitem(sys.modules, 'sam3', sam3)
    monkeypatch.setitem(sys.modules, 'sam3.model_builder', builder)
    def segment(tracker, folder, photo, seeds, torch_module):
        assert seeds['background'] == [[1, 0]] and tracker.backbone is not None
        selected = np.zeros(photo.shape[:2], dtype=bool)
        selected[:, 1] = True
        return {'background': selected}
    monkeypatch.setattr(worker.completion, 'segment', segment)
    try:
        snapshot = jobs._snapshot(0, 'pixel_draft', 1)
        result = worker.execute(snapshot, {'model_digest': 'pinned', 'sam_checkpoint': str(checkpoint),
            'sam_checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest()}, tmp_path)
        mask = cv2.imdecode(np.frombuffer(base64.b64decode(result['mask']), np.uint8), cv2.IMREAD_UNCHANGED)
        assert np.all(mask[:, :2] == 0) and np.all(mask[:, 2:] == 255)
        assert result['added_pixels'] == 24
        assert built == [{'checkpoint_path': str(checkpoint), 'load_from_HF': False}]
    finally:
        jobs.close()
