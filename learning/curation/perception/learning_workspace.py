"""Persistent links to local learning reports; no job execution or qualification."""
import hashlib
import json
import math
import re
import sqlite3
import uuid
from pathlib import Path

WORKFLOWS = [
    {'id': 'review', 'name': '객체 라벨 검수', 'support': '웹에서 편집·승인·제외·자료 준비',
     'next': '사진 전체를 확인하고 승인 자료를 준비하세요. 세션 분리·고정 평가 제외는 학습 담당자가 확인합니다.'},
    {'id': 'segmentation', 'name': '영역 마스크 검수', 'support': '웹 픽셀 편집·독립 승인 / CVAT 기존 반환 도구',
     'files': ['review-return.json', 'manifest.json'],
     'next': '픽셀 검수에서 사진 전체와 배경을 확인하고 명시 승인하세요. 객체 박스 승인은 픽셀 승인에 적용되지 않습니다. 학습 반영은 별도 검증합니다.'},
    {'id': 'perception', 'name': 'Perception 학습', 'support': '기존 recording_job / train_job CLI',
     'files': ['state.json', 'summary.json', 'intake_report.json'],
     'next': '실패 단계를 확인하고 원래 job 설정으로 CLI를 재개하세요. 품질 거절은 새 조건과 새 작업이 필요합니다.'},
    {'id': 'raw', 'name': 'Pinky 원본 데이터 검증', 'support': '기존 verify_raw / prepare_behavior CLI',
     'files': ['raw-verification.json', 'dataset-manifest.json', 'episode.json'],
     'next': '원본 MCAP과 변환 provenance를 verify_raw로 검증하고 독립 평가 세션을 분리하세요.'},
    {'id': 'pinky', 'name': 'Pinky 행동 학습 연구', 'support': '기존 comparison_job CLI',
     'files': ['state.json', 'comparison-report.json'],
     'next': 'm/s와 rad/s 평가를 각각 확인하세요. research_only 결과에는 로봇 실행 권한이 없습니다.'},
    {'id': 'omx', 'name': 'OMX 시연·ACT 학습', 'support': '기존 LeRobot export / act_job CLI',
     'files': ['state.json', 'offline-report.json'],
     'next': 'episode 분리·관절 단위·평가 거절 이유를 확인하세요. offline_only는 장치 수용이 아닙니다.'},
    {'id': 'policy', 'name': '정책 산출물·원장', 'support': '기존 registry CLI / artifact 확인',
     'files': ['policy-artifact.json', 'offline-report.json', 'comparison-report.json'],
     'next': 'registry에서 파일 closure·평가 receipt를 검증하세요. 보고서 열람은 원장 승격이나 owner 실행 허가가 아닙니다.'},
    {'id': 'isaac', 'name': 'Isaac 학습 환경', 'support': '기존 시뮬레이션 도구',
     'files': ['state.json', 'summary.json'],
     'next': '환경·센서·과제 설정을 독립 시뮬레이션에서 확인하세요. 이 화면은 환경을 실행하지 않습니다.'},
]
KINDS = {row['id']: row for row in WORKFLOWS if 'files' in row}


def report_image(root, item):
    name, expected = item.get('name'), item.get('sha256')
    if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.jpe?g', name, re.I)
            or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)):
        raise ValueError('invalid JPG evidence reference')
    file = root / name
    if file.is_symlink() or file.resolve().parent != root or not file.is_file():
        raise ValueError('JPG evidence must be a regular file in the result directory')
    if file.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('JPG evidence exceeds 10 MiB')
    raw = file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected or not raw.startswith(b'\xff\xd8'):
        raise ValueError('JPG evidence hash or format differs')
    return raw


def read_report(root, name, baseline=None):
    file = root / name
    result = {'name': name, 'status': 'missing'}
    if not file.exists() and not file.is_symlink():
        return result
    try:
        if file.is_symlink() or file.resolve().parent != root:
            raise ValueError('report link outside registered directory')
        if not file.is_file() or file.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('report must be a JSON file under 2 MiB')
        raw = file.read_bytes()
        doc = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        if not isinstance(doc, dict):
            raise ValueError('report must be a JSON object')
        digest = hashlib.sha256(raw).hexdigest()
        result.update(status='unchanged' if baseline == digest else 'changed', sha256=digest)
        # Only known status fields are returned. Inputs/config/credentials remain on disk.
        result['declared'] = {key: str(doc[key])[:500] for key in
            ('schema', 'status', 'outcome', 'verdict', 'promotion', 'offline_verdict', 'error', 'revision')
            if key in doc and isinstance(doc[key], (str, bool, int, float))}
        result['reasons'] = [str(reason)[:500] for reason in doc.get('reasons', [])[:20]] if isinstance(doc.get('reasons'), list) else []
        result['steps'] = [{'name': str(key)[:100], 'status': str(value.get('status', 'unknown'))[:100],
                            'error': str(value.get('error', ''))[:500]}
                           for key, value in list(doc.get('steps', {}).items())[:40] if isinstance(value, dict)] if isinstance(doc.get('steps'), dict) else []
        metrics = doc.get('metrics', [])
        if isinstance(metrics, list):
            result['metrics'] = [{'label': row['label'][:60], 'value': row['value'],
                                  'unit': row.get('unit', '')[:12]}
                                 for row in metrics[:6] if isinstance(row, dict)
                                 and isinstance(row.get('label'), str)
                                 and type(row.get('value')) in (int, float) and math.isfinite(row['value'])
                                 and isinstance(row.get('unit', ''), str)]
        images = doc.get('images', [])
        if not isinstance(images, list) or len(images) > 12:
            raise ValueError('at most 12 JPG evidence files allowed')
        result['images'] = []
        for item in images:
            if not isinstance(item, dict):
                raise ValueError('invalid JPG evidence reference')
            report_image(root, item)
            result['images'].append({'name': item['name'], 'sha256': item['sha256']})
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        result.update(status='invalid', error=str(exc)[:500])
    return result


class Workspace:
    def __init__(self, db):
        self.db = Path(db)
        with sqlite3.connect(self.db) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS learning_links
                (id TEXT PRIMARY KEY, kind TEXT, name TEXT, path TEXT, hashes TEXT,
                 version INTEGER, UNIQUE(kind,path))''')

    def inspect(self, row):
        root = Path(row[3])
        hashes = json.loads(row[4])
        reports = [read_report(root, name, hashes.get(name)) for name in KINDS[row[1]]['files']]
        return {'id': row[0], 'kind': row[1], 'name': row[2], 'path': row[3], 'version': row[5],
                'reports': reports, 'qualified': False, 'next': KINDS[row[1]]['next']}

    def list(self):
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute('SELECT * FROM learning_links ORDER BY rowid DESC').fetchall()
        return [self.inspect(row) for row in rows]

    def image(self, identifier, name):
        with sqlite3.connect(self.db) as conn:
            row = conn.execute('SELECT * FROM learning_links WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('unknown learning result')
        root = Path(row[3])
        for report in KINDS[row[1]]['files']:
            for item in read_report(root, report).get('images', []):
                if item['name'] == name:
                    return report_image(root, item), item['sha256']
        raise ValueError('JPG evidence is not declared by this result')

    def register(self, body):
        kind, name, path = body.get('kind'), body.get('name'), body.get('path')
        if kind not in KINDS or not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('known learning kind and name (1..100 characters) required')
        if not isinstance(path, str) or not path.strip() or len(path) > 2048:
            raise ValueError('local result directory required')
        if path.startswith(('\\\\', '//')):
            raise ValueError('network paths are not local result directories')
        original = Path(path)
        if not original.is_absolute() or original.is_symlink():
            raise ValueError('absolute local directory without links required')
        root = original.resolve()
        if not root.is_dir():
            raise ValueError('result directory does not exist')
        reports = [read_report(root, file) for file in KINDS[kind]['files']]
        if any(row['status'] == 'invalid' for row in reports):
            raise ValueError(next(row['error'] for row in reports if row['status'] == 'invalid'))
        if not any('sha256' in row for row in reports):
            raise ValueError('no supported report files in result directory')
        row = (uuid.uuid4().hex, kind, name.strip(), str(root),
               json.dumps({r['name']: r['sha256'] for r in reports if 'sha256' in r}), 1)
        try:
            with sqlite3.connect(self.db) as conn:
                conn.execute('INSERT INTO learning_links VALUES (?,?,?,?,?,?)', row)
        except sqlite3.IntegrityError as exc:
            raise ValueError('result directory already registered for this kind') from exc
        return self.inspect(row)

    def remove(self, body):
        if not isinstance(body.get('id'), str) or type(body.get('version')) is not int:
            raise ValueError('id and integer version required')
        with sqlite3.connect(self.db) as conn:
            deleted = conn.execute('DELETE FROM learning_links WHERE id=? AND version=?',
                                   (body['id'], body['version'])).rowcount
            if not deleted:
                raise ValueError('version conflict or link already removed; reload')
        return {'removed': body['id']}
