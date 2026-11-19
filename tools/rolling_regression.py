"""24/7 continuous rolling regression engine (D-1052).

Combines closure-hashed shard keys with forced TTL watermarks, 30-minute GHA
rolling sweeps, preemptive WARM_BATCH=1 lab micro-warming, 1x same-SHA nodeid
reruns, and two-stage closure-filtered single-nodeid bisect.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

TOOLS = Path(__file__).resolve().parent
for _extra in (str(TOOLS), str(TOOLS / "harness"), str(TOOLS / "remote"), str(TOOLS.parent / "test")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import affected_ci  # noqa: E402
import affected_closure  # noqa: E402
import affected_exclusive  # noqa: E402
import affected_tests  # noqa: E402
import known_failures  # noqa: E402
import land_mainred  # noqa: E402
import land_queue  # noqa: E402
import work_queue  # noqa: E402

ACT_ENTRY = next(e for e in affected_ci.CI_FULL_MATRIX if e["name"] == "omx-act-cpu")
ROOT_TEST_ENTRY = {"name": "root-test", "invocations": [["test"]]}
EXCLUDED_PREFIXES = ("integrations/simulation/", "learning/envs/isaac/", "middleware/devices/omx/adapter/")

CORE_TTL_S = 12 * 3600
LAB_TTL_S = 24 * 3600
ALONE_TTL_S = 48 * 3600
GHA_BATCH_LIMIT = 4
WARM_BATCH = 1
MAX_KEYS_PER_SHARD = 3
DISK_GC_TRIGGER_GB = 28.0
DISK_HARD_FLOOR_GB = 18.0
SUITE_HEADROOM_GB = 5.0
STATE_FILE = "rosy-rolling-sweep.json"
GLOBAL_SEAM_PATHS = (
    "pyproject.toml", "conftest.py", "pytest.ini", "tools/harness", "test/conftest.py",
    "test/known_failures.txt", "test/flaky_quarantine.txt", ".github/workflows/ci.yml",
    "deploy/robot/pinky_pro/image/device-python-requirements.txt",
)


def _git(wt: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def common_dir(wt: Path) -> Path:
    out = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else wt / ".git"


def state_path(wt: Path) -> Path:
    return common_dir(wt) / STATE_FILE


def load_state(wt: Path, explicit: Path | None = None) -> dict:
    try:
        data = json.loads((explicit or state_path(wt)).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"shards": data.get("shards") or {}, "open_culprits": data.get("open_culprits") or {}}
    except (OSError, ValueError):
        pass
    return {"shards": {}, "open_culprits": {}}


def save_state(wt: Path, state: dict, explicit: Path | None = None) -> Path:
    p = explicit or state_path(wt)
    p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=p.parent, delete=False, suffix=".tmp") as tmp:
        tmp.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, p)
    return p


@functools.lru_cache(maxsize=16)
def tree_map(wt_str: str, sha: str) -> dict[str, str]:
    res = _git(Path(wt_str), "ls-tree", "-r", sha)
    if res.returncode != 0:
        return {}
    return {path: meta.split()[2] for line in res.stdout.splitlines() if "\t" in line
            for meta, path in (line.split("\t", 1),) if len(meta.split()) >= 3}


@functools.lru_cache(maxsize=4)
def _repo_closure(wt_str: str, sha: str):
    wt = Path(wt_str)
    if not (wt / "tools/harness/harness.yaml").is_file():
        return None, None
    repo = affected_tests.Repo.load(wt, rev=sha)
    return repo, affected_closure.Closure(repo)


def _path_digest(tmap: dict[str, str], target: str) -> str:
    clean = target.replace("\\", "/").split("::", 1)[0].rstrip("/")
    if clean in tmap:
        return tmap[clean]
    items = sorted((p, oid) for p, oid in tmap.items() if p.startswith(clean + "/"))
    return "missing" if not items else hashlib.sha256(
        "".join(f"{p}:{oid}\n" for p, oid in items).encode("utf-8")).hexdigest()


def work_queue_env(word: str) -> bool:
    return bool(re.match(r"^ROSY_[A-Z0-9_]*=", word))


def posix_parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _shard_targets(shard: dict) -> list[str]:
    return sorted(dict.fromkeys(
        w.replace("\\", "/").split("::", 1)[0]
        for inv in shard.get("invocations") or () for w in inv if not w.startswith("-") and not work_queue_env(w)
    ))


def shard_key(wt: Path, sha: str, shard: dict, use_closure: bool = True) -> str | None:
    """Closure SHA256 for resolvable shards; None for cross-repo root-test shards."""
    name = str(shard.get("name", ""))
    tmap = {} if (shard.get("unresolvable") or name.startswith("root-test")) else tree_map(str(wt.resolve()), sha)
    if not tmap:
        return None
    targets, extra = _shard_targets(shard), set()
    for t in targets:
        parent = posix_parent(t)
        while parent:
            extra.update(cfg for cfg in (f"{parent}/conftest.py", f"{parent}/__init__.py") if cfg in tmap)
            parent = posix_parent(parent)
    if use_closure:
        repo, closure = _repo_closure(str(wt.resolve()), sha)
        if repo is not None and closure is not None:
            for t in targets:
                if mod := repo.module_for(t):
                    extra.update([mod["path"], *(mod.get("source_paths") or ())])
                tfiles = [t] if (t.endswith(".py") and t in tmap) else [
                    p for p in repo.test_files if affected_tests._under(p, t)]
                for tf in tfiles:
                    extra.update(p for p in closure.reach(tf) if p != "?")
    payload = {
        "name": name, "ros": shard.get("ros", "none"), "invocations": shard.get("invocations", []),
        "global": {p: _path_digest(tmap, p) for p in GLOBAL_SEAM_PATHS},
        "targets": {t: _path_digest(tmap, t) for t in targets},
        "closure": {p: _path_digest(tmap, p) for p in sorted(extra)},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def ci_runnable(inv: list[str]) -> bool:
    """True when `inv` belongs to a gating GHA matrix entry rather than lab-exclusive hosts."""
    paths = [w.replace("\\", "/").split("::", 1)[0] for w in inv if not w.startswith("-")]
    if not paths or _has_h5_marker(inv):
        return False
    acts = set(ACT_ENTRY["invocations"][0])
    if any(a == p or a.startswith(p.rstrip("/") + "/") for p in paths for a in acts):
        return all(p in acts for p in paths)
    return any(e.get("gating", True) and all(
        any(p == r or p.startswith(r + "/") for ie in e["invocations"] for r in ie if not r.startswith("-"))
        for p in paths) for e in (*affected_ci.CI_FULL_MATRIX, ROOT_TEST_ENTRY) if e is not ACT_ENTRY)


def _has_h5_marker(inv: list[str]) -> bool:
    return (any(work_queue_env(w) or w.startswith("-ptools.g1_timing") for w in inv)
            or work_queue.lab_only(inv) or work_queue.host_alone(inv) or affected_exclusive.dedicated(inv)
            or any(w.replace("\\", "/").split("::", 1)[0].startswith(EXCLUDED_PREFIXES) for w in inv if not w.startswith("-")))


@functools.lru_cache(maxsize=4)
def _canonical_shards_cached(wt_str: str, sha: str) -> tuple[dict, ...]:
    wt = Path(wt_str)
    repo, _ = _repo_closure(wt_str, sha)
    repo = repo or affected_tests.Repo.load(wt, rev=sha or None)
    matrix = affected_ci.ci_matrix(repo, affected_tests.Selection("full", []))["include"]
    shards: list[dict] = []
    for entry in matrix:
        if entry.get("kind", "pytest") != "pytest":
            continue
        invs = list(entry.get("invocations") or [])
        alone = any(affected_exclusive.dedicated(i) or work_queue.host_alone(i) for i in invs)
        venue = "gha" if invs and all(ci_runnable(i) for i in invs) and not alone else "lab"
        shards.append({"name": entry["name"], "ros": entry.get("ros", "none"), "invocations": invs,
                       "gating": entry.get("gating", True), "venue": venue, "alone": alone,
                       "ttl_s": CORE_TTL_S if venue == "gha" else (ALONE_TTL_S if alone else LAB_TTL_S),
                       "est_gb": 6.0 if ("gz-sim" in entry["name"] or "isaac" in entry["name"]) else 2.0})
    if (wt / "middleware/devices/omx/adapter/test").is_dir():
        shards.append({"name": "omx-adapter-lab", "ros": "overlay", "invocations": [["middleware/devices/omx/adapter/test"]],
                       "gating": True, "venue": "lab", "alone": False, "ttl_s": LAB_TTL_S, "est_gb": 2.0})
    if (wt / "test/browser_scope.py").is_file() and (wt / "tools/land_browser.py").is_file():
        import land_browser
        b_paths = sorted(p for p in repo.test_files if p.endswith("_browser.py") and p != "test/test_monitoring_browser.py"
                         and not p.startswith(("operations/fleet/test/", "applications/fleet/test/")) and (wt / p).is_file())
        for idx, chunk in enumerate(land_browser.chunks(wt, b_paths, n=6) if b_paths else ()):
            shards.append({"name": f"lab-browser-{idx + 1}", "ros": "none", "invocations": [chunk], "gating": True,
                           "venue": "lab", "alone": work_queue.host_alone(chunk),
                           "ttl_s": ALONE_TTL_S if work_queue.host_alone(chunk) else LAB_TTL_S, "est_gb": 2.5})
    return tuple(shards)


def canonical_shards(wt: Path, sha: str | None = None) -> list[dict]:
    """Partition full CI matrix + H5 lab-only suites into venue='gha' or venue='lab' shards."""
    return [dict(s) for s in _canonical_shards_cached(str(wt.resolve()), sha or "")]


def shard_satisfied(entry_state: dict, key: str | None, ttl_s: int, now: float) -> bool:
    return bool(key and entry_state and key in (entry_state.get("recent_keys") or [])
                and (now - float(entry_state.get("last_real_run_ts", 0.0))) < ttl_s)


def _commit_distance(wt: Path, since_sha: str | None, head_sha: str) -> int:
    if not since_sha or since_sha == head_sha:
        return 1 if not since_sha else 0
    res = _git(wt, "rev-list", "--count", f"{since_sha}..{head_sha}")
    return int(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip().isdigit() else 1


def watermark(state: dict, shards: list[dict], wt: Path | None = None, sha: str | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    smap = state.get("shards") or {}
    timestamps = [float((smap.get(s["name"], {})).get("last_real_run_ts", 0.0)) for s in shards]
    sat = sum(1 for s in shards if shard_satisfied(
        smap.get(s["name"], {}),
        shard_key(wt, sha, s) if (wt and sha) else smap.get(s["name"], {}).get("last_key"),
        int(s.get("ttl_s", CORE_TTL_S)), now))
    oldest = min(timestamps) if timestamps else 0.0
    return {
        "total": len(shards), "satisfied": sat,
        "gha_total": sum(1 for s in shards if s.get("venue") == "gha"),
        "lab_total": sum(1 for s in shards if s.get("venue") == "lab"),
        "min_real_run_ts": oldest, "max_staleness_s": (now - oldest) if oldest > 0 else None,
    }


def select_gha_batch(wt: Path, sha: str, state: dict, limit: int = GHA_BATCH_LIMIT,
                     now: float | None = None, shards: list[dict] | None = None) -> list[dict]:
    """Pick up to `limit` CI-runnable shards for current HEAD sha, ordered by closure miss + risk/age."""
    now = time.time() if now is None else now
    smap = state.get("shards") or {}
    scored: list[tuple[float, float, str, dict]] = []
    for s in (shards if shards is not None else canonical_shards(wt, sha)):
        invs = s.get("invocations") or []
        st = smap.get(s["name"], {})
        if s.get("venue") != "gha" or not invs or any(_has_h5_marker(i) for i in invs):
            continue
        if shard_satisfied(st, (key := shard_key(wt, sha, s)), int(s.get("ttl_s", CORE_TTL_S)), now):
            continue
        last_ts = float(st.get("last_real_run_ts", 0.0))
        key_miss = 1000.0 if (key is None or key not in (st.get("recent_keys") or [])) else 0.0
        commits = _commit_distance(wt, st.get("verified_sha"), sha) if wt else int(st.get("unverified_commits", 1))
        age_hours = min(72.0, (now - last_ts) / 3600.0) if last_ts > 0 else 72.0
        score = key_miss + commits * (1.0 + float(s.get("risk_weight", 0.0))) + age_hours
        scored.append((score, -last_ts, s["name"], {**s, "sha": sha, "shard_key": key, "score": round(score, 2)}))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[3] for item in scored[:max(0, limit)]]


def _load_known(wt: Path) -> dict[str, str]:
    files = [wt / p for p in ("test/known_failures.txt", "test/flaky_quarantine.txt") if (wt / p).is_file()]
    return {k: v for fp in files for k, v in known_failures.load_known(fp.read_text(encoding="utf-8", errors="replace")).items()}


def run_with_nodeid_retry(invocations: list[list[str]], run_fn: Callable[[list[str]], tuple[int, str]],
                          known: dict[str, str]) -> dict:
    """Run shard invocations and retry NEW failing node IDs once on the same SHA."""
    outs, exit_code = [], 0
    for inv in invocations:
        c, out = run_fn(inv)
        outs.append(out)
        exit_code = exit_code or c
    combined = "\n".join(outs)
    new_bad = known_failures.compare(combined, known)[0] if exit_code or "FAILED " in combined or "ERROR " in combined else []
    flaky_cleared, persistent, rerun_out = [], [], ""
    if new_bad:
        r_code, rerun_out = run_fn(["-v", *new_bad])
        still_bad = set(known_failures.compare(rerun_out, known)[0])
        if r_code != 0 and not still_bad:
            still_bad = set(new_bad)
        flaky_cleared = [n for n in new_bad if n not in still_bad]
        persistent = [n for n in new_bad if n in still_bad]
    clean = (exit_code == 0 and not new_bad) or (bool(new_bad) and not persistent)
    return {"clean": clean, "exit_code": exit_code, "output": combined + ("\n" + rerun_out if rerun_out else ""),
            "flaky_cleared": flaky_cleared, "deterministic_failures": persistent}


def _mark_shard_green(state: dict, name: str, sha: str, key: str | None, now: float) -> None:
    st = state.setdefault("shards", {}).setdefault(name, {"recent_keys": []})
    st.update({"last_real_run_ts": now, "verified_sha": sha, "last_green_sha": sha})
    if key:
        st["last_key"] = key
        st["recent_keys"] = [key, *(k for k in (st.get("recent_keys") or []) if k != key)][:MAX_KEYS_PER_SHARD]


def _record_culprit(state: dict, sha: str, shard_name: str, nid: str, output: str, last_green: str, bisect_fn) -> dict | None:
    fp = land_mainred.fingerprint(output, nid) or "unknown"
    dedupe_key = f"{nid}::{fp}"
    culprits = state.setdefault("open_culprits", {})
    if bisect_fn and dedupe_key not in culprits:
        culprit = bisect_fn(nid, last_green)
        culprits[dedupe_key] = {"sha": sha, "shard": shard_name, "nodeid": nid, "fingerprint": fp, **culprit}
        return culprit
    return None


def record_gha_results(wt: Path, sha: str, state: dict, results: list[dict], now: float | None = None,
                       bisect_fn: Callable[[str, str, str], dict] | None = None) -> dict:
    """Merge finished sweep shard outcomes into rolling state JSON and trigger bisect on persistent failures."""
    now, smap = time.time() if now is None else now, state.setdefault("shards", {})
    for res in results:
        name = res["name"]
        st = smap.setdefault(name, {"recent_keys": []})
        if res.get("flaky_cleared"):
            st["flaky_count"] = int(st.get("flaky_count", 0)) + len(res["flaky_cleared"])
        if res.get("clean"):
            _mark_shard_green(state, name, sha, res.get("shard_key"), now)
        else:
            st.update({"last_failure_sha": sha, "last_failure_ts": now})
            last_green = st.get("last_green_sha") or st.get("verified_sha") or ""
            for nid in (res.get("deterministic_failures") or ()) if bisect_fn else ():
                _record_culprit(state, sha, name, nid, res.get("output", ""), last_green,
                                lambda _n, lg, _nm=name: bisect_fn(_nm, _n, lg))
    return state


def queue_busy(wt: Path) -> bool:
    qdir = common_dir(wt) / land_queue.QUEUE
    return qdir.is_dir() and bool(land_queue.ahead(qdir, Path("~")))


def evaluate_disk_budget(free_gb: float | None, est_gb: float = 2.0,
                         gc_fn: Callable[[], float | None] | None = None) -> tuple[bool, str]:
    required_gb = max(DISK_HARD_FLOOR_GB, float(est_gb) + SUITE_HEADROOM_GB)
    if free_gb is None:
        return True, "probe_unknown"
    updated = gc_fn() if float(free_gb) < DISK_GC_TRIGGER_GB and gc_fn else None
    current = float(free_gb if updated is None else updated)
    return (True, f"ok:{current:.1f}GB") if current >= required_gb else (False, f"low_disk:{current:.1f}GB<{required_gb:.1f}GB")


def run_preemptible(cmd_or_factory, poll_preempt: Callable[[], bool], poll_s: float = 0.15,
                    term_grace_s: float = 0.4, cwd: Path | None = None, env: dict | None = None) -> tuple[int, str, bool]:
    """Run a child process and terminate it in <1s if `poll_preempt()` turns True."""
    proc = (cmd_or_factory() if callable(cmd_or_factory) else
            subprocess.Popen(cmd_or_factory, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"))
    chunks: list[str] = []
    reader = threading.Thread(target=lambda: chunks.extend(proc.stdout or ()), daemon=True)
    reader.start()
    preempted = False
    while proc.poll() is None:
        if poll_preempt():
            preempted = True
            proc.terminate()
            deadline = time.monotonic() + term_grace_s
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            break
        time.sleep(poll_s)
    reader.join(timeout=0.5)
    return (130 if preempted else int(proc.returncode or 0)), "".join(chunks), preempted


def lab_micro_warm(wt: Path, sha: str | None = None, state: dict | None = None, *,
                   shards: list[dict] | None = None, runner=None, queue_check=None,
                   disk_probe=None, gc_fn=None, bisect_fn=None, now: float | None = None) -> dict:
    """Run at most WARM_BATCH=1 H5 lab shard when landing queue is idle and disk headroom allows."""
    now = time.time() if now is None else now
    qcheck = queue_check or (lambda: queue_busy(wt))
    if qcheck():
        return {"status": "skipped_queue", "ran": 0, "warmed": 0}
    sha = sha or _git(wt, "rev-parse", "main").stdout.strip()
    state = state if state is not None else load_state(wt)
    smap = state.setdefault("shards", {})
    candidates = [
        (0 if key is None or key not in (st.get("recent_keys") or []) else 1,
         float(st.get("last_real_run_ts", 0.0)), s["name"], {**s, "shard_key": key})
        for s in (shards if shards is not None else canonical_shards(wt, sha))
        if s.get("venue") == "lab"
        for st in (smap.get(s["name"], {}),)
        for key in (shard_key(wt, sha, s),)
        if not shard_satisfied(st, key, int(s.get("ttl_s", LAB_TTL_S)), now)
    ]
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    if not candidates:
        return {"status": "all_satisfied", "ran": 0, "warmed": 0}
    target = candidates[0][3]
    ok_disk, disk_note = evaluate_disk_budget(disk_probe() if disk_probe else None, float(target.get("est_gb", 2.0)), gc_fn=gc_fn)
    if not ok_disk:
        return {"status": disk_note, "ran": 0, "warmed": 0, "shard": target["name"]}
    pre_flag, known = False, _load_known(wt)

    def _run_inv(inv: list[str]) -> tuple[int, str]:
        nonlocal pre_flag
        env_vars, args = _split_env(inv)
        c, txt, pre = run_preemptible([sys.executable, "-m", "pytest", *args, "-v", *known_failures.NO_ROS_LAUNCH_PLUGINS],
                                      qcheck, cwd=wt, env={**os.environ, **env_vars})
        pre_flag = pre_flag or pre
        return c, txt

    if runner is not None:
        code, out, pre_flag = runner(target, qcheck)
        new_bad = [] if pre_flag else (known_failures.compare(out, known)[0] if code or "FAILED " in out or "ERROR " in out else [])
    else:
        res = run_with_nodeid_retry(target["invocations"], _run_inv, known)
        code, out, new_bad = (0 if res["clean"] else res["exit_code"] or 1), res["output"], res["deterministic_failures"]
    if pre_flag:
        return {"status": "preempted", "ran": 0, "warmed": 0, "shard": target["name"]}
    if code == 0 and not new_bad:
        _mark_shard_green(state, target["name"], sha, target.get("shard_key"), now)
        save_state(wt, state)
        return {"status": "warmed", "ran": 1, "warmed": 1, "shard": target["name"]}
    st = smap.setdefault(target["name"], {"recent_keys": []})
    st.update({"last_failure_sha": sha, "last_failure_ts": now})
    if new_bad and (wt / ".git").exists():
        try:
            land_mainred.red(wt, sha, new_bad, out, [w for w in target["invocations"][0] if work_queue_env(w)], by="rolling-lab")
        except Exception:  # noqa: BLE001
            pass
    culprit = (_record_culprit(state, sha, target["name"], new_bad[0], out, st.get("last_green_sha") or "",
                               lambda nid, lg: bisect_fn(target, nid, lg)) if new_bad and bisect_fn else None)
    save_state(wt, state)
    return {"status": "failed", "ran": 1, "warmed": 0, "shard": target["name"], "failures": new_bad, "culprit": culprit}


def touched_first_parent_commits(wt: Path, last_green: str, fail_sha: str, shard: dict) -> tuple[list[str], list[str]]:
    """Return `(all_commits, closure_touched_commits)` oldest-to-newest across `last_green..fail_sha`."""
    res = _git(wt, "rev-list", "--first-parent", "--reverse", f"{last_green}..{fail_sha}")
    commits = [line.strip() for line in res.stdout.splitlines() if line.strip()] if res.returncode == 0 else []
    touched = [c for c in commits if not (p := _git(wt, "rev-parse", f"{c}^").stdout.strip())
               or shard_key(wt, c, shard) != shard_key(wt, p, shard)]
    return commits, touched


def _split_env(inv: list[str]) -> tuple[dict[str, str], list[str]]:
    env_vars, rest = {}, list(inv)
    while rest and work_queue_env(rest[0]):
        k, v = rest.pop(0).split("=", 1)
        env_vars[k] = v
    return env_vars, rest


def bisect_culprit(commits: list[str], nodeid: str, runner: Callable[[str, str], bool],
                   touched_commits: list[str] | None = None, base_green: str | None = None) -> dict:
    """Two-stage single-nodeid fast bisect: Stage 1 closure candidates m, Stage 2 full fallback."""
    if not commits:
        return {"culprit": None, "stage": "empty", "probes": 0}
    probes, cache = 0, {}

    def probe(c: str) -> bool:
        nonlocal probes
        if c not in cache:
            probes += 1
            cache[c] = bool(runner(c, nodeid))
        return cache[c]

    def bsearch(seq: list[str]) -> str | None:
        lo, hi, hit = 0, len(seq), None
        while lo < hi:
            mid = (lo + hi) // 2
            if not probe(seq[mid]):
                hit, hi = seq[mid], mid
            else:
                lo = mid + 1
        return hit

    m = [c for c in commits if c in set(touched_commits or ())]
    if m and len(m) < len(commits) and (cand := bsearch(m)) is not None:
        idx = commits.index(cand)
        prev_sha = commits[idx - 1] if idx > 0 else base_green
        if prev_sha is None or probe(prev_sha):
            return {"culprit": cand, "stage": "closure", "probes": probes}
    pass_idx = [commits.index(c) for c, ok in cache.items() if ok and c in commits]
    fail_idx = [commits.index(c) for c, ok in cache.items() if not ok and c in commits]
    lo, hi = (max(pass_idx) + 1) if pass_idx else 0, (min(fail_idx) + 1) if fail_idx else len(commits)
    culprit = bsearch(commits[lo:hi]) or (commits[min(fail_idx)] if fail_idx else commits[-1])
    return {"culprit": culprit, "stage": "full_fallback", "probes": probes}


def _matching_shard(wt: Path, sha: str, inv: list[str]) -> dict:
    for s in canonical_shards(wt, sha):
        if inv in (s.get("invocations") or []):
            return s
    return {"name": "inv-" + hashlib.sha1(" ".join(inv).encode("utf-8")).hexdigest()[:12], "ros": "none", "invocations": [inv]}


def is_closure_warm(wt: Path, sha: str, inv: list[str], state: dict, now: float | None = None) -> bool:
    """Hook for tools/land_cache.py: whether this invocation's closure key is warm within TTL."""
    sh = _matching_shard(wt, sha, inv)
    ttl = (ALONE_TTL_S if _has_h5_marker(inv) and work_queue.host_alone(inv)
           else (LAB_TTL_S if _has_h5_marker(inv) else CORE_TTL_S))
    return shard_satisfied((state.get("shards") or {}).get(sh["name"], {}), shard_key(wt, sha, sh), ttl,
                           time.time() if now is None else now)


def note_warm_pass(wt: Path, sha: str, inv: list[str], state: dict, now: float | None = None) -> None:
    """Hook for tools/land_cache.py: record closure key pass for warm_main reuse."""
    sh = _matching_shard(wt, sha, inv)
    _mark_shard_green(state, sh["name"], sha, shard_key(wt, sha, sh), time.time() if now is None else now)


_CI_BROWSER = ("operations/fleet/test", "applications/fleet/test",
               "middleware/core/gateway/test/test_account_pipeline.py", "test/test_monitoring_browser.py")


def _run_gha_entry_cmd(wt: Path, entry: dict, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    def _exec(inv: list[str]) -> tuple[int, str]:
        env_vars, args = _split_env(inv)
        if any(p.startswith(_CI_BROWSER) for p in args if not p.startswith("-")):
            env_vars.setdefault("ROSY_RUN_BROWSER_TESTS", "1")
        res = subprocess.run([sys.executable, "-m", "pytest", *args, "-v", "--continue-on-collection-errors", *known_failures.NO_ROS_LAUNCH_PLUGINS],
                             cwd=wt, env={**os.environ, **env_vars}, capture_output=True, text=True, errors="replace")
        return res.returncode, res.stdout + ("\n" + res.stderr if res.stderr else "")
    outcome = run_with_nodeid_retry(entry["invocations"], _exec, _load_known(wt))
    (out_dir / f"{entry['name']}.log").write_text(outcome["output"], encoding="utf-8")
    summary = {**{k: outcome[k] for k in ("clean", "exit_code", "flaky_cleared", "deterministic_failures")},
               "name": entry["name"], "shard_key": entry.get("shard_key")}
    (out_dir / f"{entry['name']}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if outcome["clean"] else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    specs = {"gha-plan": (("--sha", dict(required=True)), ("--state", dict(type=Path)), ("--limit", dict(type=int, default=GHA_BATCH_LIMIT)), ("--json-out", dict(type=Path))),
             "gha-run-entry": (("--entry-json", dict(required=True)), ("--out-dir", dict(type=Path, required=True))),
             "gha-record": (("--sha", dict(required=True)), ("--state", dict(type=Path)), ("--results-dir", dict(type=Path, required=True)),
                            ("--out-state", dict(type=Path, required=True)), ("--summary-out", dict(type=Path))),
             "lab-warm": (("--main", dict(default="main")),), "status": ()}
    for name, opts in specs.items():
        sp = sub.add_parser(name)
        for flag, kw in opts:
            sp.add_argument(flag, **kw)
    args = p.parse_args(argv)
    wt = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip() or Path.cwd())
    if args.cmd == "gha-plan":
        state = load_state(wt, args.state)
        batch = select_gha_batch(wt, args.sha, state, limit=args.limit)
        if args.json_out:
            args.json_out.write_text(json.dumps({"include": batch, "watermark": watermark(state, canonical_shards(wt, args.sha), wt, args.sha)}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"include": batch}))
    elif args.cmd == "gha-run-entry":
        return _run_gha_entry_cmd(wt, json.loads(args.entry_json), args.out_dir)
    elif args.cmd == "gha-record":
        state = load_state(wt, args.state)
        results = [json.loads(fp.read_text(encoding="utf-8")) for fp in sorted(args.results_dir.rglob("*.json"))]
        record_gha_results(wt, args.sha, state, results)
        save_state(wt, state, explicit=args.out_state)
        wm = watermark(state, canonical_shards(wt, args.sha), wt, args.sha)
        if args.summary_out:
            args.summary_out.write_text(f"## Rolling Sweep Watermark ({args.sha[:10]})\n- Satisfied: `{wm['satisfied']}/{wm['total']}`\n- Recorded: `{len(results)}`\n", encoding="utf-8")
        print(json.dumps(wm))
    elif args.cmd == "lab-warm":
        print(json.dumps(lab_micro_warm(wt, _git(wt, "rev-parse", args.main).stdout.strip())))
    else:
        print(json.dumps(watermark(load_state(wt), canonical_shards(wt)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
