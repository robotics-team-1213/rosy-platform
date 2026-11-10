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
TWO_ARM_SCHEMA = 'rosy.omx-two-arm-run.v1'
TWO_ARM_ROUND_SCHEMA = 'rosy.omx-two-arm-round.v1'
TWO_ARM_TASKS = ('stack', 'rehandle')
TWO_ARM_COMPARE_SCHEMA = 'rosy.omx-two-arm-compare.v1'
COMPARE_MODES = ('one-arm-A', 'one-arm-B', 'two-arm')
COMPARE_SCENARIOS = ('stack', 'outbound')
VIDEO_FOLDERS = ('two_arm_rounds', 'two_arm_compare')
STATUSES = {'pending', 'running', 'passed', 'failed', 'blocked', 'not_run'}
IMAGES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
VIDEO_LIMIT = 64 << 20  # a whole task at 640x480; shortcut: sent whole, no range requests, so the player cannot seek before it has loaded
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
    out.update({key: scalar(raw.get(key)) for key in ('claim', 'reason', 'started_at', 'finished_at', 'run_id', 'result',
                                                      'stage_order', 'track', 'role', 'scenario')})
    out['artifacts'] = artifacts(raw.get('artifacts'))
    if isinstance(raw.get('eval'), dict):
        ev = raw['eval']
        out['eval'] = {**{key: scalar(ev.get(key)) for key in ('n', 'seed_base', 'lifted', 'xy_err_mm_median', 'yaw_err_deg_median')},
                       'strict': flat(ev.get('strict')), 'loose': flat(ev.get('loose'))}
    if isinstance(raw.get('contract'), dict):
        out['contract'] = {key: scalar(raw['contract'].get(key)) for key in ('backend', 'passed', 'report', 'camera_hz')}
        out['contract']['checks'] = flat(raw['contract'].get('checks'))
    return out


def read_record(file):
    """One record as a dict, or None when it is missing, linked, oversized or corrupt."""
    try:
        info = file.lstat()
        if file.parent.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 1 << 20:
            return None
        value = json.loads(file.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def paired(value):
    """The round's own comparison on the parent's seeds, when it recorded one."""
    record = value.get('comparison')
    parent = record.get('parent_eval') if isinstance(record, dict) else None
    if (not isinstance(parent, dict) or not isinstance(parent.get('strict'), dict) or record.get('same_seeds') is not True
            or record.get('result') not in ('better', 'worse', 'unclear')):
        return None
    return {'against': scalar(record.get('against')), 'result': record['result'],
            'placed': scalar(parent['strict'].get('placed')), 'n': scalar(parent.get('n'))}


def two_arm_public(value):
    failed = value.get('failed_steps')
    roll = value.get('roll_below_floor_steps')
    views = value.get('views')
    status = value.get('status')
    stages = value.get('stages') if isinstance(value.get('stages'), dict) else None
    row = {key: scalar(value.get(key)) for key in ('run_id', 'created_at', 'task', 'seed', 'source_sha', 'reason', 'steps', 'steps_pass',
                                                   'final_ok', 'final_total', 'note', 'isaac_handoff', 'isaac_suite')}
    row.update(status=status if status in STATUSES else 'unknown',
               views=[item for item in views[:8] if isinstance(item, str) and re.fullmatch(PART, item)] if isinstance(views, list) else [],
               failed_steps=[flat(item) for item in failed[:40] if isinstance(item, dict)] if isinstance(failed, list) else [],
               roll_below_floor_steps=[scalar(item, 20) for item in roll[:40]] if isinstance(roll, list) else [])
    if stages:
        row['stages'] = {name: stage(stages.get(name)) for name in ('mujoco', 'isaac', 'gazebo')}
    return row


def two_arm_round_public(value):
    """A learned two-arm round through a whitelist: the score, never a path or a log."""
    score = value.get('eval') if isinstance(value.get('eval'), dict) else None
    stages = value.get('stages') if isinstance(value.get('stages'), dict) else None
    status, cameras, videos = value.get('status'), value.get('cameras'), value.get('artifacts')
    row = {key: scalar(value.get(key)) for key in ('round_id', 'created_at', 'finished_at', 'source_sha', 'stage', 'reason', 'claim', 'isaac_handoff', 'isaac_suite')}
    row.update(status=status if status in STATUSES else 'unknown', data=flat(value.get('data')), recipe=flat(value.get('recipe')),
               cameras=[scalar(item, 20) for item in cameras[:8]] if isinstance(cameras, list) else [],
               videos=[item for item in videos[:8] if isinstance(item, str) and re.fullmatch(PART, item) and item.endswith('.mp4')] if isinstance(videos, list) else [])
    if score:
        whole = score.get('whole')
        row['eval'] = {**{key: scalar(score.get(key)) for key in ('n', 'passed', 'lifted', 'wilson_low', 'wilson_high')}, 'per_step': flat(score.get('per_step')),
                       'whole': [flat(item) for item in whole[:12] if isinstance(item, dict)] if isinstance(whole, list) else []}
    if stages:
        row['stages'] = {name: stage(stages.get(name)) for name in ('mujoco', 'isaac', 'gazebo')}
    return row


def compare_public(value):
    """One one-arm vs two-arm comparison through a whitelist: per scenario and mode the score, holds and time, never a path or a log."""
    status, runs, videos = value.get('status'), value.get('runs'), value.get('videos')
    row = {key: scalar(value.get(key)) for key in ('run_id', 'created_at', 'finished_at', 'seed', 'source_sha', 'reason', 'claim')}
    row.update(status=status if status in STATUSES else 'unknown',
               videos=[item for item in videos[:12] if isinstance(item, str) and re.fullmatch(PART, item) and item.endswith('.mp4')] if isinstance(videos, list) else [],
               runs=[])
    for run in runs[:12] if isinstance(runs, list) else []:
        if not isinstance(run, dict) or run.get('scenario') not in COMPARE_SCENARIOS or run.get('mode') not in COMPARE_MODES:
            continue
        holds, failed = run.get('holds'), run.get('failed_steps')
        item = {key: scalar(run.get(key)) for key in ('scenario', 'mode', 'steps', 'steps_pass', 'makespan_s', 'overlap_s', 'planned_makespan_s',
                                                      'extra_transports', 'video', 'reason')}
        item.update(completed=run.get('completed') is True, concurrent=run.get('concurrent') is True, moves_per_arm=flat(run.get('moves_per_arm')),
                    holds=[flat(h) for h in holds[:8] if isinstance(h, dict)] if isinstance(holds, list) else [],
                    failed_steps=[flat(f) for f in failed[:20] if isinstance(f, dict)] if isinstance(failed, list) else [])
        row['runs'].append(item)
    return row


def public(value):
    stages = value.get('stages') if isinstance(value.get('stages'), dict) else {}
    row = {'round_id': value['round_id'], 'created_at': scalar(value.get('created_at')),
           'parent_round_id': scalar(value.get('parent_round_id')), 'source_sha': scalar(value.get('source_sha'), 40)}
    row.update({key: flat(value.get(key)) for key in ('scene', 'recipe', 'data')})
    row['stages'] = {name: stage(stages.get(name)) for name in ('mujoco', 'isaac', 'gazebo')}
    row['paired'] = paired(value)
    return row


class Ladder:
    def __init__(self, config):
        if (not isinstance(config, dict) or not KEYS <= set(config) or set(config) - KEYS
                or not all(isinstance(config[key], str) and Path(config[key]).is_absolute() for key in KEYS)):
            raise ValueError('ladder configuration needs absolute root, cell, python and lerobot_train')
        self.root, self.cell, self.python, self.train = (Path(config[key]) for key in ('root', 'cell', 'python', 'lerobot_train'))
        self.process = None
        self.two_arm_process = None  # shortcut: forgotten across an app restart, harmless because a run only writes its own folder
        self.lock = threading.Lock()

    def load(self, round_id):
        """Raw record of one round, or None when it is missing, linked, oversized or corrupt."""
        if not re.fullmatch(ROUND, round_id):
            return None
        value = read_record(self.root / 'rounds' / round_id / 'round.json')
        return value if value and value.get('schema') == SCHEMA and value.get('round_id') == round_id else None

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
            same = row['paired'] if row['paired'] and row['paired']['against'] == best['round_id'] else None
            row['comparison'] = 'current' if best['round_id'] == round_id else same['result'] if same else verdict(row, best)
            row['same_seeds'] = same is not None or (row['stages']['mujoco'].get('eval') or {}).get('seed_base') == \
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

    def two_arm_running(self):
        return bool(self.two_arm_process and self.two_arm_process.poll() is None)

    def records(self, folder, file, schema, key, shown):
        """Newest records of one kind, each through its whitelist; a missing, linked or foreign one reads as unreadable."""
        try:
            ids = sorted((p.name for p in (self.root / folder).iterdir() if re.fullmatch(ROUND, p.name)), reverse=True)
        except OSError:
            return []
        rows = []
        for record_id in ids[:SHOWN]:
            value = read_record(self.root / folder / record_id / file)
            good = value and value.get('schema') == schema and value.get(key) == record_id
            rows.append(shown(value) if good else {key: record_id, 'unreadable': True})
        return rows

    def two_arm_runs(self):
        return self.records('two_arm', 'run.json', TWO_ARM_SCHEMA, 'run_id', two_arm_public)

    def two_arm_rounds(self):
        return self.records('two_arm_rounds', 'round.json', TWO_ARM_ROUND_SCHEMA, 'round_id', two_arm_round_public)

    def two_arm_compares(self):
        return self.records('two_arm_compare', 'compare.json', TWO_ARM_COMPARE_SCHEMA, 'run_id', compare_public)

    def start_two_arm_compare(self, body):
        """Launch the fixed one-arm vs two-arm comparison; only a bounded seed reaches it. It shares the two-arm slot."""
        if set(body) != {'seed'} or type(body['seed']) is not int or not 0 <= body['seed'] <= 1000:
            raise ValueError('비교 실행 필드를 확인하세요.')
        command = [str(self.python), str(ENTRY), 'two-arm-compare', '--root', str(self.root), '--python', str(self.python),
                   '--seed', str(body['seed'])]
        with self.lock:
            if self.two_arm_running():
                return False
            self.two_arm_process = self.spawn(command, 'two-arm.log')
        return True

    def start_two_arm(self, body):
        """Launch the fixed two-arm command; only a named task and a bounded seed reach it."""
        if set(body) != {'task', 'seed'} or body['task'] not in TWO_ARM_TASKS or type(body['seed']) is not int or not 0 <= body['seed'] <= 1000:
            raise ValueError('양팔 태스크 필드를 확인하세요.')
        command = [str(self.python), str(ENTRY), 'two-arm', '--root', str(self.root), '--python', str(self.python),
                   '--task', body['task'], '--seed', str(body['seed'])]
        with self.lock:
            if self.two_arm_running():
                return False
            self.two_arm_process = self.spawn(command, 'two-arm.log')
        return True

    def spawn(self, command, log_name):
        env = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME') if key in os.environ}
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / log_name, 'wb') as log:
            return subprocess.Popen(command, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def artifact(self, round_id, rel, folder='rounds'):
        """(bytes, media type) of one run's image, or a learned round's or comparison's video; nothing outside its artifacts folder, no links."""
        suffix = Path(rel).suffix.lower()
        base = self.root / folder / round_id / 'artifacts'
        video = suffix == '.mp4' and folder in VIDEO_FOLDERS
        if suffix not in IMAGES and not video:
            raise FileNotFoundError
        target = base
        for part in rel.split('/'):
            target = target / part
        for link in [base.parent, base, *list(target.parents)[:len(rel.split('/')) - 1]]:
            if link.is_symlink():
                raise FileNotFoundError
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size > (VIDEO_LIMIT if video else 8 << 20)
                or not target.resolve().is_relative_to(base.resolve())):
            raise FileNotFoundError
        return target.read_bytes(), 'video/mp4' if video else IMAGES[suffix]

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
        with self.lock:
            if self.running():
                return False
            self.process = self.spawn(command, 'start.log')
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
    elif path == PREFIX + 'two-arm':
        handler.send({'running': ladder.two_arm_running(), 'runs': ladder.two_arm_runs()})
    elif path == PREFIX + 'two-arm-rounds':
        handler.send({'rounds': ladder.two_arm_rounds()})
    elif path == PREFIX + 'two-arm-compare':
        handler.send({'running': ladder.two_arm_running(), 'runs': ladder.two_arm_compares()})
    elif match := re.fullmatch(PREFIX + 'two-arm-compare/(' + ROUND + ')/artifacts/(' + PART + ')', path):
        try:
            raw, mime = ladder.artifact(match[1], match[2], 'two_arm_compare')
            handler.send(raw, mime=mime)
        except OSError:
            handler.send({'error': '영상을 찾을 수 없습니다.'}, 404)
    elif match := re.fullmatch(PREFIX + 'two-arm-rounds/(' + ROUND + ')/artifacts/(' + PART + ')', path):
        try:
            raw, mime = ladder.artifact(match[1], match[2], 'two_arm_rounds')
            handler.send(raw, mime=mime)
        except OSError:
            handler.send({'error': '영상을 찾을 수 없습니다.'}, 404)
    elif match := re.fullmatch(PREFIX + 'two-arm/(' + ROUND + ')/artifacts/(' + PART + ')', path):
        try:
            raw, mime = ladder.artifact(match[1], match[2], 'two_arm')
            handler.send(raw, mime=mime)
        except OSError:
            handler.send({'error': '그림을 찾을 수 없습니다.'}, 404)
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
    elif path == PREFIX + 'two-arm':
        if ladder.start_two_arm(body):
            handler.send({'started': True})
        else:
            handler.send({'error': '양팔 태스크가 이미 실행 중입니다. 끝난 뒤 시작하세요.'}, 409)
    elif path == PREFIX + 'two-arm-compare':
        if ladder.start_two_arm_compare(body):
            handler.send({'started': True})
        else:
            handler.send({'error': '양팔 태스크가 이미 실행 중입니다. 끝난 뒤 시작하세요.'}, 409)
    else:
        handler.send({'error': '사다리 경로를 확인하세요.'}, 404)
    return True
