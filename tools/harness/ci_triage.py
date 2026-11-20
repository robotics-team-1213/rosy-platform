"""CI failure triage (panel 2026-11-19 Q1, section 8): which failed jobs are infrastructure, and the one safe rerun.

Until 2026-11-19 a red 'ci-result' stopped the publish merge with no reason and the signer reran every red run
blind: PR #247 lost about 40 minutes of a person finding that 25 shards failed in 'apt-get' (attempts 1-2) and
two in the Test step (attempt 3). Given a workflow run id this module reads the failed jobs of its latest attempt,
finds each job's failing step, and sorts it:

  infra         the step is Set up job, container initialisation, Checkout or Install*, and its log shows a
                network signature (Failed to fetch, Temporary failure resolving, Connection timed out/failed,
                HTTP 429/5xx, lost communication with the server)
  env_drift     an Install* step failed on resolution or hash (ResolutionImpossible, hash mismatch, no candidate)
  real_failure  everything else, always: any other step (Test, Build, Smoke, Guard ...), an unreadable log, a
                missing failing step. A test step stays real_failure even if its log mentions the network.

The 'ci-result' aggregate job is ignored. handle() appends one JSON line per failed job to the ledger and
reruns the failed jobs ('gh run rerun --failed') only when EVERY causing job is infra, at most once per
(run, job) and twice per (head_sha, workflow), after re-reading that the run is still the newest one for the
sha and still the attempt that was judged. Merging and signing keep trusting only a real green ci-result.
Standard library only; gh is injected (gh(*args) -> stdout, raising on failure).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import time
from pathlib import Path
from typing import Callable

LEDGER = "rosy-ci-triage.jsonl"
GATE = "ci-result"
RERUNS_PER_JOB = 1
RERUNS_PER_SHA_WORKFLOW = 2
INFRA_STEP = re.compile(r"Set up job|Initiali[sz]e containers|Checkout|Install\b.*")
NETWORK = re.compile(
    r"Failed to fetch|Temporary failure resolving|Connection (?:timed out|failed)|Could not connect to"
    r"|Unable to connect to|HTTP(?: error)?[ /:]+(?:429|5\d\d)\b|\b5\d\d\s+(?:Bad Gateway|Service Unavailable"
    r"|Gateway Time-?out|Internal Server Error)|\b429\s+Too Many Requests|lost communication with the server",
    re.IGNORECASE)
DRIFT = re.compile(r"ResolutionImpossible|DO NOT MATCH THE HASHES|Hash Sum mismatch|No matching distribution"
                   r"|Unable to locate package|has no installation candidate", re.IGNORECASE)
HINT = re.compile(r"Fatal Python error|Segmentation fault|^\S+Z FAILED |AssertionError|collected 0 items"
                  r"|^\S+Z ERROR |##\[error\](?!Process completed)")
STAMP = re.compile(r"^\S*\d{4}-\d\d-\d\dT[\d:.]+Z ")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
Gh = Callable[..., str]


def last_step_log(log: str) -> str:
    """The log text of the group that held the last ##[error]: earlier steps' retried-and-fine warnings do not count."""
    at = log.rfind("##[error]")
    return log if at < 0 else log[max(log.rfind("##[group]", 0, at), 0):]


def failing_step(job: dict) -> str:
    return next((s.get("name", "") for s in job.get("steps") or [] if s.get("conclusion") in ("failure", "timed_out")), "")


def _line(log: str, pattern: re.Pattern) -> str:
    for line in log.splitlines():
        if pattern.search(line):
            return STAMP.sub("", line).strip()[:160]
    return ""


def classify(job: dict, log: str | None) -> dict:
    """{job, step, category, signature, url} for one failed job; log None means it could not be read."""
    step = failing_step(job)
    out = {"job": job.get("name", ""), "step": step, "url": job.get("html_url", "")}
    if not step:
        return {**out, "category": "real_failure", "signature": "no failing step recorded (runner lost or cancelled?)"}
    log = ANSI.sub("", log or "")
    if not INFRA_STEP.fullmatch(step):
        hint = _line(log, HINT) or f"step '{step}' failed"
        return {**out, "category": "real_failure", "signature": hint}
    if log == "":
        return {**out, "category": "real_failure", "signature": "log unavailable; kept red"}
    segment = last_step_log(log)
    if hit := _line(segment, DRIFT):
        return {**out, "category": "env_drift", "signature": hit}
    if hit := _line(segment, NETWORK):
        return {**out, "category": "infra", "signature": hit}
    return {**out, "category": "real_failure", "signature": f"step '{step}' failed without a network signature"}


def read_ledger(path: Path) -> list[dict]:
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return rows


def append_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)  # one write: concurrent runs never interleave
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def failed_jobs(gh: Gh, repo: str, run_id: int, attempt: int) -> list[dict]:
    data = json.loads(gh("api", f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"))
    return [j for j in data["jobs"] if j.get("name") != GATE and j.get("conclusion") in ("failure", "timed_out")]


def job_log(gh: Gh, repo: str, job_id: int) -> str | None:
    try:
        return gh("api", "--allow-escape-sequences", f"repos/{repo}/actions/jobs/{job_id}/logs")
    except Exception:  # noqa: BLE001  (an unreadable log keeps the job red, never infra)
        return None


def triage_run(gh: Gh, repo: str, run_id: int, attempt: int) -> list[dict]:
    jobs = failed_jobs(gh, repo, run_id, attempt)
    with ThreadPoolExecutor(max_workers=8) as pool:
        logs = list(pool.map(lambda j: job_log(gh, repo, j["id"]), jobs))
    return [classify(j, log) for j, log in zip(jobs, logs)]


def newest_run(gh: Gh, repo: str, workflow: str, sha: str) -> dict | None:
    runs = json.loads(gh("api", f"repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}&per_page=100"))["workflow_runs"]
    runs = [r for r in runs if r.get("head_sha") == sha]
    return max(runs, key=lambda r: r["id"]) if runs else None


def refusal(rows: list[dict], ledger: list[dict], run: dict, workflow: str) -> str:
    """Why this failure must not be rerun (empty: all caps and the all-infra rule allow it)."""
    if not rows:
        return "no causing job found"
    if any(r["category"] != "infra" for r in rows):
        return "not every causing job is infra"
    reran = [r for r in ledger if r.get("action") == "rerun"]
    if any(r.get("run_id") == run["id"] and r.get("job") in {x["job"] for x in rows} for r in reran):
        return f"a job already had its {RERUNS_PER_JOB} rerun in this run"
    batches = {(r.get("run_id"), r.get("attempt")) for r in reran
               if r.get("head_sha") == run["head_sha"] and r.get("workflow") == workflow}
    if len(batches) >= RERUNS_PER_SHA_WORKFLOW:
        return f"{len(batches)} reruns already for this sha and workflow"
    return ""


def handle(gh: Gh, repo: str, run_id: int, *, ledger: Path, expected_sha: str, workflow: str = "ci.yml",
           event: str = "", rerun: bool = True, now: float | None = None) -> dict:
    """Judge one completed red run: {category, action, reason, rows}. Never raises; any doubt means no rerun.

    category: infra only when every causing job is infra, else the worst of env_drift / real_failure.
    action: rerun (requested now), none (a person acts: see rows), seen (this attempt was judged before).
    """
    try:
        run = json.loads(gh("api", f"repos/{repo}/actions/runs/{run_id}"))
        attempt, sha = run["run_attempt"], run["head_sha"]
        if run.get("status") != "completed" or run.get("conclusion") != "failure":
            return {"category": "", "action": "none", "reason": f"run is {run.get('status')}/{run.get('conclusion')}", "rows": []}
        prior = read_ledger(ledger)
        done = [r for r in prior if r.get("run_id") == run_id and r.get("attempt") == attempt]
        if done:
            return {"category": _overall(done), "action": "seen", "reason": "this attempt was already triaged", "rows": done}
        rows = triage_run(gh, repo, run_id, attempt)
        reason = refusal(rows, prior, run, workflow)
        if not reason and not rerun:
            reason = "rerun not requested here"
        if not reason:
            reason = _stale(gh, repo, workflow, expected_sha, run)
        action = "none"
        if not reason:
            try:
                gh("run", "rerun", str(run_id), "--failed", "--repo", repo)
                action = "rerun"
            except Exception as error:  # noqa: BLE001  (a token without actions:write: red stays red, with its reason)
                reason = f"rerun refused: {str(error)[:120]}"
        base = {"t": int(time.time() if now is None else now), "repo": run.get("repository", {}).get("full_name", repo),
                "workflow": workflow, "event": event or run.get("event", ""), "head_sha": sha,
                "run_id": run_id, "attempt": attempt}
        verdict = "rerun" if action == "rerun" else f"blocked: {reason}"
        out = [{**base, **r, "action": verdict} for r in rows] or [
            {**base, "job": "", "step": "", "category": "real_failure", "signature": "no failed job found",
             "action": verdict, "url": ""}]
        append_ledger(ledger, out)
        return {"category": _overall(rows), "action": action, "reason": reason, "rows": out}
    except Exception as error:  # noqa: BLE001  (fail closed: a triage error is never a rerun)
        return {"category": "", "action": "none", "reason": f"triage error: {type(error).__name__}: {str(error)[:120]}", "rows": []}


def _stale(gh: Gh, repo: str, workflow: str, expected_sha: str, run: dict) -> str:
    """Re-read right before the rerun: same sha as the caller's, newest run for it, still the judged attempt."""
    now = json.loads(gh("api", f"repos/{repo}/actions/runs/{run['id']}"))
    if now["head_sha"] != expected_sha:
        return "head sha moved; this run is stale"
    if now["run_attempt"] != run["run_attempt"] or now.get("status") != "completed":
        return "run attempt changed; someone already reran it"
    newest = newest_run(gh, repo, workflow, expected_sha)
    return "" if newest and newest["id"] == run["id"] else "a newer run exists for this sha"


def _overall(rows: list[dict]) -> str:
    cats = {r["category"] for r in rows}
    for worst in ("real_failure", "env_drift", "infra"):
        if worst in cats:
            return worst
    return "real_failure"


def describe(result: dict, run_id: int) -> list[str]:
    """Operator lines: the classification, the action and a log link per failed job."""
    lines = [f"[ci-triage] run {run_id}: {result['category'] or 'unknown'}; action {result['action']}"
             + (f" ({result['reason']})" if result["reason"] else "")]
    for r in result["rows"][:6]:
        lines.append(f"[ci-triage]   {r['category']} {r['job']} / {r['step'] or '-'}: {r['signature']} {r.get('url', '')}".rstrip())
    if len(result["rows"]) > 6:
        lines.append(f"[ci-triage]   ... {len(result['rows']) - 6} more failed jobs in the ledger")
    return lines


def backlog_lines(ledger: Path, now: float, window_s: int = 24 * 3600, shown: int = 5) -> list[str]:
    """Land-tick backlog lines: runs of the last day a person must look at (anything not infra-rerun)."""
    runs: dict[tuple, dict] = {}
    for r in read_ledger(ledger):
        if now - r.get("t", 0) <= window_s and r.get("action") != "rerun" and r.get("category"):
            runs.setdefault((r.get("run_id"), r.get("attempt")), r)
    rows = sorted(runs.values(), key=lambda r: r["t"], reverse=True)
    if not rows:
        return []
    out = [f"[backlog] ci-triage: {len(rows)} red runs need a person in 24 h (ALERT)"]
    out += [f"[backlog]   run {r['run_id']}#{r['attempt']} {r['category']} {r['job']} / {r['step'] or '-'}: {r['signature']} {r.get('url', '')}"
            .rstrip() for r in rows[:shown]]
    return out
