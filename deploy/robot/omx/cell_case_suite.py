#!/usr/bin/env python3
"""Replay the arm S cell's problem cases (cell_cases.py) in Isaac on the model PC and say which still match the
real outcome (D-872). Run it from a checkout whose committed SHA the model PC can fetch: each case is an
``arm-s-cell-case`` run of the Isaac run manager (tools/remote/remote_isaac.py check → start → status → fetch).

A case matches when Isaac's judgement equals the outcome the real cell saw; a case without one (a candidate)
is reported as measured. Exit 1 when any case stopped matching or a run gave no judgement: fix that before
the real arm repeats the case.

  cell_case_suite.py --suite suite.json --sha <committed sha> --out runs/  [--only <id> ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REMOTE = ROOT / "tools/remote/remote_isaac.py"
SCENARIO = "arm-s-cell-case"
DONE = {"SUCCEEDED", "FAILED", "STOPPED", "UNKNOWN"}
REPORT = "arm-s-cell-report.json"


def remote(*args: str) -> dict:
    result = subprocess.run([sys.executable, str(REMOTE), *args], capture_output=True, text=True, cwd=ROOT)
    try:
        value = json.loads(result.stdout)
    except ValueError:
        value = None
    if result.returncode or not isinstance(value, dict):
        raise RuntimeError(f"remote_isaac {args[0]} failed: {(result.stderr or result.stdout).strip()[-400:]}")
    return value


def judgement(snapshot: Path) -> dict | None:
    """The verified report's judgement, when the run manager published it."""
    report = snapshot / REPORT
    return json.loads(report.read_text())["judgement"] if report.is_file() else None


def run_case(case: dict, sha: str, out: Path, *, poll=20.0, max_wait=3600.0, sleep=time.sleep,
             clock=time.monotonic, call=remote) -> dict:
    """One case through the run manager; a GPU-busy admission refusal waits and asks again until max_wait."""
    # short: snapshot paths (run id, uuid, temp names) passed Windows' 260 characters under a long case id
    folder = out / hashlib.sha256(case["id"].encode()).hexdigest()[:8]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "case-id.txt").write_text(case["id"])
    (folder / "config.json").write_text(json.dumps({"seed": 0, "case": case["sim"]}))
    check = call("check", "--scenario", SCENARIO, "--config", str(folder / "config.json"), "--sha", sha)
    began, attempt = clock(), 0
    while True:
        attempt += 1
        request, receipt = folder / f"request-{attempt}.json", folder / f"receipt-{attempt}.json"
        request.write_text(json.dumps({"request_id": uuid.uuid4().hex, "scenario_id": SCENARIO,
                                       "config": {"seed": 0, "case": case["sim"]}, "source_sha": sha,
                                       "expected_input_sha256": check["input_sha256"]}))
        row = call("start", "--request", str(request), "--receipt", str(receipt))
        while row.get("status") not in DONE:
            sleep(poll)
            row = call("status", "--receipt", str(receipt))
            row = row.get("run", row)
        refused = row["status"] == "FAILED" and "admission" in json.dumps(row.get("error") or "")
        if not refused or clock() - began >= max_wait:
            break
        sleep(max(poll, 60.0))  # another owner holds the GPU; the worker admits only an idle one
    snapshot = Path(call("fetch", "--receipt", str(receipt))["snapshot_directory"])
    found = judgement(snapshot)
    expect = case["sim"]["expect"]
    gap = case.get("isaac_gap")
    known = bool(found and gap and found["result"] == gap["result"])  # Isaac, not the cell, differs here
    return {"id": case["id"], "expect": expect, "run_id": row.get("run_id"), "status": row["status"],
            "result": (found or {}).get("result"), "matches": None if found is None or expect is None or known
            else found["result"] == expect, "known_gap": gap["why"] if known else None, "judgement": found,
            "snapshot": str(snapshot)}


def verdict(rows: list[dict]) -> int:
    """0 when every case with an expectation reproduced it; 1 when one did not or gave no judgement."""
    return int(any(r["matches"] is False or (r["expect"] is not None and r["judgement"] is None) for r in rows))


def table(rows: list[dict], skipped: list[dict]) -> str:
    lines = ["| case | expected | Isaac | run | verdict |", "|---|---|---|---|---|"]
    for r in rows:
        mark = ("measured" if r["expect"] is None and r["judgement"] else "no judgement" if r["judgement"] is None
                else f"known Isaac gap: {r['known_gap']}" if r.get("known_gap") else "matches" if r["matches"]
                else "DIFFERS")
        lines.append(f"| {r['id']} | {r['expect']} | {r['result']} | {r['status']} {r['run_id']} | {mark} |")
    lines += [f"| {c['id']} | - | not simulated: {c['why_not_sim']} | - | {c['covered_by']} |" for c in skipped]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", required=True, type=Path, help="from cell_cases.py --out")
    parser.add_argument("--sha", required=True, help="committed source the model PC runs")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--only", action="append", help="case id (repeatable)")
    parser.add_argument("--max-wait-min", type=float, default=60.0, help="per case, while the GPU is busy")
    args = parser.parse_args(argv)
    cases = json.loads(args.suite.read_text())["cases"]
    chosen = [c for c in cases if "sim" in c and (not args.only or c["id"] in args.only)]
    skipped = [c for c in cases if "sim" not in c and (not args.only or c["id"] in args.only)]
    rows = []
    for case in chosen:
        try:
            rows.append(run_case(case, args.sha, args.out, max_wait=args.max_wait_min * 60))
        except RuntimeError as exc:
            rows.append({"id": case["id"], "expect": case["sim"]["expect"], "run_id": None, "status": "ERROR",
                         "result": None, "matches": None, "judgement": None, "error": str(exc)})
        print(json.dumps({k: rows[-1][k] for k in ("id", "status", "result", "matches")}), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "suite-report.json").write_text(json.dumps({"sha": args.sha, "rows": rows}, indent=1))
    (args.out / "suite-report.md").write_text(table(rows, skipped))
    print(table(rows, skipped))
    return verdict(rows)


if __name__ == "__main__":
    sys.exit(main())
