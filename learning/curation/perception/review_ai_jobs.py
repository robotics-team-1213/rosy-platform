"""Durable, bounded single-frame AI requests; publication never edits human labels."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

import cv2
import numpy as np

import class_sets
import review_masks
import vision_review_drafts
import vlm_mask_feedback


ACTIONS = ('object_draft', 'pixel_draft', 'mask_check')
ACTIVE = ('queued', 'running')


class Jobs:
    def __init__(self, store, config_file=None, *, backend=None):
        self.store, self.backend = store, backend
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.config, self.reason = None, 'AI 실행 설정이 없습니다. 관리자에게 모델 PC 설정을 요청하세요.'
        self.folder = store.state / 'review-ai'
        self.folder.mkdir(exist_ok=True)
        self.lease = (self.folder / '.worker.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.lease.write(b'0'); self.lease.flush(); self.lease.seek(0)
                msvcrt.locking(self.lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close()
            self.lease = None
            self.reason = '이 자료의 AI 실행기가 이미 열려 있습니다.'
        with store.lock, store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS review_ai_jobs (
                id TEXT PRIMARY KEY, frame INTEGER NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS review_ai_feedback (
                frame INTEGER PRIMARY KEY, report TEXT NOT NULL);''')
            if self.lease:
                for row in db.execute('SELECT document FROM review_ai_jobs').fetchall():
                    job = json.loads(row[0])
                    if job['state'] in ACTIVE:
                        job.update(state='failed', error='실행기 재시작으로 중단되었습니다. 다시 요청하세요.')
                        self._write(db, job)
        if self.lease and backend:
            self.config = {'model_digest': 'test-backend', 'workspace_id': self._metadata()['workspace_id']}
        elif self.lease and config_file:
            try:
                config = json.loads(Path(config_file).read_text(encoding='utf-8'))
                if (config['workspace_id'] != self._metadata()['workspace_id']
                        or not Path(config['python']).is_absolute() or not Path(config['python']).is_file()
                        or not re.fullmatch(r'(?:sha256:)?[a-f0-9]{64}', config['model_digest'])):
                    raise ValueError('invalid worker configuration')
                self.config = {key: config[key] for key in ('workspace_id', 'python', 'model_digest')}
                if config.get('sam_checkpoint'):
                    if (not Path(config['sam_checkpoint']).is_absolute()
                            or not Path(config['sam_checkpoint']).is_file()
                            or not re.fullmatch('[a-f0-9]{64}', config['sam_checkpoint_sha256'])):
                        raise ValueError('invalid checkpoint configuration')
                    self.config.update({key: config[key] for key in ('sam_checkpoint', 'sam_checkpoint_sha256')})
            except (OSError, ValueError, KeyError, TypeError):
                self.config = None
                self.reason = 'AI 실행 설정의 작업공간·인터프리터·모델 식별 정보를 확인하세요.'

    def _metadata(self):
        with self.store.connect() as db:
            return dict(db.execute('SELECT key,value FROM metadata'))

    @staticmethod
    def _write(db, job):
        job['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        db.execute('INSERT OR REPLACE INTO review_ai_jobs VALUES (?,?,?)',
                   (job['id'], job['frame'], json.dumps(job, ensure_ascii=False)))

    def status(self, index):
        frame = self.store.get(index)
        mask = review_masks.get(self.store, index)
        actions = {}
        for action in ACTIONS:
            reason = '' if self.config and self.lease else self.reason
            if not reason and frame['status'] == 'excluded':
                reason = '제외한 사진은 AI 작업을 실행할 수 없습니다.'
            if not reason and action == 'object_draft':
                if frame['status'] != 'pending':
                    reason = '객체 재검수를 시작한 뒤 초안을 요청하세요.'
                elif self.store.object_classes() != vision_review_drafts.CLASSES:
                    reason = '이 모델은 obstacle을 포함한 7개 객체 클래스로 새로 만든 작업공간에서 사용할 수 있습니다.'
            if not reason and action != 'object_draft':
                if not mask['classes'] or not any(c['name'] == 'drivable' for c in mask['classes']['classes']):
                    reason = '드라이버블 픽셀 클래스 설정이 필요합니다.'
                elif mask['status'] == 'excluded':
                    reason = '제외한 픽셀 검수는 AI 작업을 실행할 수 없습니다.'
                elif not review_masks.lane_boundary_classes(mask['classes']):
                    reason = '현재 AI는 차선 안쪽 도로만 판단합니다. 전체 도로(road_surface/1) 검수는 지원하지 않습니다.'
                elif action == 'mask_check' and mask['path'] is None:
                    reason = '픽셀 마스크를 저장한 뒤 AI 확인을 요청하세요.'
                elif action == 'pixel_draft':
                    if mask['status'] != 'pending':
                        reason = '픽셀 재검수를 시작한 뒤 초안을 요청하세요.'
                    elif not self.backend and 'sam_checkpoint' not in self.config:
                        reason = 'SAM 체크포인트 설정이 필요합니다.'
            if not reason and action == 'mask_check':
                try:
                    vlm_mask_feedback.feedback_binding(mask['classes'])
                except ValueError:
                    reason = '현재 AI 확인은 구형 또는 current_road_region/1 클래스 의미만 지원합니다.'
            actions[action] = {'available': not reason, 'reason': reason}
        with self.store.connect() as db:
            jobs = [json.loads(row[0]) for row in db.execute(
                'SELECT document FROM review_ai_jobs WHERE frame=? ORDER BY rowid DESC LIMIT 30', (index,))]
        return {'available': any(item['available'] for item in actions.values()),
                'reason': '' if self.config else self.reason, 'actions': actions, 'jobs': jobs}

    def _snapshot(self, index, action, version):
        frame = self.store.get(index)
        source = frame['source']
        image_path = (self.store.state / source['image']).resolve()
        if not image_path.is_relative_to(self.store.state):
            raise ValueError('image outside workspace')
        image = image_path.read_bytes()
        if len(image) > 32 * 1024 * 1024 or hashlib.sha256(image).hexdigest() != source['image_sha256']:
            raise ValueError('image snapshot differs')
        snapshot = {key: source[key] for key in ('width', 'height', 'image_sha256')}
        snapshot.update(frame=index, action=action, version=frame['version'], status=frame['status'],
                        object_status=frame['status'],
                        source=source, image=base64.b64encode(image).decode('ascii'))
        if action == 'object_draft':
            snapshot['binding'] = class_sets.object_set(self.store)
        else:
            mask = review_masks.get(self.store, index)
            snapshot.update(version=mask['version'], status=mask['status'], mask_sha256=mask['sha256'],
                            binding=mask['classes'],
                            mask=base64.b64encode(review_masks.encode(review_masks.pixels(self.store, mask))).decode('ascii'))
        if action == 'mask_check':
            snapshot['binding'] = review_masks.classes(self.store)
            snapshot['review_binding'] = vlm_mask_feedback.feedback_binding(snapshot['binding'])
        if version is not None and version != snapshot['version']:
            raise ValueError('검수 버전이 바뀌었습니다. 사진을 다시 불러오세요.')
        return snapshot

    def create(self, index, action, version, actor, *, authorize=None):
        if (action not in ACTIONS or type(version) is not int or version < 0
                or not isinstance(actor, str) or not 1 <= len(actor) <= 256):
            raise ValueError('invalid AI request')
        with self.guard, self.store.lock:
            if authorize:
                authorize(actor)
            state = self.status(index)
            if not state['actions'][action]['available']:
                raise ValueError(state['actions'][action]['reason'])
            if self.thread and self.thread.is_alive():
                raise ValueError('다른 AI 작업이 실행 중입니다. 완료하거나 중지한 뒤 요청하세요.')
            snapshot = self._snapshot(index, action, version)
            job = {'id': uuid.uuid4().hex, 'frame': index, 'action': action, 'version': version,
                   'state': 'queued', 'actor': actor, 'model': vision_review_drafts.MODEL,
                   'model_digest': self.config['model_digest'], 'image_sha256': snapshot['image_sha256'],
                   'workspace_id': self.config['workspace_id'], 'mask_sha256': snapshot.get('mask_sha256'),
                   'classes_sha256': (snapshot.get('binding') or {}).get('sha256'),
                   'sam_checkpoint_sha256': self.config.get('sam_checkpoint_sha256') if action == 'pixel_draft' else None,
                   'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'error': None, 'result': None}
            self.stop = threading.Event()
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                self._write(db, job)
            self.thread = threading.Thread(target=self._run, args=(job, snapshot, authorize), daemon=True)
            self.thread.start()
            return dict(job)

    def _process(self, snapshot, cancel):
        folder = self.folder / uuid.uuid4().hex
        folder.mkdir()
        source, output = folder / 'input.json', folder / 'output.json'
        source.write_text(json.dumps({'snapshot': snapshot, 'config': self.config}), encoding='utf-8')
        process = None
        try:
            process = subprocess.Popen([self.config['python'], str(Path(__file__).with_name('review_ai_worker.py')),
                                        '--input', str(source), '--output', str(output),
                                        '--parent-pid', str(os.getpid())],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 600
            while process.poll() is None:
                if cancel.wait(.1) or time.monotonic() > deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
                    raise ValueError('worker stopped or timed out')
            if process.returncode or not output.is_file() or output.stat().st_size > 48 * 1024 * 1024:
                raise ValueError('worker failed')
            return json.loads(output.read_text(encoding='utf-8'))
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            # Snapshot files contain image data; retain only the durable job/candidate provenance.
            if folder.resolve().parent == self.folder.resolve() and not folder.is_symlink():
                shutil.rmtree(folder)

    def _run(self, job, snapshot, authorize=None):
        try:
            with self.store.lock, self.store.connect() as db:
                job['state'] = 'running'
                self._write(db, job)
            result = (self.backend or self._process)(snapshot, self.stop)
            with self.store.lock, self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current = self._snapshot(job['frame'], job['action'], None)
                if self.stop.is_set():
                    job['state'] = 'cancelled'
                    saved = db.execute('SELECT document FROM review_ai_jobs WHERE id=?', (job['id'],)).fetchone()
                    if saved and json.loads(saved[0]).get('cancelled_by'):
                        job['cancelled_by'] = json.loads(saved[0])['cancelled_by']
                elif current != snapshot:
                    job['state'] = 'stale'
                else:
                    if authorize:
                        authorize(job['actor'])
                    job['result'] = self._publish(db, job, snapshot, result)
                    job['state'] = 'succeeded'
                self._write(db, job)
        except Exception:
            with self.store.lock, self.store.connect() as db:
                saved = db.execute('SELECT document FROM review_ai_jobs WHERE id=?', (job['id'],)).fetchone()
                if saved and json.loads(saved[0]).get('cancelled_by'):
                    job['cancelled_by'] = json.loads(saved[0])['cancelled_by']
                job.update(state='cancelled' if self.stop.is_set() else 'failed',
                           error=None if self.stop.is_set() else 'AI 작업을 완료하지 못했습니다. 설정과 검수 버전을 확인하고 다시 요청하세요.')
                self._write(db, job)

    def _publish(self, db, job, snapshot, result):
        if not isinstance(result, dict):
            raise ValueError('invalid worker output')
        origin = json.dumps({'job_id': job['id'], 'requested_by': job['actor'], 'model': job['model'],
                             'model_digest': job['model_digest']}, ensure_ascii=False)
        if job['action'] == 'object_draft':
            boxes = result['boxes']
            if not isinstance(boxes, list) or len(boxes) > 30:
                raise ValueError('bounded boxes required')
            self.store.validate_boxes(snapshot['source'], boxes, classes=self.store.object_classes(), approved=True)
            raw = json.dumps(boxes, sort_keys=True)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO object_drafts VALUES (?,?,?,?,?)',
                       (job['frame'], digest, raw, origin, hashlib.sha256(job['id'].encode()).hexdigest()))
            return {'candidate_sha256': digest, 'boxes': len(boxes)}
        human = cv2.imdecode(np.frombuffer(base64.b64decode(snapshot['mask']), np.uint8), cv2.IMREAD_UNCHANGED)
        if job['action'] == 'pixel_draft':
            if not isinstance(result.get('mask'), str) or len(result['mask']) > 48 * 1024 * 1024:
                raise ValueError('bounded mask required')
            raw = base64.b64decode(result['mask'], validate=True)
            raw = review_masks.from_indexed(raw, snapshot['width'], snapshot['height'], snapshot['binding'])
            proposal = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
            if not np.array_equal(proposal[human != 255], human[human != 255]):
                raise ValueError('human labels changed')
            review_masks.require_inside_lane_boundaries(proposal, snapshot['binding'])
            added = int(np.count_nonzero((human == 255) & (proposal != 255)))
            if not added:
                return {'added_pixels': 0}
            path, digest = review_masks.freeze(self.store, raw)
            db.execute('INSERT OR IGNORE INTO pixel_drafts(frame,sha256,path,catalog_sha256,origin) VALUES (?,?,?,?,?)',
                       (job['frame'], digest, path, hashlib.sha256(job['id'].encode()).hexdigest(), origin))
            return {'candidate_sha256': digest, 'added_pixels': added}
        value = vlm_mask_feedback._feedback(result['feedback'])
        meta = self._metadata()
        item = {'frame': job['frame'], 'status_at_snapshot': snapshot['status'],
                'image_sha256': snapshot['image_sha256'], 'mask_sha256': snapshot['mask_sha256'],
                'unknown_pixels': int(np.count_nonzero(human == 255)),
                'review_blocked': bool(np.any(human == 255)), 'feedback': value}
        report = {'schema': 'rosy.v13-vlm-feedback/1', 'advisory_only': True, 'training_admission': False,
                  'workspace_id': meta['workspace_id'], 'generation': meta['generation'],
                  'model': job['model'], 'model_digest': job['model_digest'], 'frames': [item],
                  'review_binding': snapshot['review_binding'],
                  'job_id': job['id'], 'requested_by': job['actor'], 'created_at': job['created_at']}
        db.execute('INSERT OR REPLACE INTO review_ai_feedback VALUES (?,?)', (job['frame'], json.dumps(report)))
        return {'feedback': value}

    def cancel(self, identifier, actor):
        with self.guard, self.store.lock, self.store.connect() as db:
            if self.lease is None:
                raise ValueError('AI 실행기 소유권이 없어 작업을 중지할 수 없습니다.')
            row = db.execute('SELECT document FROM review_ai_jobs WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise KeyError(identifier)
            job = json.loads(row[0])
            if job['state'] in ACTIVE:
                self.stop.set()
                job.update(state='cancelled', cancelled_by=actor)
                self._write(db, job)
            return job

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)
        if self.lease and not (self.thread and self.thread.is_alive()):
            self.lease.close()
            self.lease = None
