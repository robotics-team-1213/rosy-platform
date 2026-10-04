"""Local policy metadata ledger; never dispatches or grants actuator authority."""
import argparse
from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from dataset_store import DatasetStore

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'contracts/learning/src'))
from rosy.contracts.learning import seal, validate_policy, validate_promotion  # noqa: E402


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    with Path(path).open('w', encoding='utf-8') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def act_assessment(report):
    if report.get('algorithm') != 'lerobot-act':
        raise ValueError('unsupported ACT report algorithm')
    for key in ('mae_rad', 'constant_baseline_mae_rad'):
        val = report.get(key)
        if type(val) not in (int, float) or not math.isfinite(val) or val < 0:
            raise ValueError('invalid ACT error metric')
    for key in ('limit_violations', 'target_clusters_0_001_rad', 'eval_frames'):
        if type(report.get(key)) is not int or report[key] < 0:
            raise ValueError('invalid ACT count metric')
    reasons = []
    if report['eval_frames'] < 1 or report.get('reloaded_prediction_verified') is not True:
        reasons.append('evaluation_or_reload_unverified')
    if report['target_clusters_0_001_rad'] < 3:
        reasons.append('insufficient_target_diversity')
    if report['limit_violations']:
        reasons.append('joint_limit_violation')
    if report['mae_rad'] >= report['constant_baseline_mae_rad']:
        reasons.append('does_not_beat_constant_target_baseline')
    expected = 'reject' if reasons else 'offline_only'
    if report.get('verdict') != expected:
        raise ValueError('ACT claimed verdict differs from recomputed metrics')
    return {'verdict': expected, 'reasons': reasons,
            'independent_task_success': report.get('independent_task_success', 'unverified'),
            'validator': 'rosy-act-research-gate/1'}


def pinky_assessment(report):
    if (report.get('schema') != 'rosy.pinky-offline-eval/1'
            or report.get('model') not in ('tiny_cnn', 'rgb_ridge')
            or report.get('target') != 'recorded_core_final_velocity'
            or report.get('expert_status') != 'unverified'):
        raise ValueError('unsupported recorded Pinky evaluation semantics')
    for key in ('mae_m_s', 'mae_rad_s', 'zero_mae_m_s', 'zero_mae_rad_s',
                'constant_mae_m_s', 'constant_mae_rad_s'):
        value = report.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid Pinky error metric')
    for key in ('eval_frames', 'prediction_limit_violations'):
        if type(report.get(key)) is not int or report[key] < 0:
            raise ValueError('invalid Pinky count metric')
    reasons = ['recorded_velocity_expert_intent_unverified']
    if report['eval_frames'] == 0 or report.get('reloaded_prediction_verified') is not True:
        reasons.append('evaluation_or_reload_unverified')
    if report['prediction_limit_violations']:
        reasons.append('nominal_profile_velocity_limit_violation')
    for unit in ('m_s', 'rad_s'):
        if report[f'mae_{unit}'] >= min(report[f'zero_mae_{unit}'], report[f'constant_mae_{unit}']):
            reasons.append(f'does_not_beat_velocity_baseline_{unit}')
    if report.get('verdict') != 'reject':
        raise ValueError('Pinky claimed verdict differs from recorded-velocity gate')
    return {'verdict': 'reject', 'reasons': reasons, 'independent_task_success': 'unverified',
            'validator': 'rosy-pinky-recorded-velocity-research-gate/1'}


class Registry:
    def __init__(self, root, *, trusted=None):
        self.root = Path(root).resolve()
        if self.root.drive.upper() == 'F:':
            raise ValueError('registry output belongs outside source drive F:')
        self.root.mkdir(parents=True, exist_ok=True)
        self.trusted = {}
        for principal, trust in (trusted or {}).items():
            if (not isinstance(principal, str) or not principal.strip() or not isinstance(trust, dict)
                    or set(trust) != {'key', 'kinds'} or not isinstance(trust['key'], bytes)
                    or len(trust['key']) < 32 or not isinstance(trust['kinds'], (set, frozenset))
                    or not trust['kinds'] or any(not isinstance(k, str) or not k for k in trust['kinds'])):
                raise ValueError('invalid installed verifier trust')
            self.trusted[principal] = {'key': trust['key'], 'kinds': frozenset(trust['kinds'])}
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS policies (revision TEXT PRIMARY KEY, stage TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, body TEXT NOT NULL)')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.root / 'registry.sqlite3', timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _audit(self, db):
        events, stages, previous = [], {}, '0' * 64
        for index, (sequence, body) in enumerate(db.execute('SELECT sequence, body FROM events ORDER BY sequence'), 1):
            try:
                event = json.loads(body)
                valid = (sequence == index and event['sequence'] == sequence
                         and event['previous'] == previous and seal(event) == event)
                revision = event['policy_revision']
                if event['operation'] == 'register':
                    valid &= revision not in stages and event['from_stage'] is None and event['to_stage'] == 'unregistered'
                else:
                    valid &= revision in stages and event['from_stage'] == stages.get(revision)
                if event['operation'] == 'assessment':
                    valid &= event['from_stage'] == event['to_stage']
                elif event['operation'] == 'promote':
                    levels = ['unregistered', 'L0', 'L1', 'L2', 'L3']
                    valid &= levels.index(event['to_stage']) == levels.index(event['from_stage']) + 1
                elif event['operation'] != 'register':
                    valid = False
                if not valid:
                    raise ValueError('event chain differs')
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError('registry event chain differs') from exc
            stages[revision] = event['to_stage']
            previous = event['revision']
            events.append(event)
        if dict(db.execute('SELECT revision, stage FROM policies')) != stages:
            raise ValueError('registry stage differs from event chain')
        for revision in stages:
            self._policy(revision)
        for event in events:
            if event['operation'] == 'promote':
                promotion = event['data']['promotion']
                _, policy = self._policy(event['policy_revision'])
                DatasetStore(self.root / 'datasets').require_policy(policy)
                validate_promotion(promotion, policy, root=self.root / 'evidence' / promotion['revision'])
        return events

    def _policy(self, revision):
        if not isinstance(revision, str) or len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
            raise ValueError('policy revision required')
        root = self.root / 'artifacts' / revision
        policy = validate_policy(read(root / 'policy-artifact.json'), root=root)
        if policy['revision'] != revision:
            raise ValueError('snapshot policy revision differs')
        return root, policy

    def _append(self, db, operation, revision, previous_stage, next_stage, data):
        events = self._audit(db)
        event = seal({'sequence': len(events) + 1, 'previous': events[-1]['revision'] if events else '0' * 64,
                      'operation': operation, 'policy_revision': revision, 'from_stage': previous_stage,
                      'to_stage': next_stage, 'data': data})
        db.execute('INSERT INTO events VALUES (?, ?)', (event['sequence'], canonical(event)))
        db.execute('INSERT INTO policies VALUES (?, ?) ON CONFLICT(revision) DO UPDATE SET stage=excluded.stage',
                   (revision, next_stage))
        return {'policy_revision': revision, 'stage': next_stage, 'event_revision': event['revision']}

    def _snapshot(self, source, destination, refs, *, document=None):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=self.root) as scratch:
            stage = Path(scratch) / 'files'
            stage.mkdir()
            for ref in refs:
                target = stage / ref['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / ref['path'], target)
                with target.open('r+b') as stream:
                    if hashlib.sha256(stream.read()).hexdigest() != ref['sha256'] or target.stat().st_size != ref['bytes']:
                        raise ValueError('snapshot file hash differs')
                    os.fsync(stream.fileno())
            if document is not None:
                write(stage / 'policy-artifact.json', document)
                validate_policy(document, root=stage)
            if destination.exists():
                for path in stage.rglob('*'):
                    if path.is_file() and path.read_bytes() != (destination / path.relative_to(stage)).read_bytes():
                        raise ValueError('existing snapshot differs')
            else:
                os.replace(stage, destination)

    def register(self, source):
        source = Path(source).resolve()
        policy = validate_policy(read(source / 'policy-artifact.json'), root=source)
        revision = policy['revision']
        with self._db() as db:
            self._audit(db)
            current = db.execute('SELECT stage FROM policies WHERE revision=?', (revision,)).fetchone()
            if current:
                self._policy(revision)
                return {'policy_revision': revision, 'stage': current[0]}
            refs = policy['files'] + [policy['normalization']] + policy['evaluations']
            self._snapshot(source, self.root / 'artifacts' / revision, refs, document=policy)
            return self._append(db, 'register', revision, None, 'unregistered', {'artifact_revision': revision})

    def history(self):
        with self._db() as db:
            return self._audit(db)

    def show(self, revision):
        history = [e for e in self.history() if e['policy_revision'] == revision]
        if not history:
            raise ValueError('policy not registered')
        return {'policy_revision': revision, 'stage': history[-1]['to_stage'], 'events': history}

    def _act_reports(self, root, policy):
        reports = []
        for ref in policy['evaluations']:
            try:
                report = read(root / ref['path'])
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(report, dict) and report.get('algorithm') == 'lerobot-act':
                reports.append((report, ref))
        return reports

    def _act(self, root, policy):
        reports = self._act_reports(root, policy)
        if len(reports) != 1:
            raise ValueError('one bound ACT offline report required')
        return act_assessment(reports[0][0]), reports[0][1]

    def assess_act(self, revision):
        with self._db() as db:
            events = self._audit(db)
            stage = db.execute('SELECT stage FROM policies WHERE revision=?', (revision,)).fetchone()
            if not stage:
                raise ValueError('policy not registered')
            root, policy = self._policy(revision)
            result, ref = self._act(root, policy)
            data = {**result, 'report': ref}
            if any(e['operation'] == 'assessment' and e['policy_revision'] == revision
                   and e['data'] == data for e in events):
                return data
            self._append(db, 'assessment', revision, stage[0], stage[0], data)
            return data

    def _pinky(self, root, policy):
        reports = []
        for ref in policy['evaluations']:
            report = read(root / ref['path'])
            if isinstance(report, dict) and report.get('schema') == 'rosy.pinky-offline-eval/1':
                reports.append((report, ref))
        if len(reports) != 1:
            raise ValueError('one bound Pinky offline report required')
        return pinky_assessment(reports[0][0]), reports[0][1]

    def assess_pinky(self, revision):
        with self._db() as db:
            events = self._audit(db)
            stage = db.execute('SELECT stage FROM policies WHERE revision=?', (revision,)).fetchone()
            if not stage:
                raise ValueError('policy not registered')
            root, policy = self._policy(revision)
            if policy['profile'] != 'pinky_base_velocity_v1':
                raise ValueError('Pinky policy profile required')
            result, ref = self._pinky(root, policy)
            data = {**result, 'report': ref}
            if any(e['operation'] == 'assessment' and e['policy_revision'] == revision
                   and e['data'] == data for e in events):
                return data
            self._append(db, 'assessment', revision, stage[0], stage[0], data)
            return data

    def _receipt(self, receipt, promotion, check):
        if not isinstance(receipt, dict) or set(receipt) != {'principal', 'payload', 'signature'}:
            raise ValueError('invalid verifier receipt')
        trust = self.trusted.get(receipt['principal'])
        if not trust or check['kind'] not in trust['kinds']:
            raise ValueError('missing scoped verifier trust')
        expected = {'promotion_revision': promotion['revision'], 'policy_revision': promotion['policy_revision'],
                    'kind': check['kind'], 'report_sha256': check['report']['sha256'], 'verdict': 'pass'}
        signature = hmac.new(trust['key'], canonical(expected).encode(), hashlib.sha256).hexdigest()
        if receipt['payload'] != expected or not isinstance(receipt['signature'], str) or not hmac.compare_digest(receipt['signature'], signature):
            raise ValueError('verifier receipt binding/signature differs')

    def promote(self, promotion, evidence_root, receipts):
        evidence_root = Path(evidence_root).resolve()
        revision = promotion['policy_revision']
        with self._db() as db:
            self._audit(db)
            current = db.execute('SELECT stage FROM policies WHERE revision=?', (revision,)).fetchone()
            if not current or current[0] != promotion['from_stage']:
                raise ValueError('promotion current stage differs')
            root, policy = self._policy(revision)
            promotion = validate_promotion(promotion, policy, root=evidence_root)
            DatasetStore(self.root / 'datasets').require_policy(policy)
            if policy['profile'] == 'pinky_base_velocity_v1' and self._pinky(root, policy)[0]['verdict'] == 'reject':
                raise ValueError('bound Pinky offline evaluation rejected')
            # A separate pass claim cannot override the artifact's failed ACT report.
            for report, _ in self._act_reports(root, policy):
                if act_assessment(report)['verdict'] == 'reject':
                    raise ValueError('bound ACT offline evaluation rejected')
            checks = list(promotion['checks'])
            if promotion['authority'] is not None:
                checks.append({'kind': 'operating_authority', 'report': promotion['authority']['approval']})
            if not isinstance(receipts, list) or len(receipts) != len(checks):
                raise ValueError('one trusted receipt per check required')
            for check in checks:
                matched = [r for r in receipts if isinstance(r, dict) and isinstance(r.get('payload'), dict)
                           and r['payload'].get('kind') == check['kind']]
                if len(matched) != 1:
                    raise ValueError('unique verifier receipt required')
                self._receipt(matched[0], promotion, check)
                report = read(evidence_root / check['report']['path'])
                if report.get('policy_revision') != revision or report.get('kind') != check['kind'] or report.get('verdict') != 'pass':
                    raise ValueError('actual report binding/verdict differs')
            refs = [check['report'] for check in checks]
            self._snapshot(evidence_root, self.root / 'evidence' / promotion['revision'], refs)
            return self._append(db, 'promote', revision, current[0], promotion['to_stage'],
                                {'promotion': promotion, 'receipts': receipts})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('register').add_argument('source', type=Path)
    sub.add_parser('assess-act').add_argument('revision')
    sub.add_parser('assess-pinky').add_argument('revision')
    sub.add_parser('show').add_argument('revision')
    sub.add_parser('history')
    args = parser.parse_args()
    registry = Registry(args.root)
    if args.command == 'register':
        result = registry.register(args.source)
    elif args.command == 'assess-act':
        result = registry.assess_act(args.revision)
    elif args.command == 'assess-pinky':
        result = registry.assess_pinky(args.revision)
    elif args.command == 'show':
        result = registry.show(args.revision)
    else:
        result = registry.history()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
