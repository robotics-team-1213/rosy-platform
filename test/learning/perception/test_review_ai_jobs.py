"""AI execution publishes candidates without overwriting or approving human labels."""
import base64
import hashlib
import json
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
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


def test_sam_points_publish_bound_candidate_without_editing_review(tmp_path):
    store = workspace(tmp_path)
    before = review_masks.get(store, 0)
    human = review_masks.pixels(store, before)
    proposal = np.full(human.shape, 255, np.uint8)
    proposal[:, 1] = 0
    snapshots = []
    def backend(snapshot, cancel):
        snapshots.append(snapshot)
        return {'mask': base64.b64encode(review_masks.encode(proposal)).decode()}
    jobs = Jobs(store, backend=backend)
    try:
        assert jobs.status(0)['actions']['sam_points']['available']
        jobs.create(0, 'sam_points', 1, 'human-a', prompt={'label': 0, 'points': [[1, 2]]})
        done = finished(jobs)
        assert done['state'] == 'succeeded'
        assert done['model'] == 'sam3' and done['points'] == [[1, 2]] and done['label'] == 0
        assert snapshots[0]['sam_prompt'] == {'label': 0, 'points': [[1, 2]]}
        assert done['result']['selected_pixels'] == 24
        assert done['result']['selection_sha256'] == done['result']['candidate_sha256']
        current = review_masks.get(store, 0)
        assert current['version'] == before['version'] and current['status'] == 'pending'
        assert np.array_equal(review_masks.pixels(store, current), human)
        assert current['draft_candidates'][0]['sha256'] == done['result']['candidate_sha256']
        origin = json.loads(current['draft_candidates'][0]['origin'])
        assert origin['action'] == 'sam_points' and origin['job_id'] == done['id']
        assert origin['sam_prompt'] == {'label': 0, 'points': [[1, 2]]}
        assert origin['requested_by'] == 'human-a'
        assert 'sam_checkpoint_sha256' in origin
    finally:
        jobs.close()


def test_sam_points_reactivate_withdrawn_same_sha_after_managed_class_revision(tmp_path):
    import review_classes
    from review_store import Conflict
    from test_review_classes import request as class_request
    store = workspace(tmp_path)
    proposal = np.full((24, 32), 255, np.uint8)
    proposal[:, 1] = 0
    jobs = Jobs(store, backend=lambda *_: {'mask': base64.b64encode(review_masks.encode(proposal)).decode()})
    try:
        jobs.create(0, 'sam_points', 1, 'human-a', prompt={'label': 0, 'points': [[1, 2]]})
        first = finished(jobs)
        assert first['state'] == 'succeeded'
        digest = first['result']['selection_sha256']
        rows = json.loads(json.dumps(review_masks.served_classes(store)['classes']))
        rows[0]['color'] = [91, 92, 93]
        review_classes.revise(store, class_request(store, 'pixel', rows, 0), 'admin', Conflict)
        assert not review_masks.get(store, 0)['draft_candidates']
        with pytest.raises(ValueError, match='unavailable'):
            review_masks.draft_image(store, 0, digest)
        version = review_masks.get(store, 0)['version']
        jobs.create(0, 'sam_points', version, 'human-b', prompt={'label': 0, 'points': [[1, 3]]})
        second = finished(jobs)
        assert second['state'] == 'succeeded' and second['classes_sha256'] != first['classes_sha256']
        assert second['result']['selection_sha256'] == digest
        candidates = review_masks.get(store, 0)['draft_candidates']
        assert len(candidates) == 1 and json.loads(candidates[0]['origin'])['job_id'] == second['id']
        assert np.array_equal(cv2.imdecode(np.frombuffer(review_masks.draft_image(store, 0, digest), np.uint8),
                                          cv2.IMREAD_UNCHANGED), proposal)
        assert review_masks.get(store, 0)['version'] == version
    finally:
        jobs.close()


@pytest.mark.parametrize('prompt', [None, {}, {'label': 255, 'points': [[1, 2]]},
    {'label': 0, 'points': []}, {'label': 0, 'points': [[1, 2]] * 17},
    {'label': 0, 'points': [[32, 2]]}, {'label': 0, 'points': [[1, -1]]},
    {'label': 0, 'points': [[True, 2]]}, {'label': 0, 'points': [[1.5, 2]]},
    {'label': 0, 'points': [[1, 2]], 'extra': True}])
def test_sam_points_validate_prompt_before_starting_worker(tmp_path, prompt):
    store = workspace(tmp_path)
    called = []
    jobs = Jobs(store, backend=lambda *_: called.append(True))
    try:
        with pytest.raises(ValueError):
            jobs.create(0, 'sam_points', 1, 'human-a', prompt=prompt)
        assert not called and not jobs.status(0)['jobs']
    finally:
        jobs.close()


def test_sam_only_configuration_does_not_require_qwen_model(tmp_path):
    store = workspace(tmp_path)
    with store.connect() as db:
        workspace_id = db.execute("SELECT value FROM metadata WHERE key='workspace_id'").fetchone()[0]
    checkpoint = tmp_path / 'sam.pt'
    checkpoint.write_bytes(b'fixture checkpoint')
    config = tmp_path / 'review-ai.json'
    config.write_text(json.dumps({'workspace_id': workspace_id, 'python': sys.executable,
        'sam_checkpoint': str(checkpoint), 'sam_checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest()}))
    jobs = Jobs(store, config)
    try:
        actions = jobs.status(0)['actions']
        assert actions['sam_points']['available']
        assert not actions['pixel_draft']['available'] and actions['pixel_draft']['reason']
        assert not actions['object_draft']['available']
    finally:
        jobs.close()


def test_fixed_eval_allows_only_explicit_human_sam_points(tmp_path):
    store = workspace(tmp_path)
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('workspace_kind','evaluation')")
    jobs = Jobs(store, backend=lambda *_: {})
    try:
        actions = jobs.status(0)['actions']
        assert actions['sam_points']['available']
        for action in ('object_draft', 'pixel_draft', 'mask_check'):
            assert not actions[action]['available'] and actions[action]['reason']
            with pytest.raises(ValueError):
                jobs.create(0, action, 1, 'human-a')
        assert not jobs.status(0)['jobs']
    finally:
        jobs.close()


def test_fixed_eval_repeated_sam_region_retains_each_human_prompt_provenance(tmp_path):
    store = workspace(tmp_path)
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('workspace_kind','evaluation')")
    proposal = np.full((24, 32), 255, np.uint8)
    proposal[:, 1] = 0
    jobs = Jobs(store, backend=lambda *_: {'mask': base64.b64encode(review_masks.encode(proposal)).decode()})
    jobs.config['sam_checkpoint_sha256'] = 'e' * 64
    completed = []
    try:
        for actor, points in [('human-a', [[1, 2]]), ('human-b', [[1, 3]])]:
            jobs.create(0, 'sam_points', 1, actor, prompt={'label': 0, 'points': points})
            done = finished(jobs)
            assert done['state'] == 'succeeded'
            completed.append(done)
        digest = completed[0]['result']['selection_sha256']
        assert completed[1]['result']['selection_sha256'] == digest
        candidates = review_masks.get(store, 0)['draft_candidates']
        assert len(candidates) == 1
        assert json.loads(candidates[0]['origin'])['job_id'] == completed[0]['id']
        for job in completed:
            _, count, tolerance = review_masks.preview(store, 0, {'version': 1, 'label': job['label'],
                'seeds': job['points'], 'selection_sha256': digest, 'preserve_existing': True}, ValueError)
            assert count == 24 and tolerance == 0
        current = review_masks.get(store, 0)
        assert current['version'] == 1 and current['status'] == 'pending'
        assert np.all(review_masks.pixels(store, current)[:, 1] == 255)
    finally:
        jobs.close()


def test_sam_points_worker_uses_human_clicks_without_qwen(tmp_path, monkeypatch):
    import review_ai_worker as worker
    store = workspace(tmp_path)
    jobs = Jobs(store, backend=lambda *_: {})
    checkpoint = tmp_path / 'sam.pt'
    checkpoint.write_bytes(b'pinned fixture checkpoint')
    monkeypatch.setattr(worker.feedback, '_get_json', lambda *_: pytest.fail('SAM points must not call Qwen'))
    monkeypatch.setattr(worker.completion, 'ask', lambda *_: pytest.fail('human points must reach SAM directly'))
    torch = ModuleType('torch')
    torch.inference_mode = nullcontext
    torch.tensor = lambda value, dtype=None: np.asarray(value, dtype=dtype)
    torch.ones = lambda size, dtype=None: np.ones(size, dtype=dtype)
    torch.float32, torch.int32 = np.float32, np.int32
    calls = []
    class Prediction:
        def __getitem__(self, key): return self
        def cpu(self): return self
        def numpy(self):
            selected = np.zeros((24, 32), dtype=float)
            selected[:, 1:3] = 1
            return selected
    class Tracker:
        def init_state(self, **kwargs):
            assert [path.name for path in Path(kwargs['video_path']).iterdir()] == ['00000.jpg']
            return 'single-frame'
        def add_new_points_or_box(self, **kwargs):
            calls.append(kwargs)
            return None, None, None, Prediction()
    builder = ModuleType('sam3.model_builder')
    builder.build_sam3_video_model = lambda **kwargs: SimpleNamespace(tracker=Tracker(), detector=SimpleNamespace(backbone=object()))
    monkeypatch.setitem(sys.modules, 'torch', torch)
    monkeypatch.setitem(sys.modules, 'sam3', ModuleType('sam3'))
    monkeypatch.setitem(sys.modules, 'sam3.model_builder', builder)
    try:
        snapshot = jobs._snapshot(0, 'sam_points', 1)
        snapshot['sam_prompt'] = {'label': 0, 'points': [[1, 2], [3, 4]]}
        result = worker.execute(snapshot, {'sam_checkpoint': str(checkpoint),
            'sam_checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest()}, tmp_path)
        mask = cv2.imdecode(np.frombuffer(base64.b64decode(result['mask']), np.uint8), cv2.IMREAD_UNCHANGED)
        assert np.all(mask[:, 0] == 255) and np.all(mask[:, 1:3] == 0) and np.all(mask[:, 3:] == 255)
        assert result['selected_pixels'] == 48
        assert len(calls) == 1 and calls[0]['frame_idx'] == 0
        np.testing.assert_allclose(calls[0]['points'], [[1/32, 2/24], [3/32, 4/24]])
        assert calls[0]['labels'].tolist() == [1, 1]
        assert not (tmp_path / 'single-frame').exists()
    finally:
        jobs.close()


def test_missing_configuration_disables_actions(tmp_path):
    store = workspace(tmp_path)
    jobs = Jobs(store)
    try:
        assert not jobs.status(0)['available']
        with pytest.raises(ValueError):
            jobs.create(0, 'object_draft', 1, 'human-a')
    finally:
        jobs.close()


@pytest.mark.parametrize('state', ['not_requested', 'queued', 'running', 'failed', 'cancelled', 'stale'])
def test_feedback_absence_reports_latest_check_state_not_blank_result(tmp_path, state):
    store = workspace(tmp_path)
    jobs = Jobs(store)
    try:
        if state != 'not_requested':
            with store.connect() as db:
                jobs._write(db, dict(id='latest-check', frame=0, action='mask_check', state=state,
                                    version=1, error='Check failed' if state == 'failed' else None))
        result = read_current_feedback(store.state, 0)
        assert result['available'] is False
        assert result['check']['state'] == state
        if state != 'not_requested':
            assert result['check']['version'] == 1
        if state == 'failed':
            assert result['check']['error'] == 'Check failed'
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


@pytest.mark.parametrize('action', ['object_draft', 'pixel_draft'])
def test_revision_quarantine_only_fresh_validated_same_bytes_can_reactivate(tmp_path, monkeypatch, action):
    import copy
    import review_classes
    import vision_review_drafts
    from review_store import Conflict
    store = workspace(tmp_path)
    lane = 'object' if action == 'object_draft' else 'pixel'
    if lane == 'object':
        result = {'boxes': [{'label': 'person', 'bbox_xyxy': [1, 1, 12, 12]}]}
    else:
        proposal = review_masks.pixels(store, review_masks.get(store, 0)).copy()
        proposal[:, 1] = 0
        result = {'mask': base64.b64encode(review_masks.encode(proposal)).decode()}
    candidates = lambda: store.object_drafts(0) if lane == 'object' else review_masks.get(store, 0)['draft_candidates']
    version = lambda: (store.get(0) if lane == 'object' else review_masks.get(store, 0))['version']
    started, release = threading.Event(), threading.Event()
    jobs = Jobs(store, backend=lambda *_: result)
    try:
        original = jobs.create(0, action, version(), 'first-user')
        assert finished(jobs)['state'] == 'succeeded'
        digest = candidates()[0]['sha256']
        def blocked(*_):
            started.set(); assert release.wait(5)
            return result
        jobs.backend = blocked
        stale = jobs.create(0, action, version(), 'old-user')
        assert started.wait(5)
        current = review_classes.snapshot(store, lane)
        rows = copy.deepcopy(current['binding']['classes'])
        if lane == 'object':
            rows.append(dict(index=len(rows), name='new_object', display='새 물체', color=[13, 27, 49]))
        else:
            rows[0]['color'] = [91, 92, 93]
        review_classes.revise(store, dict(kind=lane, classes=rows, expected_sha=current['expected_sha'], expected_impact=0, confirm=True), 'admin', Conflict)
        assert not candidates()
        release.set()
        assert finished(jobs)['state'] == 'stale'
        assert not candidates()
        if lane == 'object':
            # This fake backend supports the appended class; production model compatibility stays guarded.
            monkeypatch.setattr(vision_review_drafts, 'CLASSES', store.object_classes())
        jobs.backend = lambda *_: result
        fresh = jobs.create(0, action, version(), 'fresh-user')
        assert finished(jobs)['state'] == 'succeeded'
        candidate = candidates()[0]
        assert candidate['sha256'] == digest
        assert json.loads(candidate['origin'])['job_id'] == fresh['id']
        assert {job['id'] for job in jobs.status(0)['jobs']} >= {original['id'], stale['id'], fresh['id']}
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
        assert result['mask_version'] == before['version']
        with store.connect() as db:
            jobs._write(db, dict(id='later-failed', frame=0, action='mask_check', state='failed', version=1, error='Later check failed'))
        older = read_current_feedback(store.state, 0)
        assert older['available'] and older['feedback'] == result['feedback'] and older['check']['state'] == 'failed'
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


def test_direct_mask_worker_refuses_whole_road_before_model_access(tmp_path, monkeypatch):
    import review_ai_worker as worker
    store = workspace(tmp_path)
    jobs = Jobs(store, backend=lambda *_: {})
    try:
        snapshot = jobs._snapshot(0, 'mask_check', 1)
        next(entry for entry in snapshot['binding']['classes'] if entry['name'] == 'drivable')['semantic'] = 'road_surface/1'
        called = []
        monkeypatch.setattr(worker.feedback, '_get_json', lambda *_: called.append(True))
        with pytest.raises(ValueError, match='semantic'):
            worker.execute(snapshot, {'model_digest': 'pinned'}, tmp_path)
        assert not called
    finally:
        jobs.close()


def test_per_frame_feedback_expires_after_class_content_change(tmp_path):
    store = workspace(tmp_path)
    jobs = Jobs(store, backend=lambda *_: {'feedback': {'verdict': 'uncertain', 'issue': 'none', 'note': 'check'}})
    try:
        jobs.create(0, 'mask_check', 1, 'human-a')
        assert finished(jobs)['state'] == 'succeeded'
        assert read_current_feedback(store.state, 0)['current']
        with store.connect() as db:
            binding = review_masks.classes(store)
            next(entry for entry in binding['classes'] if entry['name'] == 'drivable')['semantic'] = 'current_road_region/1'
            db.execute("UPDATE metadata SET value=? WHERE key='pixel_classes'", (json.dumps(binding),))
        assert read_current_feedback(store.state, 0)['current'] is False
    finally:
        jobs.close()


@pytest.mark.parametrize('semantic', [None, 'current_road_region/1'])
def test_async_feedback_without_display_defaults_is_current(tmp_path, semantic):
    store = workspace(tmp_path)
    binding = review_masks.classes(store)
    for entry in binding['classes']:
        entry.pop('display', None)
        if entry['role'] == 'drivable':
            if semantic is None:
                entry.pop('semantic', None)
            else:
                entry['semantic'] = semantic
    with store.connect() as db:
        db.execute("UPDATE metadata SET value=? WHERE key='pixel_classes'", (json.dumps(binding),))
    before = review_masks.get(store, 0)
    jobs = Jobs(store, backend=lambda *_: {'feedback': {'verdict': 'uncertain', 'issue': 'none', 'note': 'check'}})
    try:
        jobs.create(0, 'mask_check', 1, 'human-a')
        assert finished(jobs)['state'] == 'succeeded'
        assert read_current_feedback(store.state, 0)['current'] is True
        assert review_masks.get(store, 0) == before
    finally:
        jobs.close()
