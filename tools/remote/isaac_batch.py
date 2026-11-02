"""Run a list of Isaac runs on every declared simulation host, resuming only what is unfinished.

A plan is {"scenario": ..., "sha": ..., "runs": {"<name>": {<config>}}}, or a grid {"scenario", "sha",
"config": {<shared>}, "case_prefix": "...", "cases": [...], "seeds": [...]} that expands to "<case>-s<seed>".
Each run lives in <out>/<name>/: result.json means done (skipped on a rerun); a receipt.json without a result
means a run was started, so it is polled and fetched on the host that owns it, never started again; anything
else is started fresh. A host that stays busy retires and the other hosts take its share. Rerun the same command
after a stop or a lost host. --pause ROLE=unit[,unit] borrows those role units before each run on that host, only while
the role is idle (D-958, deploy/hosts/gpu_tenants.py on the host decides and restores them; Isaac admission
wants no other GPU process).
<out>/summary.tsv lists every run with placed count and the worst unstable box.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remote_isaac  # noqa: E402

TERMINAL = remote_isaac.TERMINAL


def expand(plan):
    """A grid plan becomes explicit runs; an explicit plan is returned unchanged."""
    if 'runs' in plan:
        return plan
    runs = {f'{case}-s{seed}': dict(plan.get('config', {}), seed=seed, case=plan.get('case_prefix', '') + case)
            for case in plan['cases'] for seed in plan['seeds']}
    return {'scenario': plan['scenario'], 'sha': plan['sha'], 'runs': runs}


def pauses(values):
    """['ai=rosy-ollama.service'] -> {'ai': ['rosy-ollama.service']}, refusing anything but unit names."""
    found = {}
    for value in values:
        role, _, units = value.partition('=')
        names = units.split(',')
        if role not in ('model', 'ai') or not all(re.fullmatch(r'[A-Za-z0-9@._-]+\.service', n) for n in names):
            raise ValueError('--pause takes model|ai=unit.service[,unit.service]')
        found.setdefault(role, []).extend(names)
    return found


def service_window(remotes, paused, run, log=print):
    """Run, then hand every lent unit back. Each run borrows them first (run_batch `lend`); the host's
    rosy-gpu-tenants timer restores them anyway if this process dies (D-958)."""
    try:
        return run()
    finally:
        for remote in remotes:
            if paused.get(remote.role):
                log(f"[{remote.role}] {remote.tenants('release', paused[remote.role])}")


def row(name, value, detail):
    summary = detail.get('summary') or {}
    worst = max(summary.get('unstable') or [{}], key=lambda u: u.get('position_error_mm', 0))
    return '\t'.join(str(v) for v in (
        name, value, detail.get('role', ''), detail.get('status', ''),
        f"{summary['placed']}/{summary['planned']}" if 'placed' in summary else '',
        f"box{worst['box']} {worst['position_error_mm']} mm" if 'box' in worst else '',
        ','.join(summary.get('failures') or [])))


def state(directory):
    if (directory / 'result.json').is_file():
        return 'done'
    return 'started' if (directory / 'receipt.json').is_file() else 'new'


def _set_aside(directory):
    """A run directory with a request but no receipt never started: keep it beside, start clean."""
    if directory.exists():
        for n in range(1, 1000):
            kept = directory.with_name(f'{directory.name}.stale-{n}')
            if not kept.exists():
                directory.rename(kept)
                return


def resume(directory, remote, *, sleep, fetch, interval, max_polls, max_errors):
    receipt, errors = directory / 'receipt.json', 0
    for _ in range(max_polls):
        try:
            row, errors = remote_isaac.observe(receipt, remote), 0
        except (ConnectionError, OSError):
            errors += 1
            if errors > max_errors:
                raise
            sleep(interval)
            continue
        if row['status'] in TERMINAL or row['status'] == 'UNKNOWN':
            break
        sleep(interval)
    else:
        raise ValueError('Run still active')
    snapshot = None
    if row['status'] in TERMINAL and (row.get('result') or {}).get('reason') != 'admission_refused':
        snapshot = fetch(remote_isaac.read_receipt(receipt), remote, directory / 'snapshots')
    return {'run_id': row['run_id'], 'status': row['status'], 'result': row.get('result'),
            'snapshot_directory': str(snapshot) if snapshot else None}


def run_batch(plan, out, remotes, *, sleep=time.sleep, fetch=None, summarize=remote_isaac.summarize,
              attempts=4, interval=30, max_polls=240, max_errors=10, busy_limit=3, job_errors=3, log=print, lend=None):
    """Return {name: state}. Every worker takes the next unclaimed run; a started run only goes to its owner."""
    lend = lend or {}
    fetch = fetch or remote_isaac.fetch_snapshot
    out.mkdir(parents=True, exist_ok=True)
    names, claimed, failures, lock = list(plan['runs']), set(), {}, threading.Lock()

    def owner(name):
        try:
            return remote_isaac.read_receipt(out / name / 'receipt.json').get('target_id')
        except (OSError, ValueError):
            return None

    def claim(remote):
        with lock:
            for name in names:
                directory = out / name
                current = state(directory)
                if name in claimed or current == 'done' or failures.get(name, 0) >= job_errors:
                    continue
                if current == 'started' and owner(name) != remote.target_id:
                    continue
                claimed.add(name)
                return name, current
        return None, None

    def work(remote):
        busy = 0
        while busy < busy_limit:
            name, current = claim(remote)
            if name is None:
                return
            directory = out / name
            try:
                if current == 'started':
                    if lend.get(remote.role):  # a run already holds the GPU: mark the lent units so the host restores them
                        remote.tenants('claim', lend[remote.role])
                    result = resume(directory, remote, sleep=sleep, fetch=fetch, interval=interval,
                                    max_polls=max_polls, max_errors=max_errors)
                else:
                    if lend.get(remote.role):  # D-958: the role service lends the GPU only while its role is idle
                        answer = remote.tenants('claim', lend[remote.role])
                        if answer != 'claimed':
                            raise remote_isaac.NotReady(answer)
                    _set_aside(directory)
                    result = remote_isaac.run_experiment(plan['scenario'], plan['runs'][name], plan['sha'], directory,
                        remote, sleep=sleep, fetch=fetch, attempts=attempts, interval=interval,
                        max_polls=max_polls, max_errors=max_errors)
                busy = 0
                if result['status'] in TERMINAL:
                    remote_isaac._save(directory / 'result.json', dict(summarize(result), name=name, role=remote.role))
                log(f"{name} [{remote.role}] {result['status']}")
            except remote_isaac.NotReady:  # nothing started: hand the run back, back off this host
                busy += 1
                log(f'{name} [{remote.role}] host busy ({busy}/{busy_limit})')
                sleep(interval)
            except (ValueError, OSError, ConnectionError) as exc:
                with lock:
                    failures[name] = failures.get(name, 0) + 1
                log(f'{name} [{remote.role}] interrupted: {exc}; rerun resumes it')
            finally:
                with lock:
                    claimed.discard(name)
        log(f'[{remote.role}] retired: host stayed busy')

    threads = [threading.Thread(target=work, args=(remote,)) for remote in remotes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {name: state(out / name) for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--roles', default='model,ai', help='comma-separated sim_hosts roles to use')
    parser.add_argument('--status', action='store_true', help='only list run states')
    parser.add_argument('--busy-limit', type=int, default=3, help='busy checks (about 2.5 min each) before a host retires')
    parser.add_argument('--pause', action='append', default=[], help='ROLE=unit.service[,unit.service] stopped for the batch')
    args = parser.parse_args()
    plan, paused = expand(remote_isaac._json(args.plan)), pauses(args.pause)
    if args.status:
        states = {name: state(args.out / name) for name in plan['runs']}
    else:
        repo = Path(__file__).resolve().parents[2]
        remotes = [remote_isaac.SSH(repo, role) for role in args.roles.split(',')]
        log = lambda line: print(line, flush=True)  # noqa: E731
        states = service_window(remotes, paused, lambda: run_batch(
            plan, args.out, remotes, busy_limit=args.busy_limit, log=log, lend=paused), log=log)
    lines = ['name\tstate\trole\tstatus\tplaced\tworst unstable box\tfailures']
    for name, value in states.items():
        result = args.out / name / 'result.json'
        lines.append(row(name, value, json.loads(result.read_text(encoding='utf-8')) if value == 'done' else {}))
    if args.out.is_dir():
        (args.out / 'summary.tsv').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0 if all(value == 'done' for value in states.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
