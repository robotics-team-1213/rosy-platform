"""One-shot, unprivileged simulation job; root helper owns isolation and cgroups."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

from native_sim_inputs import (CAPS, STUDY_EXPERIMENTS, read_json, run_identity, study_approval,
                               verify_bindings, write_json)


def validate_state(state):
    state = Path(state).absolute()
    document = read_json(state / "manifest.json")
    if document.get("schema") != "rosy.omx-native-sim-state/1":
        raise ValueError("unsupported native state schema")
    revision = run_identity(document["run_id"])
    expected_release = state.parent.parent / "releases" / revision
    if (state.name != document["run_id"][-12:] or state.parent.name != "state"
            or document.get("state") != str(state) or document.get("release") != str(expected_release)
            or document.get("source") != str(expected_release)
            or document.get("unit") != "rosy-native-sim-" + document["run_id"]
            or state.resolve() != state or expected_release.resolve() != expected_release):
        raise ValueError("native state path binding mismatch")
    verify_bindings(document, expected_release, state)
    return document


def capacity(jobs_root, ignore_name=None):
    """D-568 headroom after live locks and unexpired reservations, without deleting peers."""
    jobs_root, cpu, memory = Path(jobs_root), 0, 0
    for suffix in ("resv", "lock"):
        for path in jobs_root.glob("*." + suffix):
            # pathlib includes dotfiles; the canonical Bash placement glob does not.
            if path.name.startswith("."):
                continue
            if ignore_name and path.name == ignore_name + "." + suffix:
                continue
            try:
                stamp, kind, cores, gib = path.read_text().split()
                stamp, cores, gib = int(stamp), int(cores), int(gib)
                if kind not in {"sim", "pytest"} or min(cores, gib) < 0 or stamp <= 0:
                    raise ValueError("invalid peer budget")
                if suffix == "resv":
                    live = stamp > time.time()
                else:
                    try:
                        os.kill(stamp, 0)
                        live = True
                    except ProcessLookupError:
                        live = False
                if live:
                    cpu, memory = cpu + cores, memory + gib
            except FileNotFoundError:
                continue  # Peer lock may end between listing and read.
            except (ValueError, PermissionError) as exc:
                raise RuntimeError("unreadable or malformed placement budget: " + str(path)) from exc
    memory_kib = {line.split()[0].rstrip(":"): int(line.split()[1])
                  for line in Path("/proc/meminfo").read_text().splitlines() if
                  line.startswith(("MemAvailable:", "MemTotal:"))}
    cores = len(os.sched_getaffinity(0))
    return (cores - max(os.getloadavg()[0], cpu),
            min(memory_kib["MemAvailable"] / (1024 ** 2), memory_kib["MemTotal"] / (1024 ** 2) - memory))


def reserve(state, *, jobs_root=None, approve_study=False):
    state = Path(state).absolute()
    document = validate_state(state)
    study=document.get('experiment') in STUDY_EXPERIMENTS
    if study and approve_study is not True:
        raise PermissionError('explicit isolated policy study approval required')
    policy_approval=study_approval(document) if study else None
    jobs = Path(jobs_root) if jobs_root is not None else Path.home() / "rosy-jobs"
    if (jobs / "site").exists():
        raise PermissionError("native simulation refuses a site host")
    if (jobs / "busy").exists():
        raise RuntimeError("simulation host is marked busy")
    jobs.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = "sim-omx-native-" + document["run_id"]
    with (jobs / ".native-sim-placement.lock").open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        if (state / "start-intent.json").exists():
            raise FileExistsError("start intent exists; reconcile status, never replay")
        if any(value < floor for value, floor in zip(capacity(jobs, name), (6, 8))):
            raise RuntimeError("native simulation headroom below 6 CPU / 8 GiB")
        for suffix in ("resv", "lock"):
            link, target = jobs / (name + "." + suffix), state / ("budget." + suffix)
            if os.path.lexists(link) and (not link.is_symlink() or link.readlink() != target):
                raise FileExistsError("foreign placement budget path: " + str(link))
        for suffix in ("resv", "lock"):
            link = jobs / (name + "." + suffix)
            if not os.path.lexists(link):
                link.symlink_to(state / ("budget." + suffix))
        expires = int(time.time()) + 600
        cpus, gib = CAPS[document["role"]]
        intent={"run_id": document["run_id"], "revision": document["revision"],
                   "state": str(state), "jobs_root": str(jobs.absolute()), "uid": os.getuid(),
                   "created_at": time.time(), "expires_at": expires, "runtime": "NOT_RUN",
                   "approval": ["isolated-simulation", "startup-home"]}
        if policy_approval is not None:
            intent['study_approval']=policy_approval
        write_json(state / "start-intent.json",intent)
        with (state / "budget.resv").open("x") as budget:
            budget.write(f"{expires} sim {cpus} {gib}\n")
            budget.flush()
            os.fsync(budget.fileno())
    return {"run_id": document["run_id"], "state": str(state), "runtime": "NOT_RUN", "reserved": True}


def run(state, *, launcher=subprocess.run):
    state = Path(state).absolute()
    document = validate_state(state)
    if not (state / "start-intent.json").is_file():
        raise PermissionError("explicit reserved start intent required")
    if Path(__file__).resolve().parents[3] != Path(document["release"]):
        raise PermissionError("executing release does not match the reserved simulation manifest")
    intent = read_json(state / "start-intent.json")
    if (intent.get("run_id") != document["run_id"] or intent.get("revision") != document["revision"]
            or intent.get("state") != str(state) or intent.get("uid") != os.getuid()
            or intent.get("approval") != ["isolated-simulation", "startup-home"]
            or intent.get("expires_at", 0) < time.time()):
        raise PermissionError("reserved start intent binding invalid or expired")
    if document.get('experiment') in STUDY_EXPERIMENTS and intent.get('study_approval')!=study_approval(document):
        raise PermissionError('policy study approval differs from the reserved input')
    jobs = Path(intent["jobs_root"])
    if (jobs / "site").exists():
        raise PermissionError("native simulation refuses a site host")
    if (jobs / "busy").exists():
        raise RuntimeError("simulation host is marked busy")
    if any(value < floor for value, floor in zip(
            capacity(jobs, "sim-omx-native-" + document["run_id"]), (6, 8))):
        raise RuntimeError("native simulation headroom below 6 CPU / 8 GiB")
    write_json(state / "run-intent.json", {"pid": os.getpid(), "run_id": document["run_id"],
                                         "started_at": time.time(), "runtime": "UNKNOWN"})
    cpus, gib = CAPS[document["role"]]
    code, error = 1, None
    try:
        with (state / "budget.lock").open("x") as budget:
            budget.write(f"{os.getpid()} sim {cpus} {gib}\n")
            budget.flush()
            os.fsync(budget.fileno())
        (state / "budget.resv").unlink(missing_ok=True)
        for name in ("home", "tmp", "logs", "cache"):
            (state / name).mkdir(mode=0o700, exist_ok=True)
        env = dict(os.environ, OMX_NATIVE_STATE=str(state), OMX_NATIVE_RUN_ID=document["run_id"],
                   PYTHONDONTWRITEBYTECODE="1")
        # Each named runner retains its isolation and startup checks; G2 also keeps Fleet fencing.
        with (state / "logs/job.log").open("xb") as log:
            result = launcher(["/bin/bash", "--noprofile", "--norc", str(state / "run.sh")],
                              env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
        code = result.returncode
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    finally:
        (state / "budget.lock").unlink(missing_ok=True)
        (state / "budget.resv").unlink(missing_ok=True)
        task = ("SEE_CANONICAL_PICK_PLACE_RESULT" if document.get("experiment", "g2") in {"pick-place", "pick-place-demonstrations", "pick-place-chunks"}|STUDY_EXPERIMENTS
                else "SEE_CANONICAL_G2_RESULT")
        write_json(state / "exit.json", {"exit_code": code, "error": error, "ended_at": time.time(),
                                         "runtime": "EXITED", "task": task})
    return code


def status(state):
    state = Path(state).absolute()
    document = validate_state(state)
    terminal = read_json(state / "exit.json") if (state / "exit.json").is_file() else {}
    value = {"run_id": document["run_id"], "revision": document["revision"], "state": str(state),
             "runtime": terminal.get("runtime", "UNKNOWN" if (state / "start-intent.json").exists() else "NOT_RUN"),
             "exit_code": terminal.get("exit_code"), "sdk_status": "PASS", "real_episodes": 0}
    for name in ("result", "happy-result", "startup-home-ready", "startup-home-failure", "process-cleanup"):
        path = state / "g2" / (name + ".json")
        if path.is_file():
            value[name] = read_json(path)
    task_result = state / "pick-place" / "result.json"
    if document.get("experiment", "g2") in {"pick-place", "pick-place-demonstrations", "pick-place-chunks"}|STUDY_EXPERIMENTS and task_result.is_file():
        value["pick-place-result"] = read_json(task_result)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("reserve", "run", "status"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument('--approve-policy-study',action='store_true')
    args = parser.parse_args()
    if args.operation == "run":
        raise SystemExit(run(args.state))
    print(json.dumps(reserve(args.state,approve_study=args.approve_policy_study)
                     if args.operation == "reserve" else status(args.state), sort_keys=True))


if __name__ == "__main__":
    main()
