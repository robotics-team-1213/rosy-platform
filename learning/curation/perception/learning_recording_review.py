"""One cancellable, derived index of a stopped recording; never robot replay."""
import copy
import re
import threading


class Reviews:
    def __init__(self):
        self.lock = threading.Lock()
        self.busy = threading.Event()
        self.cancelled = threading.Event()
        self.key = self.review = self.result = self.thread = None

    def prepare(self, key, root, revision, *, refresh=False):
        previous = None
        with self.lock:
            if self.busy.is_set():
                if key != self.key or self.cancelled.is_set():
                    raise ValueError('다른 저장 기록의 검수 준비가 끝날 때까지 기다리세요.')
                return copy.deepcopy(self.result)
            if key == self.key and self.result is not None and not refresh:
                return copy.deepcopy(self.result)
            previous, self.review = self.review, None
            self.key = key
            self.cancelled = threading.Event()
            self.result = dict(status='preparing', session_id=key[0], episode_id=key[1],
                               physical_learning_verified=False)
            self.busy.set()
            self.thread = threading.Thread(target=self._build,
                args=(key, root, revision, self.cancelled, previous), daemon=True)
            self.thread.start()
            return copy.deepcopy(self.result)

    def _build(self, key, root, revision, cancelled, previous):
        review = None
        try:
            if previous is not None:
                previous.close()
            from passive_review import Review
            review = Review.build(root, revision, cancelled=cancelled.is_set)
            result = dict(review.summary(), status='ready', session_id=key[0], episode_id=key[1])
        except Exception:
            # Local paths and producer details must not escape a failed background validation.
            result = dict(status='failed', session_id=key[0], episode_id=key[1],
                error='저장 기록의 무결성을 확인하지 못했습니다. 원본과 저장 공간을 확인하세요.',
                physical_learning_verified=False)
        with self.lock:
            if cancelled.is_set():
                self.key = self.result = None
            else:
                self.review, review = review, None
                self.result = result
                self.busy.clear()
                return
        if review is not None:
            review.close()
        with self.lock:
            self.busy.clear()

    def _selected(self, key, revision):
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision):
            raise ValueError('저장 기록의 검수 버전이 필요합니다.')
        with self.lock:
            if (key != self.key or self.review is None or self.result.get('status') != 'ready'
                    or self.result['evidence_revision'] != revision):
                raise ValueError('저장 기록을 다시 열어 검수 버전을 확인하세요.')
            return self.review

    def frame(self, key, revision, index):
        review = self._selected(key, revision)
        row, summary = review.frame(index), review.summary()
        arms = [dict(row['arms'][arm['id']], id=arm['id'], units=arm['units'])
                for arm in summary['arms']]
        prefix = f'/api/learning/recording/review-image/{key[0]}/{key[1]}/{revision}/{index}'
        cameras = [dict({name: value for name, value in row['cameras'][camera['id']].items()
                         if name != 'path'}, id=camera['id'], role=camera['role'],
                        purposes=camera['purposes'], image_url=prefix+'/'+camera['id'])
                   for camera in summary['cameras']]
        return dict(row, arms=arms, cameras=cameras, total_frames=summary['frames'],
                    scope=summary['scope'], physical_learning_verified=False)

    def image(self, key, revision, index, camera):
        return self._selected(key, revision).image(index, camera)

    def close(self, key=None):
        with self.lock:
            if key is not None and self.key is not None and key != self.key:
                return dict(status='closed')
            self.cancelled.set()
            review, self.review = self.review, None
            if not self.busy.is_set():
                self.key = self.result = None
        if review is not None:
            review.close()
        return dict(status='closed')
