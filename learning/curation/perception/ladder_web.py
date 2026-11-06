"""Learning ladder routes: read OMX ladder rounds, record a person's replace/keep, start a round.

Rounds are simulation evidence (D-947). Replacing the best round is a comparison record, not an
approval, promotion or device change (D-793, D-857). Record format: rosy.omx-ladder-round.v1.
"""
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import time
from datetime import datetime, timezone

try:
    import fcntl
except ImportError:  # shortcut: the cross-process decision lock needs POSIX; the review app only serves from Linux
    fcntl = None

STATIC = Path(__file__).with_name('review_app_web')
PREFIX = '/api/learning/ladder/'
PAGES = {'/learning/ladder': ('ladder.html', 'text/html'), '/ladder.js': ('ladder.js', 'text/javascript'),
         '/ladder.css': ('ladder.css', 'text/css')}
ROUND = '[0-9]{8}T[0-9]{6}-[0-9a-f]{8}'
SCHEMA = 'rosy.omx-ladder-round.v1'
STATUSES = {'pending', 'running', 'passed', 'failed', 'blocked', 'not_run'}
IMAGES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
PART = '[A-Za-z0-9_][A-Za-z0-9._-]{0,99}'
ARTIFACT = PART + '(?:/' + PART + '){0,3}'
ENTRY = Path(__file__).resolve().parents[3] / 'tools/sim/omx_ladder.py'
KEYS = {'root', 'cell', 'python', 'lerobot_train'}
LIMITS = {'episodes': (1, 1000), 'eval_episodes': (1, 500), 'steps': (1, 1000000)}
SHOWN = 200
STALE_SECONDS = 12 * 3600
Z = 1.96


def load(path, parser):
    """The operator's private ladder configuration, or None when none was given."""
    if path is None:
        return None
    try:
        return Ladder(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        parser.error(f'--ladder-config: {exc}')


def scalar(value, limit=300):
    if value is None or isinstance(value, (bool, int)) or (isinstance(value, float) and math.isfinite(value)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return None if isinstance(value, float) else text[:limit]


def flat(value, limit=40):
    return {str(k)[:60]: scalar(v) for k, v in list(value.items())[:limit]} if isinstance(value, dict) else {}


def interval(public):
    """(low, high) of the strict success rate as the record states it, or None without an evaluation."""
    ev = (public['stages']['mujoco'] or {}).get('eval')
    if not ev or not isinstance(ev.get('n'), int) or ev['n'] <= 0 or not isinstance(ev['strict'].get('placed'), int):
        return None
    n, p = ev['n'], ev['strict']['placed'] / ev['n']
    centre = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    low = ev['strict'].get('wilson_low')
    return (low if isinstance(low, float) else centre - half, centre + half)


def verdict(this, best):
    """Intervals that do not overlap decide; anything else, including no data, stays undecided."""
    a, b = interval(this), interval(best) if best else None
    if a is None or b is None:
        return 'unclear'
    return 'better' if a[0] > b[1] else 'worse' if a[1] < b[0] else 'unclear'


def artifacts(raw):
    rows = [row for row in raw if isinstance(row, dict)][:40] if isinstance(raw, list) else []
    return [{'name': scalar(row.get('name'), 80), 'path': row['path']} for row in rows
            if isinstance(row.get('path'), str) and row['path'].startswith('artifacts/')
            and re.fullmatch(ARTIFACT, row['path'][10:]) and Path(row['path']).suffix.lower() in IMAGES]


def stage(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {'status': raw.get('status') if raw.get('status') in STATUSES else 'unknown'}
    out.update({key: scalar(raw.get(key)) for key in ('claim', 'reason', 'started_at', 'finished_at', 'run_id', 'result')})
    out['artifacts'] = artifacts(raw.get('artifacts'))
    if isinstance(raw.get('eval'), dict):
        ev = raw['eval']
        out['eval'] = {**{key: scalar(ev.get(key)) for key in ('n', 'seed_base', 'lifted', 'xy_err_mm_median', 'yaw_err_deg_median')},
                       'strict': flat(ev.get('strict')), 'loose': flat(ev.get('loose'))}
    if isinstance(raw.get('contract'), dict):
        out['contract'] = {key: scalar(raw['contract'].get(key)) for key in ('backend', 'passed', 'report')}
        out['contract']['checks'] = flat(raw['contract'].get('checks'))
    return out


def public(value):
    stages = value.get('stages') if isinstance(value.get('stages'), dict) else {}
    row = {'round_id': value['round_id'], 'created_at': scalar(value.get('created_at')),
           'parent_round_id': scalar(value.get('parent_round_id')), 'source_sha': scalar(value.get('source_sha'), 40)}
    row.update({key: flat(value.get(key)) for key in ('scene', 'recipe', 'data')})
    row['stages'] = {name: stage(stages.get(name)) for name in ('mujoco', 'gazebo', 'isaac')}
    return row


class Ladder:
    def __init__(self, config):
        if (not isinstance(config, dict) or not KEYS <= set(config) or set(config) - KEYS
                or not all(isinstance(config[key], str) and Path(config[key]).is_absolute() for key in KEYS)):
            raise ValueError('ladder configuration needs absolute root, cell, python and lerobot_train')
        self.root, self.cell, self.python, self.train = (Path(config[key]) for key in ('root', 'cell', 'python', 'lerobot_train'))
        self.process = None
        self.lock = threading.Lock()

    def load(self, round_id):
        """Raw record of one round, or None when it is missing, linked, oversized or corrupt."""
        if not re.fullmatch(ROUND, round_id):
            return None
        try:
            directory = self.root / 'rounds' / round_id
            info = (directory / 'round.json').lstat()
            if directory.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 1 << 20:
                return None
            value = json.loads((directory / 'round.json').read_text(encoding='utf-8'))
            return value if value.get('schema') == SCHEMA and value.get('round_id') == round_id else None
        except (OSError, ValueError, AttributeError):
            return None

    def ids(self):
        try:
            return sorted((p.name for p in (self.root / 'rounds').iterdir() if re.fullmatch(ROUND, p.name)), reverse=True)
        except OSError:
            return []

    def decisions(self):
        file = self.root / 'decisions.jsonl'
        try:
            if file.stat().st_size > 4 << 20:
                return []
            lines = file.read_text(encoding='utf-8').splitlines()
        except (OSError, ValueError):
            return []
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a torn line is skipped, never fatal
            if isinstance(row, dict) and row.get('verdict') in ('replace', 'keep') and re.fullmatch(ROUND, str(row.get('round_id'))):
                rows.append({key: scalar(row.get(key)) for key in ('at', 'by', 'round_id', 'verdict', 'note', 'best_before')})
        return rows

    def best(self):
        """The last replace in the decision record; best.json is only its copy."""
        replaced = [row['round_id'] for row in self.decisions() if row['verdict'] == 'replace']
        if replaced:
            return replaced[-1]
        try:
            value = json.loads((self.root / 'best.json').read_text(encoding='utf-8'))['round_id']
            return value if re.fullmatch(ROUND, value) else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def running(self):
        if self.process and self.process.poll() is None:
            return True
        # A round started before a restart: trust a running stage only while its record is recent.
        for round_id in self.ids()[:5]:
            value, file = self.load(round_id), self.root / 'rounds' / round_id / 'round.json'
            try:
                recent = time.time() - file.stat().st_mtime < STALE_SECONDS
            except OSError:
                continue
            if recent and value and any(isinstance(s, dict) and s.get('status') == 'running'
                                        for s in (value.get('stages') or {}).values()):
                return True
        return False

    def row(self, round_id, best=None):
        value = self.load(round_id)
        if value is None:
            return {'round_id': round_id, 'unreadable': True}
        row = public(value)
        if best is not None:
            row['comparison'] = 'current' if best['round_id'] == round_id else verdict(row, best)
            row['same_seeds'] = (row['stages']['mujoco'].get('eval') or {}).get('seed_base') == \
                                (best['stages']['mujoco'].get('eval') or {}).get('seed_base')
        return row

    def best_row(self):
        best_id = self.best()
        value = best_id and self.load(best_id)
        return public(value) if value else None

    def snapshot(self):
        best = self.best_row()
        return {'configured': True, 'running': self.running(), 'best_round_id': best and best['round_id'],
                'rounds': [self.row(round_id, best) for round_id in self.ids()[:SHOWN]]}

    def summary(self):
        ids = self.ids()
        return {'rounds': len(ids), 'best': self.best(), 'running': self.running()}

    def artifact(self, round_id, rel):
        """(bytes, media type) of one round image; nothing outside the round's artifacts folder, no links."""
        suffix = Path(rel).suffix.lower()
        base = self.root / 'rounds' / round_id / 'artifacts'
        if suffix not in IMAGES:
            raise FileNotFoundError
        target = base
        for part in rel.split('/'):
            target = target / part
        for link in [base.parent, base, *list(target.parents)[:len(rel.split('/')) - 1]]:
            if link.is_symlink():
                raise FileNotFoundError
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size > 8 << 20
                or not target.resolve().is_relative_to(base.resolve())):
            raise FileNotFoundError
        return target.read_bytes(), IMAGES[suffix]

    def decide(self, actor, body):
        if set(body) != {'round_id', 'verdict', 'note'} or body['verdict'] not in ('replace', 'keep'):
            raise ValueError('판단 요청 필드를 확인하세요.')
        note = body['note'].strip() if isinstance(body['note'], str) else ''
        if not 1 <= len(note) <= 200 or '\n' in note or '\r' in note:
            raise ValueError('한 줄 근거를 1~200자로 적어 주세요.')
        value = self.load(body['round_id']) if isinstance(body['round_id'], str) else None
        if value is None:
            raise ValueError('알 수 없거나 읽을 수 없는 라운드입니다.')
        if public(value)['stages']['mujoco']['status'] != 'passed':
            raise ValueError('MuJoCo 단계가 통과하지 않은 라운드는 판단할 수 없습니다.')
        with self.lock:
            file = self.root / 'decisions.jsonl'
            with open(file, 'a+', encoding='utf-8') as stream:
                if fcntl:
                    fcntl.flock(stream, fcntl.LOCK_EX)
                row = {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'by': actor,
                       'round_id': body['round_id'], 'verdict': body['verdict'], 'note': note, 'best_before': self.best()}
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
                if body['verdict'] == 'replace':
                    temporary = self.root / 'best.json.tmp'
                    temporary.write_text(json.dumps({'round_id': body['round_id']}), encoding='utf-8')
                    os.replace(temporary, self.root / 'best.json')
        return row

    def start(self, body):
        """Launch the fixed round command; every value is bounded here, no client path or code reaches it."""
        required = {'episodes', 'eval_episodes', 'steps', 'lr'}
        if not required <= body.keys() or body.keys() - required - {'parent'}:
            raise ValueError('라운드 시작 필드를 확인하세요.')
        for key, (low, high) in LIMITS.items():
            if type(body[key]) is not int or not low <= body[key] <= high:
                raise ValueError(f'{key} 범위를 확인하세요 ({low}~{high}).')
        lr = body['lr']
        if type(lr) not in (int, float) or not 1e-7 <= lr <= 1e-2:
            raise ValueError('학습률 범위를 확인하세요 (1e-7~1e-2).')
        parent = body.get('parent')
        if parent is not None and (not isinstance(parent, str) or self.load(parent) is None):
            raise ValueError('이전 라운드를 읽을 수 없습니다.')
        command = [str(self.python), str(ENTRY), 'round', '--root', str(self.root), '--cell', str(self.cell),
                   '--python', str(self.python), '--lerobot-train', str(self.train),
                   *(['--parent', parent] if parent else []), '--episodes', str(body['episodes']),
                   '--eval-episodes', str(body['eval_episodes']), '--steps', str(body['steps']), '--lr', repr(float(lr))]
        env = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME') if key in os.environ}
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
        with self.lock:
            if self.running():
                return False
            with open(self.root / 'start.log', 'wb') as log:
                self.process = subprocess.Popen(command, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return True


def status(ladder):
    """Home-row input: None when not configured, {'error': ...} when the root cannot be read."""
    if ladder is None:
        return None
    try:
        return ladder.summary()
    except (OSError, ValueError):
        return {'error': 'unavailable'}


def get(handler, path, ladder):
    if path in PAGES:
        name, mime = PAGES[path]
        handler.send((STATIC / name).read_bytes(), mime=mime + '; charset=utf-8')
    elif not path.startswith(PREFIX):
        return False
    elif ladder is None:
        handler.send({'configured': False, 'running': False, 'best_round_id': None, 'rounds': []})
    elif path == PREFIX + 'rounds':
        handler.send(ladder.snapshot())
    elif match := re.fullmatch(PREFIX + 'rounds/(' + ROUND + ')', path):
        best = ladder.best_row()
        handler.send({'round': ladder.row(match[1], best), 'best_round_id': best and best['round_id'],
                      'decisions': [row for row in ladder.decisions() if row['round_id'] == match[1]][-20:]})
    elif match := re.fullmatch(PREFIX + 'rounds/(' + ROUND + ')/artifacts/(' + ARTIFACT + ')', path):
        try:
            raw, mime = ladder.artifact(match[1], match[2])
            handler.send(raw, mime=mime)
        except OSError:
            handler.send({'error': '그림을 찾을 수 없습니다.'}, 404)
    else:
        handler.send({'error': '사다리 경로를 확인하세요.'}, 404)
    return True


def post(handler, path, body, ladder, collaboration):
    if not path.startswith(PREFIX):
        return False
    if not collaboration:
        raise PermissionError('Ladder control requires an authenticated project manager')
    collaboration.accounts.require(handler.learning_principal, 'manage')
    if ladder is None:
        handler.send({'error': '학습 사다리가 연결되지 않았습니다.'}, 503)
    elif path == PREFIX + 'decision':
        handler.send(dict(ladder.decide(handler.learning_principal['user_id'], body), best_round_id=ladder.best()))
    elif path == PREFIX + 'start':
        if ladder.start(body):
            handler.send({'started': True})
        else:
            handler.send({'error': '다른 라운드가 실행 중입니다. 끝난 뒤 시작하세요.'}, 409)
    else:
        handler.send({'error': '사다리 경로를 확인하세요.'}, 404)
    return True
