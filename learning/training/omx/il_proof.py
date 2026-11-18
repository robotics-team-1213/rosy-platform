"""Synthetic end-to-end proof that imitation learning and its environment work. Wiring only, never evidence.

Chain (every step after the synthetic sessions runs through its real CLI in a subprocess):
synthetic closed sessions -> collection_pipeline prepare -> synthetic decisions file (reviewer
"synthetic-proof") -> collection_pipeline train (split + ACT + fresh-process eval) -> independent
native_cycle verify -> optional SmolVLA train (--smolvla) -> register_policy --dry-run ->
hub_sync prepare (never uploads). Writes <out>/proof-receipt.json; exits 1 if a requested stage fails.

    python il_proof.py --out <new dir> --device cuda [--smolvla] [--steps 20]
Run it with the python of the learning env (learning/training/env/provision_policy_gpu.sh).
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / 'learning/curation/omx/collection_pipeline.py'
CYCLE = ROOT / 'learning/training/omx/native_cycle.py'
REGISTER = ROOT / 'learning/training/omx/register_policy.py'
HUB_SYNC = ROOT / 'learning/registry/policy/hub_sync.py'
SOURCE_REPO = 'rosy-fixture/collection'
NOT_EVIDENCE = 'synthetic labels for environment and wiring proof only; not human evidence'


def make_sessions(work, count=3, frames=2):
    """Closed synthetic raw sessions; the journal is written directly and no motion backend runs."""
    sys.path.insert(0, str(ROOT / 'deploy/robot/omx'))
    from collection_profile import digest
    from collection_store import RawCollection, append, save
    sessions = []
    for i in range(count):
        source = Path(work) / f'raw-{i}'
        start = 100 + i * 100
        profile = dict(rig_revision='synthetic-rig', calibration_revision='synthetic-cal', fps=10,
                       task='synthetic pipeline fixture', camera_shapes={r: [32, 32, 3] for r in ('top', 'front')})
        teacher = dict(schema='rosy.omx-collection-teacher.v1', steps=[dict(positions=[0.] * 6, duration_s=.1)])
        store = RawCollection(source, profile, digest(teacher), 'hardware')
        save(source / 'teacher.json', teacher)
        save(source / 'profile.json', dict(reach_tolerance_rad=[.01] * 6))
        event = dict(policy='omx-photometric-v3', run_id=f'synthetic-run-{i}', profile_sha256='a' * 64,
                     recorded_ns=start, motion_admitted=False, physical_acceptance=False,
                     photometric_ready=False, observations={}, environment={r: dict(state='OBSERVING',
                         condition=None, environment_epoch=0, control_generation=0) for r in ('top', 'front')})
        append(source / 'environment.jsonl', event)
        episode = store.begin(start, event)
        command = episode['cycle_id'] + '-0'
        goal = f'synthetic-goal-{i}'
        for fact in (dict(kind='INTENT', command_id=command, step=teacher['steps'][0], time_ns=start),
                     dict(kind='SUBMISSION', command_id=command, decision=dict(accepted=True), time_ns=start + 1),
                     dict(kind='GOAL_ACCEPTED', command_id=command, goal_id=goal, sequence=1,
                          observed_at_monotonic_s=1.),
                     dict(kind='TERMINAL_RESULT', command_id=command, goal_id=goal, sequence=2,
                          observed_at_monotonic_s=2., status=4, result_code=0),
                     dict(kind='TERMINAL', command_id=command, time_ns=start + 3,
                          result=dict(succeeded=True, source='native_follow_joint_trajectory')),
                     dict(kind='REACHED', command_id=command, time_ns=start + 4, errors_rad=[0.] * 6,
                          tolerance_rad=[.01] * 6)):
            append(source / 'events.jsonl', fact)
        observation = dict(time_ns=start + 1, observation_state=[0.] * 6, action=[float(i + 1)] * 6,
                           joint_positions=[.01, .02, .03, .04, .05, .06],
                           joint_source_stamp=1. + i, reference_source_stamp=1. + i,
                           images={r: dict(data=bytes([100, 110, 120]) * 1024, width=32, height=32,
                                           source_stamp=1. + i) for r in ('top', 'front')})
        for frame in range(frames):
            observation.update(time_ns=start + frame + 1, joint_source_stamp=1. + i + frame / 10,
                               reference_source_stamp=1. + i + frame / 10)
            for image in observation['images'].values():
                image['source_stamp'] = 1. + i + frame / 10
            store.sample(episode, observation, [0.] * 6)
        episode.update(complete=True, reason='', end_ns=start + 10)
        store.close(dict(hold_requested=True, terminal_observed=True, physical_stop_verified=False))
        sessions.append(source)
    return sessions


def synthetic_decisions(prepared, output):
    """One success per split; the file and a sibling note say these labels are not human evidence."""
    rows = json.loads((Path(prepared) / 'decisions.json').read_text(encoding='utf-8'))
    if len(rows) != 3:
        raise ValueError(f'expected 3 inspected episodes, got {len(rows)}')
    for row, split in zip(rows, ('train', 'eval', 'test')):
        row.update(outcome='success', split=split, reviewer='synthetic-proof', reason=NOT_EVIDENCE)
    output = Path(output)
    output.write_text(json.dumps(rows, indent=2), encoding='utf-8')
    output.with_name('SYNTHETIC-NOT-EVIDENCE.txt').write_text(NOT_EVIDENCE + '\n', encoding='utf-8')
    return output


def fingerprint():
    result = dict(python=sys.version.split()[0], platform=platform.platform(), packages={})
    for name in ('lerobot', 'torch', 'torchvision', 'transformers', 'numpy', 'safetensors'):
        try:
            result['packages'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result['packages'][name] = None
    try:
        import torch
        result['cuda'] = dict(available=bool(torch.cuda.is_available()), torch_cuda=torch.version.cuda,
                              device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
    except Exception as exc:
        result['cuda'] = dict(available=False, error=type(exc).__name__)
    result['code_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in (Path(__file__), PIPELINE, CYCLE, REGISTER, HUB_SYNC)}
    return result


def find_snapshot(repo, override):
    if override:
        return Path(override)
    cache = Path(os.environ.get('HF_HUB_CACHE') or Path(os.environ.get('HF_HOME', '~/.cache/huggingface')).expanduser() / 'hub')
    found = sorted((p for p in (cache / f'models--{repo.replace("/", "--")}' / 'snapshots').glob('*')
                    if (p / 'config.json').is_file()), key=lambda p: p.stat().st_mtime)
    if not found:
        raise ValueError(f'{repo} not in the local HF cache ({cache}); pass the path explicitly (no download is attempted)')
    return found[-1]


def vlm_metadata(source, output):
    """SmolVLA wants a metadata-only directory (no weights); copy just the allowed files."""
    sys.path.insert(0, str(ROOT / 'contracts/learning/src'))
    from rosy.contracts.learning.policy_assets import VLM_FILES
    output.mkdir()
    for name in sorted(VLM_FILES):
        if (source / name).is_file():
            (output / name).write_bytes((source / name).read_bytes())
    return output


class Proof:
    def __init__(self, out):
        self.out, self.stages, self.failed = Path(out), [], False
        self.env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1'}

    def run(self, label, argv, timeout):
        """Run one real CLI; log to <out>/logs/<label>.log; return stdout; raise with the log tail on failure."""
        log = self.out / 'logs' / f'{label}.log'
        # Own session: on timeout the whole trainer tree (pipeline -> train -> lerobot) is killed, not left on the GPU.
        with subprocess.Popen([sys.executable, *map(str, argv)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env=self.env, start_new_session=True) as child:
            try:
                stdout, stderr = child.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL) if hasattr(os, 'killpg') else child.kill()
                child.communicate()
                raise
        done = argparse.Namespace(returncode=child.returncode, stdout=stdout, stderr=stderr)
        log.write_text(f'$ {argv}\n--- stdout\n{done.stdout}\n--- stderr\n{done.stderr}', encoding='utf-8')
        if done.returncode:
            raise RuntimeError(f'{label} exited {done.returncode}: {(done.stderr or done.stdout)[-1500:]} (log: {log})')
        return done.stdout

    def stage(self, name, function):
        if self.failed:
            self.stages.append(dict(name=name, status='skipped', reason='an earlier stage failed'))
            return None
        start = time.monotonic()
        try:
            detail, status = function() or {}, 'passed'
        except Exception as exc:  # a stage failure must reach the receipt, not a traceback
            detail, status, self.failed = dict(error=f'{type(exc).__name__}: {exc}'[-2500:]), 'failed', True
        self.stages.append(dict(name=name, status=status, seconds=round(time.monotonic() - start, 2), **detail))
        return detail


def _finite(values):
    return bool(values) and all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _cycle(run_dir, policy, device):
    root = Path(run_dir)
    cycle = json.loads((root / 'training/cycle-receipt.json').read_text(encoding='utf-8'))
    config = json.loads((root / 'training/train-config.json').read_text(encoding='utf-8'))
    evaluation = cycle['evaluation']
    if cycle['policy_type'] != policy or not (cycle['offline_only'] and not cycle['promotion']):
        raise ValueError('cycle receipt is not an offline unpromoted ' + policy + ' run')
    if config['policy']['device'] != device:
        raise ValueError(f"trainer ran on {config['policy']['device']}, requested {device}")
    if evaluation['samples'] < 1 or not _finite(evaluation['mae_per_joint']):
        raise ValueError('evaluation has no samples or a non-finite error')
    return cycle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True, help='new directory; must not exist')
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--steps', type=int, default=20, help='ACT optimizer steps')
    parser.add_argument('--batch-size', type=int, default=1)
    parser.add_argument('--frames', type=int, default=2, help='frames per synthetic session')
    parser.add_argument('--smolvla', action='store_true', help='also run a few SmolVLA steps (needs the GPU env + local base)')
    parser.add_argument('--smolvla-steps', type=int, default=2)
    parser.add_argument('--smolvla-base', type=Path, help='default: lerobot/smolvla_base in the local HF cache')
    parser.add_argument('--smolvla-vlm-source', type=Path, help='default: HuggingFaceTB/SmolVLM2-500M-Video-Instruct in the local HF cache')
    parser.add_argument('--timeout', type=int, default=3600, help='seconds per subprocess')
    args = parser.parse_args(argv)
    if args.steps < 1 or args.batch_size < 1 or args.frames < 1 or args.smolvla_steps < 1:
        parser.error('step, batch and frame counts must be positive')
    out = args.out.resolve()
    out.mkdir(parents=True)  # refuses an existing run: never overwrite a previous proof
    (out / 'logs').mkdir()
    proof = Proof(out)
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    state = {}

    def env_stage():
        info = fingerprint()
        state['env'] = info
        if info['packages']['lerobot'] is None or info['packages']['torch'] is None:
            raise ValueError('lerobot/torch are not installed in this python; use the policy-gpu env')
        if args.device == 'cuda' and not info['cuda']['available']:
            raise ValueError('--device cuda requested but torch.cuda is not available')
        if args.smolvla and info['packages']['transformers'] is None:
            raise ValueError('--smolvla needs transformers in this python')
        return dict(device_requested=args.device, cuda=info['cuda'])

    def sessions_stage():
        state['sessions'] = make_sessions(out / 'raw', frames=args.frames)
        return dict(sessions=[str(p) for p in state['sessions']], frames_per_session=args.frames)

    def prepare_stage():
        state['prepared'] = out / 'prepared'
        proof.run('prepare', [PIPELINE, 'prepare', *state['sessions'], '--out', state['prepared'],
                                     '--repo-id', SOURCE_REPO], args.timeout)
        info = json.loads((state['prepared'] / 'intake-receipt.json').read_text(encoding='utf-8'))
        if info.get('reader_verified') is not True:
            raise ValueError('prepared dataset reader was not verified')
        return dict(prepared=str(state['prepared']), reader_verified=True)

    def decisions_stage():
        state['decisions'] = synthetic_decisions(state['prepared'], out / 'synthetic-decisions.json')
        return dict(decisions=str(state['decisions']), reviewer='synthetic-proof', human_evidence=False)

    def train_stage(policy, label, steps, extra=()):
        def go():
            run = out / label
            proof.run(label, [PIPELINE, 'train', state['prepared'], '--decisions', state['decisions'], '--out', run,
                              '--steps', steps, '--batch-size', args.batch_size, '--device', args.device,
                              '--policy', policy, *extra], args.timeout)
            cycle = _cycle(run, policy, args.device)
            splits = json.loads((run / 'splits/split-receipt.json').read_text(encoding='utf-8'))['splits']
            if splits != dict(train=[0], eval=[1], test=[2]):
                raise ValueError(f'unexpected split {splits}')
            for marker_dir in (run, run / 'training'):  # downstream tools read these dirs, not the out root
                (marker_dir / 'SYNTHETIC-NOT-EVIDENCE.txt').write_text(NOT_EVIDENCE + '\n', encoding='utf-8')
            state[label] = run
            return dict(run=str(run), steps=steps, device=args.device, split=splits,
                        policy_revision=cycle['policy_revision'], eval_samples=cycle['evaluation']['samples'],
                        eval_mae_per_joint=cycle['evaluation']['mae_per_joint'])
        return go

    def model_dir(label):
        return state[label] / 'training/trainer/checkpoints/last/pretrained_model'

    def verify_stage():
        target = out / 'independent-eval-act.json'
        proof.run('verify-act', [CYCLE, 'verify', '--model', model_dir('act'), '--splits', state['act'] / 'splits',
                                 '--repo-id', SOURCE_REPO, '--out', target], args.timeout)
        fresh = json.loads(target.read_text(encoding='utf-8'))
        first = json.loads((state['act'] / 'training/evaluation.json').read_text(encoding='utf-8'))
        gap = max(abs(a - b) for a, b in zip(fresh['mae_per_joint'], first['mae_per_joint']))
        if not (fresh['model_reloaded_in_new_process'] and fresh['samples'] == first['samples']
                and _finite(fresh['mae_per_joint']) and gap <= 1e-3):
            raise ValueError(f'independent reload differs from the cycle evaluation (max gap {gap})')
        return dict(evaluation=str(target), max_mae_gap=gap, samples=fresh['samples'])

    def smolvla_stage():
        base = find_snapshot('lerobot/smolvla_base', args.smolvla_base)
        vlm_source = find_snapshot('HuggingFaceTB/SmolVLM2-500M-Video-Instruct', args.smolvla_vlm_source)
        vlm = vlm_metadata(vlm_source, out / 'vlm-assets')
        detail = train_stage('smolvla', 'smolvla', args.smolvla_steps,
                             ('--base-model', base, '--vlm-assets', vlm))()
        return dict(detail, base_model=str(base), vlm_assets=str(vlm))

    def register_stage():
        text = proof.run('register-dry-run', [REGISTER, '--cycle', state['act'] / 'training', '--fleet',
                                              'https://fleet.invalid', '--workcell', 'proof-cell', '--dry-run'],
                         args.timeout)
        body = json.loads(text)
        if body['to_stage'] != 'L0' or not body['policy_revision'].startswith('act-'):
            raise ValueError('proposal is not an ACT L0 body')
        return dict(proposal=body, sent=False)

    def hub_stage():
        source = model_dir('act').resolve()
        files = sorted(p.name for p in source.iterdir()
                       if p.is_file() and p.suffix in ('.json', '.safetensors') and not p.name.startswith('.'))
        bundle = out / 'hub-bundle'
        manifest = json.loads(proof.run('hub-prepare', [HUB_SYNC, 'prepare', source, '--out', bundle,
                              '--repo-id', 'rosy-proof/synthetic-act', '--repo-type', 'model',
                              *[x for f in files for x in ('--file', f)]], args.timeout))
        if set(manifest['files']) != set(files) or (bundle / 'receipt.json').exists():
            raise ValueError('bundle manifest differs from the selected files')
        (bundle / 'SYNTHETIC-NOT-EVIDENCE.txt').write_text(NOT_EVIDENCE + '\n', encoding='utf-8')
        return dict(bundle=str(bundle), files=len(files), uploaded=False)

    proof.stage('env', env_stage)
    proof.stage('synthetic_sessions', sessions_stage)
    proof.stage('prepare', prepare_stage)
    proof.stage('synthetic_decisions', decisions_stage)
    proof.stage('train_act', train_stage('act', 'act', args.steps))
    proof.stage('independent_eval_act', verify_stage)
    if args.smolvla:
        proof.stage('train_smolvla', smolvla_stage)
    proof.stage('register_dry_run', register_stage)
    proof.stage('hub_prepare', hub_stage)
    receipt = dict(schema='rosy.il-proof-receipt/1', synthetic=True, evidence_of='environment and wiring only',
                   uploaded=False, promotion=False, device_execution=False,
                   requested=dict(device=args.device, act_steps=args.steps, smolvla=args.smolvla,
                                  batch_size=args.batch_size, frames=args.frames),
                   started_utc=started, finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   out=str(out), env=state.get('env'), stages=proof.stages,
                   ok=all(s['status'] == 'passed' for s in proof.stages))
    (out / 'proof-receipt.json').write_text(json.dumps(receipt, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(ok=receipt['ok'], receipt=str(out / 'proof-receipt.json'),
                          stages={s['name']: s['status'] for s in proof.stages})))
    return 0 if receipt['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())