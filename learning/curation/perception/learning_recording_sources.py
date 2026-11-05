"""Read registered local sample spools; never discover or control devices."""
import hashlib
import json
from pathlib import Path
import re
import time


def read(root, relative, limit=65536):
    path = Path(root)
    if path.is_symlink() or not path.is_dir():
        raise ValueError('regular source directory required')
    for part in Path(relative).parts:
        if part in ('.', '..') or Path(part).is_absolute():
            raise ValueError('owned relative source file required')
        path = path / part
        if path.is_symlink():
            raise ValueError('source links are not allowed')
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('bounded registered source file required')
    return path.read_bytes()


class Sources:
    def __init__(self, rows, *, registry=None):
        if not isinstance(rows, list) or len(rows) > 96:
            raise ValueError('bounded local source configuration required')
        self.rows = {}
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {'id', 'kind', 'label', 'root'}
                    or not isinstance(row['id'], str)
                    or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}', row['id'])
                    or row['id'] in self.rows or row['kind'] not in ('arm', 'camera')
                    or not isinstance(row['label'], str) or not 1 <= len(row['label']) <= 128):
                raise ValueError('fixed registered source fields required')
            root = Path(row['root'])
            if not root.is_absolute() or root.is_symlink() or not root.is_dir():
                raise ValueError('existing absolute source directory required')
            self.rows[row['id']] = dict(row, root=root.resolve())
        self.fixed_rows = [dict(row) for row in rows]
        self.registry = Path(registry) if registry is not None else None
        if self.registry is not None and (not self.registry.is_absolute()
                or self.registry.is_symlink() or not self.registry.is_dir()):
            raise ValueError('existing absolute local source registry required')

    def _refresh(self):
        if self.registry is None:
            return
        if self.registry.is_symlink() or not self.registry.is_dir():
            raise ValueError('regular local source registry required')
        rows = self.fixed_rows[:]
        count = 0
        for root in self.registry.iterdir():
            count += 1
            if count > 96:
                raise ValueError('local source registry exceeds 96 entries')
            if not root.is_dir() or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}', root.name):
                continue
            if root.is_symlink():
                raise ValueError('source registry links are forbidden')
            if not (root/'registration.json').exists():
                continue
            registration = json.loads(read(root, 'registration.json'))
            if not isinstance(registration, dict) or set(registration) != {'kind', 'label'}:
                raise ValueError('fixed local source registration fields required')
            rows.append(dict(registration, id=root.name, root=root))
        self.rows = Sources(rows).rows

    def descriptor(self, uid):
        row = self.rows[uid]
        value = json.loads(read(row['root'], 'descriptor.json'))
        if not isinstance(value, dict) or value.get('kind') != row['kind']:
            raise ValueError('registered source kind changed')
        return value

    def snapshot(self):
        self._refresh()
        result = []
        for uid, row in self.rows.items():
            public = dict(id=uid, kind=row['kind'], label=row['label'], source_identity=None,
                status='unavailable', reason='등록된 녹화 생산자가 없습니다.', arm_id=None,
                joint_names=None, units=None, shape=None, purposes=[], preview_url=None)
            if row['kind'] == 'arm':
                public['arm_id'] = uid
            try:
                desc = self.descriptor(uid)
                public.update(source_identity=desc.get('source_identity'), shape=desc.get('shape'),
                    joint_names=desc.get('joint_names'), units=desc.get('state_units'))
                fresh = json.loads(read(row['root'], 'latest.json'))
                if not isinstance(fresh, dict):
                    raise ValueError('registered source sample object required')
                stamp = fresh.get('reference_timestamp') if row['kind'] == 'arm' else fresh.get('timestamp')
                if type(stamp) not in (int, float) or not 0 <= time.monotonic() - stamp <= .5:
                    raise ValueError('최근 시연 샘플이 없습니다.')
                if (fresh.get('session_epoch') != desc.get('session_epoch')
                        or fresh.get('source_identity') != desc.get('source_identity')
                        or fresh.get('clock_domain') != desc.get('clock_domain')):
                    raise ValueError('등록 정보와 샘플의 장비·시계 버전이 다릅니다.')
                if row['kind'] == 'arm' and (desc.get('reference_stage') != 'post_guard_accepted'
                        or 'accepted_reference' not in fresh):
                    raise ValueError('검증된 동작 참조 생산자가 없습니다.')
                public.update(status='ready', reason='녹화 시작 전 선택한 구성으로 다시 검증합니다.')
            except (ValueError, OSError, KeyError, TypeError):
                # An image can be previewed without claiming an accepted action or recording provenance.
                if row['kind'] == 'camera':
                    try:
                        read(row['root'], 'preview.jpg', 16 * 1024**2)
                        public.update(status='preview_only', reason='영상만 확인 가능: 녹화 출처·순서 검증이 필요합니다.',
                            preview_url='/api/learning/recording/preview/' + uid)
                    except (ValueError, OSError):
                        pass
            if row['kind'] == 'camera' and public['preview_url'] is None:
                try:
                    read(row['root'], 'preview.jpg', 16 * 1024**2)
                    public['preview_url'] = '/api/learning/recording/preview/' + uid
                except (ValueError, OSError):
                    pass
            result.append(public)
        return result

    def bind(self, profile):
        self._refresh()
        chosen, producers = {}, dict(arms={}, cameras={})
        for arm in profile['arms']:
            uid = arm['id']
            if uid not in self.rows or self.rows[uid]['kind'] != 'arm':
                raise ValueError('선택한 팔에 검증된 동작 기록 생산자가 연결되지 않았습니다.')
            desc = self.descriptor(uid)
            chosen[uid] = ('arms', uid, desc)
            producers['arms'][uid] = desc
        for camera in profile['cameras']:
            if not set(camera['purposes']) - {'monitor'}:
                continue
            matches = []
            for uid, row in self.rows.items():
                if row['kind'] == 'camera':
                    try:
                        matches.append((uid, self.descriptor(uid)))
                    except (ValueError, OSError):
                        continue
            matches = [(uid, desc) for uid, desc in matches if desc.get('source_identity') == camera['source_identity']]
            if len(matches) != 1:
                raise ValueError('카메라의 물리 장치 식별자가 등록 정보와 일치해야 합니다.')
            uid, desc = matches[0]
            chosen[uid] = ('cameras', camera['id'], desc)
            producers['cameras'][camera['id']] = desc
        return chosen, producers

    def poll(self, chosen, cursors, recorder):
        for uid, (kind, logical_id, desc) in chosen.items():
            if self.descriptor(uid) != desc:
                raise ValueError('녹화 중 장비 구성이 변경됐습니다. 새 구성으로 다시 시작하세요.')
            root = self.rows[uid]['root']
            latest = json.loads(read(root, 'latest.json'))
            if any(latest.get(key) != desc.get(key) for key in ('session_epoch', 'source_identity', 'clock_domain')):
                raise ValueError('producer sample identity changed')
            sequence = latest.get('sequence')
            if type(sequence) is not int or sequence < 0:
                raise ValueError('nonnegative producer sequence required')
            prior = cursors.get(uid)
            if prior is not None and sequence < prior:
                raise ValueError('producer sequence regressed')
            if prior == sequence:
                continue
            start = sequence if prior is None else prior + 1
            if sequence - start > 255:
                raise ValueError('bounded source backlog exceeded')
            for index in range(start, sequence + 1):
                event = json.loads(read(root, f'events/{index}.json'))
                if event.get('sequence') != index:
                    raise ValueError('source spool sequence changed')
                if index == sequence and event != latest:
                    raise ValueError('source latest sample differs from immutable event')
                if kind == 'arms':
                    event['arm_id'] = logical_id
                    recorder.push_arm(event, received_at=time.monotonic())
                else:
                    data = read(root, f'events/{index}.jpg', 16 * 1024**2)
                    if event.pop('jpeg_sha256', None) != hashlib.sha256(data).hexdigest():
                        raise ValueError('source JPEG content changed')
                    event['camera_id'] = logical_id
                    recorder.push_camera(event, data, received_at=time.monotonic())
            cursors[uid] = sequence
