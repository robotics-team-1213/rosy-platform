"""Site model watcher: new model -> intake -> shadow push (D-373 decisions 5 and 8).

watch.py [--config /etc/rosy/model-watch.yaml]

Two backends, one delivery logic. The key of an entry is the inbox folder name
(backend inbox, the default) or the HF commit (backend hf, optional).

backend inbox (store folder, no HF): each run
1. The store root must exist (a NAS or Drive mount that is not there is a
   listing failure, never an empty inbox). Its layout dirs are created.
2. List the complete folders of <store>/models/inbox/ (READY marker equal to the
   folder's content_sha), oldest marker first. Half-synced folders are ignored.
3. A folder whose verdict is recorded but that is still in the inbox (a move
   failed last run) is moved now. A folder name reused with other content is
   moved to rejected/ ("reused"); hand it over under a new name.
4. Intake the unseen ones (at most max_new_per_run). Pass: the folder moves to
   models/accepted/<model_revision>/. Fail: to models/rejected/<folder>/ with
   REJECTED.txt. An infrastructure error keeps the folder in the inbox and is
   retried up to max_attempts, then recorded as gave_up (still in the inbox:
   fix the site, then delete its state entry, or remove the folder).

backend hf: each run
1. List the newest `history_limit` commits of the HF model repo.
2. First run (no state file) without `since`: every listed commit but the newest
   is recorded as skipped ("bootstrap"). With `since: <sha>`, that commit and
   everything before it are recorded as skipped ("since").
3. Intake, in-process, on unseen commits and on commits whose earlier intake
   hit an infrastructure error (oldest first, at most max_new_per_run).

Both: a real gate verdict (pass/fail) is final; an infrastructure error (disk,
network, HF, missing runtime, timeout) is retried on later runs up to
max_attempts, then recorded as gave_up.
Deliver: only the newest passed entry is ever pushed (newest wins); older
   pending entries are superseded, and a robot added to the config later gets
   it too. For every robot the robot's real hold file and shadow pointer are
   read each run:
   - hold file present (an operator pushed or rolled back by hand) -> held:
     nothing pushed, no attempt used, until `rosy_ml release-hold <robot>`;
   - already on the newest revision -> ok, no push;
   - otherwise push `--unless-held` as operator "site:<hostname>" - also when
     the robot was up to date before and is behind again (released after a
     rollback). Inside the robot lock a hold taken meanwhile gives exit 76
     (held) and a busy lock exit 75 (retry next run); neither uses an attempt.
   A failed read or push of a robot that is not up to date stays pending and is
   retried on later runs, without re-running intake, up to max_attempts.
The state file is rewritten atomically after every step.

The end of automation is the shadow slot: this only ever calls `deliver push`.
Selecting a model for driving stays behind the D-205 P3 gate.

HF token (backend hf only): only a secret file, named by config `hf_token_file`
or HF_TOKEN_FILE. A named file that does not exist means no token (a public
repo). Without one, token=False is passed so huggingface_hub does not fall back
to HF_TOKEN or $HF_HOME/token. Never an argument, never a repo file.

Config (YAML):
  backend: inbox                          # optional: inbox (default) | hf
  store: /srv/rosy/store                  # backend inbox: the store folder (local, NAS, Drive)
  repo: org/lane-seg                      # backend hf: the HF model repo
  robots: [{name: <robot-id>, host: <hostname>.local, user: rosy}]   # user optional
      # host is a name (mDNS); an IP works but is not recommended: the network renumbers.
      # The host key is pinned in known_hosts under `name` (ssh HostKeyAlias), not the host.
  ssh: {identity: <site key>, known_hosts: <pinned file>}     # both required
  intake_out: /var/lib/rosy-model-watch/models
  state_file: /var/lib/rosy-model-watch/state.json
  since: <40-hex sha>                     # backend hf, optional: skip it and older commits
  hf_token_file: <path>                   # backend hf, optional, else HF_TOKEN_FILE
  gate: <intake_gate.yaml>                # optional, intake's default
  replay_root: <dir holding data/teleop/learning/*.mp4>   # optional, the repo root
  max_new_per_run: 1                      # optional: intakes per run
  history_limit: 20                       # optional (hf): newest commits considered
  max_attempts: 5                         # optional: per intake / per robot push
  push_timeout_s: 600                     # optional: deliver --timeout

Exit codes: 0 run finished and nothing is waiting on a retry (a failed intake,
a held robot or a busy lock is a recorded outcome, not an error); 1 an intake
infrastructure error, a store move or a robot push failed this run (retried
later); 2 bad config or state file; 5 the listing failed (store missing or
unreadable, or the HF listing failed; nothing recorded); 6 CONFIG_EXIT: intake
reported a configuration error (a Python package such as onnx missing from the
watcher's venv): the run stops at once, nothing is recorded and no attempt is
spent, so the timer retries every run until the venv is fixed. A robot push that
fails with deliver.py's own code (3, 75, 76) is logged with that code; the
watcher's exit stays one of these, except for a network failure to a robot:
77 its host name did not resolve (DNS / mDNS), 78 connection refused, timed out or no
route, 79 host key unknown or changed. These are deliver.py's codes (operator_ssh.py);
the run exits with the code of the first robot (config order) that failed this way, so
the unit shows failed and the timer keeps firing. A network failure spends no attempt
(the robot stays pending, never gave_up) and is recorded per robot in the state file
under robot_failures {kind, exit, at, count}; the next successful contact clears it.
`rosy_ml status --watch-config` shows it. A robot that is up to date but cannot be
read also exits with its code (it used to be a silent message)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import socket
import sys
import tempfile
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent
for _p in (MODEL_DIR, MODEL_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import store  # noqa: E402

DEFAULT_CONFIG = "/etc/rosy/model-watch.yaml"
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_NAME = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]*")
_SHA = re.compile(r"[0-9a-f]{40}")
import operator_ssh  # noqa: E402  (learning/training/perception, on sys.path above)
from deliver import HELD_EXIT, LOCK_BUSY_EXIT as BUSY_EXIT  # noqa: E402  no attempt used
# 5, not 3: deliver.py's 3 (history not written) and harvest.py's 4 (not idle) stay distinct.
LIST_FAILED_EXIT = 5
BACKENDS = ("inbox", "hf")
INBOX_KEY = "store-inbox"


# --- pure core (watch_core.py) ---------------------------------------------------------------

from watch_core import (  # noqa: E402,F401  re-exported for callers and tests
    STATE_VERSION,
    new_state,
    record_failure,
    clear_failure,
    apply_result,
    skip_old,
    plan_run,
    newest_passed,
    supersede_older,
    ensure_targets,
    delivery_decision,
    _set_robot,
    record_delivery,
    supersede,
)


# --- files ----------------------------------------------------------------------------------

def read_hf_token(env, cfg) -> str | bool:
    """The token from the secret file, else False (never HF_TOKEN / $HF_HOME/token)."""
    path = cfg.get("hf_token_file") or env.get("HF_TOKEN_FILE")
    if not path or not Path(path).exists():
        return False
    return Path(path).read_text(encoding="utf-8").strip() or False


def load_config(path) -> dict:
    import yaml
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("config must be a mapping")
    backend = cfg.setdefault("backend", "inbox")
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {BACKENDS}, got {backend!r}")
    if backend == "hf":
        if not isinstance(cfg.get("repo"), str) or not _REPO.fullmatch(cfg["repo"]):
            raise ValueError(f"repo must be org/name, got {cfg.get('repo')!r}")
    else:
        if not isinstance(cfg.get("store"), str) or not cfg["store"].strip():
            raise ValueError("store: the store folder path is required (backend inbox)")
        if cfg.get("since") is not None:
            raise ValueError("since applies only to backend hf")
    robots = cfg.get("robots")
    if not isinstance(robots, list) or not robots:
        raise ValueError("robots: at least one {name, host}")
    names = set()
    for r in robots:
        if not isinstance(r, dict) or not all(
                isinstance(r.get(k), str) and _NAME.fullmatch(r[k]) for k in ("name", "host")):
            raise ValueError(f"robots: bad entry {r!r}")
        if r["name"] in names:
            raise ValueError(f"robots: duplicate name {r['name']!r}")
        names.add(r["name"])
    ssh = cfg.get("ssh") or {}
    if not ssh.get("identity") or not ssh.get("known_hosts"):
        raise ValueError("ssh.identity (the site key) and ssh.known_hosts are required")
    for key in ("intake_out", "state_file"):
        if not cfg.get(key):
            raise ValueError(f"{key} is required")
    since = cfg.get("since")
    if since is not None and (not isinstance(since, str) or not _SHA.fullmatch(since)):
        raise ValueError(f"since must be a 40-hex commit sha, got {since!r}")
    for key, default in (("max_new_per_run", 1), ("history_limit", 20), ("max_attempts", 5),
                         ("push_timeout_s", 600)):
        cfg.setdefault(key, default)
        if not isinstance(cfg[key], int) or isinstance(cfg[key], bool) or cfg[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    return cfg


def load_state(path, repo: str) -> dict:
    path = Path(path)
    if not path.exists():
        return new_state(repo)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("repo", repo) != repo:
        raise ValueError(f"state file {path} belongs to {state.get('repo')}, not {repo}")
    return {**new_state(repo), **state}


def save_state(path, state: dict) -> None:
    """Write-temp, fsync, replace: a crash leaves the old or the new file, never half."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --- real HF / intake / deliver (lazy: heavy imports only when used) ------------------------

def state_key(cfg: dict) -> str:
    return cfg["repo"] if cfg["backend"] == "hf" else INBOX_KEY


def hf_list_commits(repo: str, token) -> list[str]:
    from huggingface_hub import HfApi
    return [c.commit_id for c in HfApi(token=token).list_repo_commits(repo, repo_type="model")]


def default_intake(cfg: dict, token):
    def run(sha: str):
        import functools

        import intake
        from huggingface_hub import snapshot_download
        return intake.run(f"hf:{cfg['repo']}@{sha}", out=cfg["intake_out"],
                          gate_path=cfg.get("gate") or intake.DEFAULT_GATE,
                          root=cfg.get("replay_root") or intake.ROOT,
                          downloader=functools.partial(snapshot_download, token=token))
    return run


def default_inbox_intake(cfg: dict):
    def run(name: str):
        import intake
        return intake.run(f"store-inbox:{name}", out=cfg["intake_out"],
                          gate_path=cfg.get("gate") or intake.DEFAULT_GATE,
                          root=cfg.get("replay_root") or intake.ROOT, store=cfg["store"])
    return run


def default_deliverer(cfg: dict):
    def push(robot: dict, rev: str) -> int:
        import deliver
        return deliver.main(["push", robot["host"], rev, "--models", str(cfg["intake_out"]),
                             "--user", robot.get("user", "rosy"),
                             "--host-key-alias", robot["name"],
                             "--identity", cfg["ssh"]["identity"],
                             "--known-hosts", cfg["ssh"]["known_hosts"],
                             "--timeout", str(cfg["push_timeout_s"]),
                             "--operator", f"site:{socket.gethostname()}",
                             "--unless-held"])
    return push


def default_observer(cfg: dict):
    def read(robot: dict) -> dict:
        import deliver
        return deliver.observe(robot["host"], user=robot.get("user", "rosy"),
                               identity=cfg["ssh"]["identity"],
                               known_hosts=cfg["ssh"]["known_hosts"],
                               host_key_alias=robot["name"])
    return read


# --- one run --------------------------------------------------------------------------------

INTAKE_REPORT = "intake_report.json"  # == intake.REPORT_NAME (intake is imported lazily)


def demote_report(out, revision: str, reason: str) -> None:
    """Turn <out>/<revision>/intake_report.json from pass into fail, so a pass the store
    refused never becomes the eval champion (intake.find_champion reads only passes)."""
    path = Path(out) / revision / INTAKE_REPORT
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        print(f"{revision}: cannot read {path} to mark it failed ({exc})", file=sys.stderr)
        return
    if not isinstance(report, dict):
        return
    report["verdict"] = "fail"
    report["reasons"] = [*(report.get("reasons") or []), f"store refused the pass: {reason}"]
    try:
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"{revision}: cannot mark {path} failed ({exc})", file=sys.stderr)


def finish_inbox(st, state: dict, name: str, out=None) -> tuple[dict, bool]:
    """Move a folder with a verdict out of the inbox: (state, moved). A clash with an
    accepted revision of other files turns the pass into a fail (nothing delivered);
    with out (intake_out) the pass report there is rewritten as a fail too."""
    rec = state["commits"][name]
    try:
        if rec["intake"] == "pass":
            try:
                st.accept(name, rec["model_revision"])
                print(f"{name}: accepted as {rec['model_revision']}")
                return state, True
            except store.StoreError as exc:
                if out is not None:
                    demote_report(out, rec["model_revision"], str(exc))
                rec = {k: v for k, v in rec.items() if k != "robots"}
                rec.update(intake="fail", reasons=[*(rec.get("reasons") or []), str(exc)])
                state = apply_result(state, name, rec)
        reasons = "; ".join(rec.get("reasons") or []) or "intake fail"
        dest = st.reject(name, reasons)
        print(f"{name}: rejected -> {dest.name}: {reasons}")
        return state, True
    except OSError as exc:
        print(f"{name}: cannot move out of the inbox ({exc}); retried next run", file=sys.stderr)
        return state, False


def settle_inbox(st, state: dict, listed: list[str], out=None) -> tuple[dict, list[str], bool]:
    """Listed folders that already have a verdict are moved now; a name reused with
    other content is rejected. Returns (state, folders left to plan, all moved)."""
    all_ok, left = True, []
    for name in listed:
        rec = (state.get("commits") or {}).get(name)
        if not rec or rec.get("intake") not in ("pass", "fail"):
            left.append(name)
            continue
        try:
            if store.content_sha(st.inbox_folder(name)) != rec.get("content_sha"):
                dest = st.reject(name, f"folder name reused: {name} was already processed "
                                       f"(intake {rec['intake']}); hand it over under a new name")
                print(f"{name}: name reused, rejected -> {dest.name}", file=sys.stderr)
                continue
        except OSError as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            all_ok = False
            continue
        state, ok = finish_inbox(st, state, name, out)
        all_ok &= ok
    return state, left, all_ok


def _replay(outcome):
    """intake_fn's recorded outcome, as intake_result expects to receive it."""
    if isinstance(outcome, BaseException):
        raise outcome
    return outcome


def _short(key: str) -> str:
    """An HF commit shortened for logs; an inbox folder name in full."""
    return key[:12] if _SHA.fullmatch(key) else key


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def intake_result(sha: str, prev: dict | None, robots: list[str], intake_fn,
                  max_attempts: int) -> dict:
    attempts = (prev or {}).get("attempts", 0) + 1
    try:
        rc, report = intake_fn(sha)
    except Exception as exc:  # noqa: BLE001 - an unexpected crash is not a verdict
        rc, report = 1, {"transient": True, "reasons": [f"{type(exc).__name__}: {exc}"]}
    reasons = list(report.get("reasons") or [])
    base = {"at": _now(), "attempts": attempts,
            "model_revision": report.get("model_revision")}
    if report.get("transient"):
        state = "gave_up" if attempts >= max_attempts else "error"
        print(f"{_short(sha)}: intake error (attempt {attempts}/{max_attempts}): "
              f"{'; '.join(reasons)}", file=sys.stderr)
        return {**base, "intake": state, "last_error": "; ".join(reasons)}
    if rc != 0 or report.get("verdict") != "pass" or not report.get("model_revision"):
        print(f"{_short(sha)}: intake FAIL {'; '.join(reasons)}", file=sys.stderr)
        return {**base, "intake": "fail", "reasons": reasons}
    miou = (report.get("eval") or {}).get("miou")
    print(f"{_short(sha)}: intake PASS {report['model_revision']}"
          + ("" if miou is None else f" (eval mIoU {miou:.3f})"))
    return {**base, "intake": "pass", "reasons": reasons,
            "robots": {r: {"status": "pending", "attempts": 0} for r in robots}}


CONFIG_EXIT = 6


def main(argv=None, *, list_commits=hf_list_commits, intake_fn=None, deliver_fn=None,
         observe_fn=None, env=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    args = ap.parse_args(argv)
    env = os.environ if env is None else env
    try:
        cfg = load_config(args.config)
        fresh = not Path(cfg["state_file"]).exists()
        state = load_state(cfg["state_file"], state_key(cfg))
        inbox = cfg["backend"] == "inbox"
        token = False if inbox else read_hf_token(env, cfg)
    except (OSError, ValueError) as exc:
        print(f"model-watch: {exc}", file=sys.stderr)
        return 2
    retry_later = False
    if inbox:
        st = store.Store(cfg["store"])
        try:
            if not st.root.is_dir():
                raise OSError(f"store {st.root} does not exist (NAS or Drive not mounted?)")
            st.ensure_layout()
            commits = list(reversed(st.list_inbox()))  # newest first, like HF
        except OSError as exc:
            print(f"model-watch: cannot list the store inbox: {exc}", file=sys.stderr)
            return LIST_FAILED_EXIT
        state, commits, moved_ok = settle_inbox(st, state, commits, cfg["intake_out"])
        retry_later |= not moved_ok
    else:
        try:
            commits = list_commits(cfg["repo"], token)[:cfg["history_limit"]]
        except Exception as exc:  # noqa: BLE001 - network, auth, missing repo: retry next tick
            print(f"model-watch: cannot list {cfg['repo']}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return LIST_FAILED_EXIT
        try:
            state = skip_old(commits, state, since=cfg.get("since"), fresh=fresh)
        except ValueError as exc:
            print(f"model-watch: {exc}", file=sys.stderr)
            return 2
    save_state(cfg["state_file"], state)

    robots = {r["name"]: r for r in cfg["robots"]}
    max_attempts = cfg["max_attempts"]
    intake_fn = intake_fn or (default_inbox_intake(cfg) if inbox else default_intake(cfg, token))
    deliver_fn = deliver_fn or default_deliverer(cfg)
    observe_fn = observe_fn or default_observer(cfg)
    for sha in plan_run(commits, state, cfg["max_new_per_run"], max_attempts):
        try:
            probe = intake_fn(sha)
        except Exception as exc:  # noqa: BLE001 - intake_result records it below
            probe = exc
        if isinstance(probe, tuple) and (probe[1] or {}).get("config_error"):
            reasons = "; ".join(probe[1].get("reasons") or [])
            print(f"model-watch: CONFIG ERROR, intake cannot run on this host: {reasons}. "
                  "Fix the watcher venv (deploy/site/README.md) and check with "
                  "rosy_ml doctor --watch-config; nothing was recorded.", file=sys.stderr)
            return CONFIG_EXIT
        extra = {"content_sha": store.content_sha(st.inbox_folder(sha))} if inbox else {}
        result = {**intake_result(sha, state["commits"].get(sha), list(robots),
                                  lambda _sha, p=probe: _replay(p), max_attempts), **extra}
        retry_later |= result["intake"] == "error"
        state = apply_result(state, sha, result)
        save_state(cfg["state_file"], state)
        if inbox and result["intake"] in ("pass", "fail"):
            state, ok = finish_inbox(st, state, sha, cfg["intake_out"])
            retry_later |= not ok
            save_state(cfg["state_file"], state)

    state = supersede_older(ensure_targets(state, list(robots)))
    save_state(cfg["state_file"], state)
    sha = newest_passed(state)
    net_exits: list[int] = []  # network failures this run, in config order

    def net_failure(state: dict, name: str, kind: str, detail: str) -> dict:
        code = operator_ssh.KIND_EXIT[kind]
        net_exits.append(code)
        state = record_failure(state, name, kind, code, _now())
        n = state["robot_failures"][name]["count"]
        print(f"model-watch: {name}: {kind} failure (exit {code}, {n} in a row): {detail}",
              file=sys.stderr)
        save_state(cfg["state_file"], state)
        return state

    for name in robots if sha else ():
        rev = state["commits"][sha]["model_revision"]
        entry = state["commits"][sha]["robots"][name]
        if entry["status"] == "gave_up":
            continue
        try:
            decision = delivery_decision(rev, observe_fn(robots[name]))
            if name in (state.get("robot_failures") or {}):  # reachable again
                state = clear_failure(state, name)
                save_state(cfg["state_file"], state)
        except Exception as exc:  # noqa: BLE001 - one robot never blocks the others
            if getattr(exc, "kind", None) in operator_ssh.KIND_EXIT:
                state = net_failure(state, name, exc.kind, str(exc))
                continue  # no attempt spent: the robot is not reachable, not broken
            if entry["status"] == "ok":  # up to date when last seen: nothing to retry
                print(f"{name}: cannot read the robot ({exc}); last delivered {rev}")
                continue
            decision, error = "error", f"{type(exc).__name__}: {exc}"
        if decision == "held":
            print(f"{_short(sha)}: {rev} -> {name}: held by an operator (rosy_ml release-hold)")
            continue
        if decision == "ok":
            if entry["status"] != "ok":
                state = record_delivery(state, sha, name, error=None, max_attempts=max_attempts)
                save_state(cfg["state_file"], state)
            continue
        if decision == "push":
            if entry["status"] == "ok":  # the robot is behind again (released after a rollback)
                state = _set_robot(state, sha, name, {"status": "pending", "attempts": 0})
            try:
                code = deliver_fn(robots[name], rev)
            except Exception as exc:  # noqa: BLE001 - one robot never blocks the others
                code, error = 1, f"{type(exc).__name__}: {exc}"
            else:
                error = None if code == 0 else f"deliver exit {code}"
            if code in operator_ssh.EXIT_KIND:  # deliver already logged the ssh line
                state = net_failure(state, name, operator_ssh.EXIT_KIND[code],
                                    "see the ssh line above")
                continue
            if code == HELD_EXIT:  # an operator took the hold after we looked
                print(f"{_short(sha)}: {rev} -> {name}: held by an operator (rosy_ml release-hold)")
                save_state(cfg["state_file"], state)
                continue
            if code == BUSY_EXIT:
                print(f"{_short(sha)}: {rev} -> {name}: robot lock busy, retry next run")
                save_state(cfg["state_file"], state)
                continue
        state = record_delivery(state, sha, name, error=error, max_attempts=max_attempts)
        save_state(cfg["state_file"], state)
        outcome = state["commits"][sha]["robots"][name]["status"]
        print(f"{_short(sha)}: {rev} -> {name} shadow: {outcome}"
              + (f" ({error})" if error else ""))
        retry_later |= error is not None
    if net_exits:
        return net_exits[0]
    return 1 if retry_later else 0


if __name__ == "__main__":
    sys.exit(main())
