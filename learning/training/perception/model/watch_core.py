"""Pure state transitions for the model watcher (watch.py): no I/O, no clock, no network.

Split from watch.py to keep it under the D-362 600-line budget. watch.py re-exports these
names, so callers and tests keep using ``watch.<name>``.
"""

from __future__ import annotations

STATE_VERSION = 1


def new_state(repo: str) -> dict:
    return {"version": STATE_VERSION, "repo": repo, "next_order": 0, "commits": {},
            "shadow": {}, "robot_failures": {}}


def record_failure(state: dict, robot: str, kind: str, code: int, at: str) -> dict:
    """The last network failure of a robot; count = consecutive runs it failed this way."""
    failures = dict(state.get("robot_failures") or {})
    prev = failures.get(robot) or {}
    count = prev.get("count", 0) + 1 if prev.get("kind") == kind else 1
    failures[robot] = {"kind": kind, "exit": code, "at": at, "count": count}
    return {**state, "robot_failures": failures}


def clear_failure(state: dict, robot: str) -> dict:
    if robot not in (state.get("robot_failures") or {}):
        return state
    return {**state, "robot_failures": {k: v for k, v in state["robot_failures"].items()
                                        if k != robot}}


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


def newest_passed(state: dict) -> str | None:
    passed = [(rec["order"], sha) for sha, rec in (state.get("commits") or {}).items()
              if rec.get("intake") == "pass" and rec.get("model_revision")]
    return max(passed)[1] if passed else None


def supersede_older(state: dict) -> dict:
    """Pending robot entries on any passed commit but the newest are superseded:
    the newest passed model is the only one ever pushed (newest wins)."""
    newest = newest_passed(state)
    for sha, rec in (state.get("commits") or {}).items():
        if sha == newest or rec.get("intake") != "pass":
            continue
        for robot, entry in (rec.get("robots") or {}).items():
            if entry.get("status") == "pending":
                state = supersede(state, sha, robot)
    return state


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


def delivery_decision(rev: str, observed: dict) -> str:
    """held | ok | push, from the robot's real hold file and shadow pointer."""
    if observed.get("hold"):
        return "held"
    if observed.get("shadow") == rev:
        return "ok"
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
