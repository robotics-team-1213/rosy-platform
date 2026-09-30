"""Site model watcher: new HF model commit -> intake -> shadow push (D-373 decision 5).

watch.py [--config /etc/rosy/model-watch.yaml]

One run (rosy-model-watch.timer, every 10 min): list the commits of the HF
model repo, take the ones the state file has not seen (oldest first, at most
max_new_per_run), run intake on hf:<repo>@<sha> in-process, and on pass run
deliver.py push to every configured robot. Each commit's result (intake verdict,
reasons, per-robot outcome) is written to the state file atomically, so a
commit is never processed twice. A robot that fails does not stop the others.

The end of automation is the shadow slot: this only ever calls `deliver push`.
Selecting a model for driving stays behind the D-205 P3 gate.

HF token: the file named by HF_TOKEN_FILE, else HF_TOKEN from the environment,
else none (public repo). Never an argument, never a repo file.

Config (YAML):
  repo: org/lane-seg                      # HF model repo
  robots: [{name: pinky-005, host: <robot-ip>, user: rosy}]   # user optional
  ssh: {identity: /etc/rosy/model-watch/rosy-operator-ed25519,
        known_hosts: /etc/rosy/model-watch/known_hosts}
  intake_out: /var/lib/rosy-model-watch/models
  state_file: /var/lib/rosy-model-watch/state.json
  gate: <intake_gate.yaml>                # optional, intake's default
  replay_root: <dir holding data/teleop/learning/*.mp4>   # optional, the repo root
  max_new_per_run: 1                      # optional
  history_limit: 20                       # optional: newest commits considered

Exit codes: 0 run finished, no delivery failed (a failed intake is a recorded
outcome, not an error); 1 at least one robot delivery failed; 2 bad config or
state file; 3 HF listing failed (nothing recorded)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
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


# --- pure core ------------------------------------------------------------------------------

def plan_run(commits: list[str], state: dict, limit: int) -> list[str]:
    """Unseen commits, oldest first, at most limit. commits: newest first (HF order)."""
    seen = state.get("commits") or {}
    return [sha for sha in reversed(commits) if sha not in seen][:max(limit, 0)]


def apply_result(state: dict, sha: str, result: dict) -> dict:
    """A new state with result recorded for sha; state is not modified."""
    return {**state, "commits": {**(state.get("commits") or {}), sha: result}}


# --- files ----------------------------------------------------------------------------------

def read_hf_token(env) -> str | None:
    path = env.get("HF_TOKEN_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip() or None
    return env.get("HF_TOKEN") or None


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
        raise ValueError("ssh.identity and ssh.known_hosts are required")
    for key in ("intake_out", "state_file"):
        if not cfg.get(key):
            raise ValueError(f"{key} is required")
    cfg.setdefault("max_new_per_run", 1)
    cfg.setdefault("history_limit", 20)
    for key in ("max_new_per_run", "history_limit"):
        if not isinstance(cfg[key], int) or cfg[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    return cfg


def load_state(path, repo: str) -> dict:
    path = Path(path)
    if not path.exists():
        return {"version": STATE_VERSION, "repo": repo, "commits": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("repo", repo) != repo:
        raise ValueError(f"state file {path} belongs to {state.get('repo')}, not {repo}")
    return state


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

def hf_list_commits(repo: str, token: str | None) -> list[str]:
    from huggingface_hub import HfApi
    return [c.commit_id for c in HfApi(token=token).list_repo_commits(repo, repo_type="model")]


def default_intake(cfg: dict, token: str | None):
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
                             "--known-hosts", cfg["ssh"]["known_hosts"]])
    return push


# --- one run --------------------------------------------------------------------------------

def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def process_commit(sha: str, robots: list[dict], intake_fn, deliver_fn) -> dict:
    try:
        rc, report = intake_fn(sha)
    except Exception as exc:  # noqa: BLE001 - recorded, the run goes on
        rc, report = 1, {"verdict": "fail", "reasons": [f"{type(exc).__name__}: {exc}"]}
    result = {"at": _now(), "intake": report.get("verdict", "fail"),
              "model_revision": report.get("model_revision"),
              "reasons": list(report.get("reasons") or [])}
    if rc != 0 or result["intake"] != "pass" or not result["model_revision"]:
        result["intake"] = "fail"
        print(f"{sha[:12]}: intake FAIL {'; '.join(result['reasons'])}", file=sys.stderr)
        return result
    result["robots"] = {}
    for robot in robots:
        try:
            code = deliver_fn(robot, result["model_revision"])
            outcome = "ok" if code == 0 else f"failed (exit {code})"
        except Exception as exc:  # noqa: BLE001 - one robot never blocks the others
            outcome = f"failed ({type(exc).__name__}: {exc})"
        result["robots"][robot["name"]] = outcome
        print(f"{sha[:12]}: {result['model_revision']} -> {robot['name']} shadow: {outcome}")
    return result


def main(argv=None, *, list_commits=hf_list_commits, intake_fn=None, deliver_fn=None,
         env=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    args = ap.parse_args(argv)
    env = os.environ if env is None else env
    try:
        cfg = load_config(args.config)
        state = load_state(cfg["state_file"], cfg["repo"])
        token = read_hf_token(env)
    except (OSError, ValueError) as exc:
        print(f"model-watch: {exc}", file=sys.stderr)
        return 2
    try:
        commits = list_commits(cfg["repo"], token)[:cfg["history_limit"]]
    except Exception as exc:  # noqa: BLE001 - network, auth, missing repo: retry next tick
        print(f"model-watch: cannot list {cfg['repo']}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 3
    intake_fn = intake_fn or default_intake(cfg, token)
    deliver_fn = deliver_fn or default_deliverer(cfg)
    delivery_failed = False
    for sha in plan_run(commits, state, cfg["max_new_per_run"]):
        result = process_commit(sha, cfg["robots"], intake_fn, deliver_fn)
        delivery_failed |= any(v != "ok" for v in result.get("robots", {}).values())
        state = apply_result(state, sha, result)
        save_state(cfg["state_file"], state)
    return 1 if delivery_failed else 0


if __name__ == "__main__":
    sys.exit(main())
