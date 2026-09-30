"""Site model watcher: new HF model commit -> intake -> shadow push (D-373 decision 5).

watch.py [--config /etc/rosy/model-watch.yaml]

One run (rosy-model-watch.timer, every 10 min):
1. List the newest `history_limit` commits of the HF model repo.
2. First run (no state file) without `since`: every listed commit but the newest
   is recorded as skipped ("bootstrap"). With `since: <sha>`, that commit and
   everything before it are recorded as skipped ("since").
3. Intake, in-process, on unseen commits and on commits whose earlier intake
   hit an infrastructure error (oldest first, at most max_new_per_run). A real
   gate verdict (pass/fail) is final; an infrastructure error (disk, network,
   HF, missing runtime, timeout) is retried on later runs up to max_attempts,
   then recorded as gave_up.
4. Deliver: every passed commit is pending per robot; a robot added to the
   config later gets the newest passed commit. Per robot only the newest
   pending commit is considered; older pending ones, and any not newer than
   what the watcher last delivered, are superseded (newest wins). Before a push
   the robot's real pointer and history.jsonl are read:
   - already on that revision (an operator pushed it) -> ok, no push;
   - the robot holds a revision the watcher knows to be newer -> superseded;
   - operator hold: the latest pointer action on the robot is a rollback away
     from this revision -> not pushed (no attempt used) until an operator
     pushes something else or runs `deliver.py release-hold`;
   - otherwise push, as operator "site:<hostname>".
   A failed read or push stays pending and is retried on later runs, without
   re-running intake, up to max_attempts.
The state file is rewritten atomically after every step.

The end of automation is the shadow slot: this only ever calls `deliver push`.
Selecting a model for driving stays behind the D-205 P3 gate.

HF token: only a secret file, named by config `hf_token_file` or HF_TOKEN_FILE.
A named file that does not exist means no token (a public repo). Without one,
token=False is passed so huggingface_hub does not fall back to
HF_TOKEN or $HF_HOME/token. Never an argument, never a repo file.

Config (YAML):
  repo: org/lane-seg                      # HF model repo
  robots: [{name: pinky-005, host: <robot-ip>, user: rosy}]   # user optional
  ssh: {identity: <site key>, known_hosts: <pinned file>}     # both required
  intake_out: /var/lib/rosy-model-watch/models
  state_file: /var/lib/rosy-model-watch/state.json
  since: <40-hex sha>                     # optional: skip it and older commits
  hf_token_file: <path>                   # optional, else HF_TOKEN_FILE
  gate: <intake_gate.yaml>                # optional, intake's default
  replay_root: <dir holding data/teleop/learning/*.mp4>   # optional, the repo root
  max_new_per_run: 1                      # optional: intakes per run
  history_limit: 20                       # optional: newest commits considered
  max_attempts: 5                         # optional: per intake / per robot push
  push_timeout_s: 600                     # optional: deliver --timeout

Exit codes: 0 run finished and nothing is waiting on a retry (a failed intake is
a recorded outcome, not an error); 1 an intake infrastructure error or a robot
push failed this run (retried later); 2 bad config or state file; 3 the HF
listing failed (nothing recorded)."""

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
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

DEFAULT_CONFIG = "/etc/rosy/model-watch.yaml"
STATE_VERSION = 1
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_NAME = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]*")
_SHA = re.compile(r"[0-9a-f]{40}")


# --- pure core ------------------------------------------------------------------------------

def new_state(repo: str) -> dict:
    return {"version": STATE_VERSION, "repo": repo, "next_order": 0, "commits": {},
            "shadow": {}}


def apply_result(state: dict, sha: str, result: dict) -> dict:
    """A new state whose record for sha is result; the commit keeps its order
    (first-seen, which is oldest-first chronology) or gets the next one."""
    commits = dict(state.get("commits") or {})
    nxt = state.get("next_order", 0)
    order = (commits.get(sha) or {}).get("order")
    if order is None:
        order, nxt = nxt, nxt + 1
    commits[sha] = {"order": order, **{k: v for k, v in result.items() if k != "order"}}
    return {**state, "commits": commits, "next_order": nxt}


def skip_old(commits: list[str], state: dict, *, since: str | None, fresh: bool) -> dict:
    """Record commits that are never processed. commits: newest first (HF order)."""
    if since:
        if since in commits:
            old, reason = commits[commits.index(since):], "since"
        elif since in (state.get("commits") or {}):
            return state  # recorded on an earlier run; it has left the listed window
        else:
            raise ValueError(f"since {since} is not among the last {len(commits)} commits")
    elif fresh:
        old, reason = commits[1:], "bootstrap"
    else:
        return state
    for sha in reversed(old):
        if sha not in (state.get("commits") or {}):
            state = apply_result(state, sha, {"intake": "skipped", "reason": reason})
    return state


def plan_run(commits: list[str], state: dict, limit: int, max_attempts: int) -> list[str]:
    """Commits to run intake on: unseen, or an earlier infrastructure error with
    attempts left. Oldest first, at most limit. commits: newest first."""
    seen = state.get("commits") or {}

    def due(sha):
        rec = seen.get(sha)
        return rec is None or (rec.get("intake") == "error"
                               and rec.get("attempts", 0) < max_attempts)
    return [sha for sha in reversed(commits) if due(sha)][:max(limit, 0)]


def plan_deliveries(state: dict, robots: list[str], max_attempts: int):
    """([(sha, robot)] to push, [(sha, robot)] superseded). Per robot only the
    newest pending commit is pushed, and never one not newer than its shadow."""
    commits = state.get("commits") or {}
    todo, superseded = [], []
    for robot in robots:
        pending = sorted(
            (rec["order"], sha) for sha, rec in commits.items()
            if rec.get("intake") == "pass"
            and (rec.get("robots") or {}).get(robot, {}).get("status") == "pending"
            and rec["robots"][robot].get("attempts", 0) < max_attempts)
        if not pending:
            continue
        floor = (state.get("shadow") or {}).get(robot, {}).get("order", -1)
        newest_order, newest = pending[-1]
        superseded += [(sha, robot) for _, sha in pending[:-1]]
        if newest_order > floor:
            todo.append((newest_order, newest, robot))
        else:
            superseded.append((newest, robot))
    todo.sort()
    return [(sha, robot) for _, sha, robot in todo], superseded


def ensure_targets(state: dict, robots: list[str]) -> dict:
    """Robots with no entry on the newest passed commit (added to the config
    later) become pending for it. Older commits are never back-filled."""
    passed = [(rec["order"], sha) for sha, rec in (state.get("commits") or {}).items()
              if rec.get("intake") == "pass"]
    if not passed:
        return state
    sha = max(passed)[1]
    missing = [r for r in robots if r not in (state["commits"][sha].get("robots") or {})]
    for robot in missing:
        state = _set_robot(state, sha, robot, {"status": "pending", "attempts": 0})
    return state


def delivery_decision(rev: str, order: int, observed: dict, rev_orders: dict) -> str:
    """push | ok | held | superseded, from the robot's real pointer and history."""
    from deliver import operator_hold
    actual = observed.get("shadow")
    if actual == rev:
        return "ok"
    if operator_hold(observed.get("history") or []) == rev:
        return "held"
    if actual in rev_orders and rev_orders[actual] > order:
        return "superseded"
    return "push"


def _set_robot(state: dict, sha: str, robot: str, entry: dict) -> dict:
    rec = state["commits"][sha]
    robots = {**(rec.get("robots") or {}), robot: entry}
    return {**state, "commits": {**state["commits"], sha: {**rec, "robots": robots}}}


def record_delivery(state: dict, sha: str, robot: str, *, error: str | None,
                    max_attempts: int) -> dict:
    prev = state["commits"][sha]["robots"][robot]
    attempts = prev.get("attempts", 0) + 1
    if error is None:
        state = _set_robot(state, sha, robot, {"status": "ok", "attempts": attempts})
        shadow = {**(state.get("shadow") or {}),
                  robot: {"sha": sha, "order": state["commits"][sha]["order"]}}
        return {**state, "shadow": shadow}
    status = "gave_up" if attempts >= max_attempts else "pending"
    return _set_robot(state, sha, robot,
                      {"status": status, "attempts": attempts, "last_error": error})


def supersede(state: dict, sha: str, robot: str) -> dict:
    prev = state["commits"][sha]["robots"][robot]
    return _set_robot(state, sha, robot, {**prev, "status": "superseded"})


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
    if not isinstance(cfg.get("repo"), str) or not _REPO.fullmatch(cfg["repo"]):
        raise ValueError(f"repo must be org/name, got {cfg.get('repo')!r}")
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


def default_deliverer(cfg: dict):
    def push(robot: dict, rev: str) -> int:
        import deliver
        return deliver.main(["push", robot["host"], rev, "--models", str(cfg["intake_out"]),
                             "--user", robot.get("user", "rosy"),
                             "--identity", cfg["ssh"]["identity"],
                             "--known-hosts", cfg["ssh"]["known_hosts"],
                             "--timeout", str(cfg["push_timeout_s"]),
                             "--operator", f"site:{socket.gethostname()}"])
    return push


def default_observer(cfg: dict):
    def read(robot: dict) -> dict:
        import deliver
        return deliver.observe(robot["host"], user=robot.get("user", "rosy"),
                               identity=cfg["ssh"]["identity"],
                               known_hosts=cfg["ssh"]["known_hosts"])
    return read


# --- one run --------------------------------------------------------------------------------

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
        print(f"{sha[:12]}: intake error (attempt {attempts}/{max_attempts}): "
              f"{'; '.join(reasons)}", file=sys.stderr)
        return {**base, "intake": state, "last_error": "; ".join(reasons)}
    if rc != 0 or report.get("verdict") != "pass" or not report.get("model_revision"):
        print(f"{sha[:12]}: intake FAIL {'; '.join(reasons)}", file=sys.stderr)
        return {**base, "intake": "fail", "reasons": reasons}
    print(f"{sha[:12]}: intake PASS {report['model_revision']}")
    return {**base, "intake": "pass", "reasons": reasons,
            "robots": {r: {"status": "pending", "attempts": 0} for r in robots}}


def main(argv=None, *, list_commits=hf_list_commits, intake_fn=None, deliver_fn=None,
         observe_fn=None, env=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    args = ap.parse_args(argv)
    env = os.environ if env is None else env
    try:
        cfg = load_config(args.config)
        fresh = not Path(cfg["state_file"]).exists()
        state = load_state(cfg["state_file"], cfg["repo"])
        token = read_hf_token(env, cfg)
    except (OSError, ValueError) as exc:
        print(f"model-watch: {exc}", file=sys.stderr)
        return 2
    try:
        commits = list_commits(cfg["repo"], token)[:cfg["history_limit"]]
    except Exception as exc:  # noqa: BLE001 - network, auth, missing repo: retry next tick
        print(f"model-watch: cannot list {cfg['repo']}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 3
    try:
        state = skip_old(commits, state, since=cfg.get("since"), fresh=fresh)
    except ValueError as exc:
        print(f"model-watch: {exc}", file=sys.stderr)
        return 2
    save_state(cfg["state_file"], state)

    robots = {r["name"]: r for r in cfg["robots"]}
    max_attempts = cfg["max_attempts"]
    intake_fn = intake_fn or default_intake(cfg, token)
    deliver_fn = deliver_fn or default_deliverer(cfg)
    observe_fn = observe_fn or default_observer(cfg)
    retry_later = False
    for sha in plan_run(commits, state, cfg["max_new_per_run"], max_attempts):
        result = intake_result(sha, state["commits"].get(sha), list(robots), intake_fn,
                               max_attempts)
        retry_later |= result["intake"] == "error"
        state = apply_result(state, sha, result)
        save_state(cfg["state_file"], state)

    state = ensure_targets(state, list(robots))
    todo, superseded = plan_deliveries(state, list(robots), max_attempts)
    for sha, name in superseded:
        state = supersede(state, sha, name)
    save_state(cfg["state_file"], state)
    rev_orders = {rec["model_revision"]: rec["order"] for rec in state["commits"].values()
                  if rec.get("intake") == "pass" and rec.get("model_revision")}
    for sha, name in todo:
        rev = state["commits"][sha]["model_revision"]
        try:
            decision = delivery_decision(rev, state["commits"][sha]["order"],
                                         observe_fn(robots[name]), rev_orders)
            if decision == "held":
                print(f"{sha[:12]}: {rev} -> {name}: held (an operator rolled it back; "
                      "deliver.py release-hold ends the hold)")
                continue
            if decision == "superseded":
                state = supersede(state, sha, name)
                save_state(cfg["state_file"], state)
                continue
            code = 0 if decision == "ok" else deliver_fn(robots[name], rev)
            error = None if code == 0 else f"deliver exit {code}"
        except Exception as exc:  # noqa: BLE001 - one robot never blocks the others
            error = f"{type(exc).__name__}: {exc}"
        state = record_delivery(state, sha, name, error=error, max_attempts=max_attempts)
        save_state(cfg["state_file"], state)
        outcome = state["commits"][sha]["robots"][name]["status"]
        print(f"{sha[:12]}: {rev} -> {name} shadow: {outcome}"
              + (f" ({error})" if error else ""))
        retry_later |= error is not None
    return 1 if retry_later else 0


if __name__ == "__main__":
    sys.exit(main())
