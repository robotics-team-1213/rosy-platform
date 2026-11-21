#!/usr/bin/env python3
"""Record one human review of a supervised task in the operating envelope (D-911), in one step.

    python3 cell_envelope_review.py list <work-dir>/attempts.jsonl
    python3 cell_envelope_review.py add --attempts <work-dir>/attempts.jsonl --envelope <operating_envelope_path> \
        --task-sha256 <key from list> --reviewed-by <name> --evidence-ref <what was checked> \
        --min-attempts N --min-success-rate R --home-tolerance U --confirm-physical-review

This is the existing review procedure (README "검증된 native 셀 작업 범위") made a single command; it changes no rule. The
reviewer's name, the evidence reference and the three acceptance numbers have no defaults and are never filled in by software
(D-911 3/7: a success does not promote itself; the numbers are set before the trials by the reviewer). The task key, scope and
`attempts_sha256` are copied from the trials in the ledger so they cannot be mistyped. Nothing is written when the trials do not
meet the numbers the reviewer gave (the review would never pass), or the task is not a hardware task, or it is already reviewed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from cell_envelope import SCHEMA, review_candidates


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def add_review(attempts: Path, envelope: Path, *, task_sha256: str, reviewed_by: str, evidence_ref: str, min_attempts: int,
               min_success_rate: float, home_tolerance_units: float, confirmed: bool) -> dict:
    """Append the review and return it; raises ValueError (nothing written) when it must not be recorded."""
    if not confirmed:
        raise ValueError("a person must confirm the physical evidence was reviewed (--confirm-physical-review)")
    if not (isinstance(reviewed_by, str) and reviewed_by.strip() and isinstance(evidence_ref, str) and evidence_ref.strip()):
        raise ValueError("reviewed_by and evidence_ref are required")
    if type(min_attempts) is not int or min_attempts < 1 or not 0 < min_success_rate <= 1 or not home_tolerance_units > 0:
        raise ValueError("min_attempts >= 1, 0 < min_success_rate <= 1 and home_tolerance_units > 0 are required")
    candidate = review_candidates(_rows(attempts)).get(task_sha256)
    if candidate is None:
        raise ValueError("no such task in this attempts ledger")
    if candidate.get("scope") != "hardware":
        raise ValueError("only a hardware task can be reviewed; simulation trials are not hardware evidence")
    if candidate["attempts"] < min_attempts or candidate["successes"] / max(candidate["attempts"], 1) < min_success_rate:
        raise ValueError(f"the trials ({candidate['successes']}/{candidate['attempts']}) do not meet the review numbers; nothing recorded")
    document = json.loads(envelope.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != SCHEMA or not isinstance(document.get("reviews"), list):
        raise ValueError("not an operating envelope document")
    if any(r.get("task_sha256") == task_sha256 for r in document["reviews"] if isinstance(r, dict)):
        raise ValueError("this task already has a review; duplicates are not allowed")
    review = {"task_sha256": task_sha256, "scope": candidate["scope"], "reviewed_by": reviewed_by.strip(),
              "evidence_ref": evidence_ref.strip(), "attempts_sha256": candidate["attempts_sha256"], "min_attempts": min_attempts,
              "min_success_rate": min_success_rate, "home_tolerance_units": home_tolerance_units}
    document["reviews"].append(review)
    tmp = envelope.with_suffix(".tmp")
    tmp.write_text(json.dumps(document, indent=2), encoding="utf-8")
    os.replace(tmp, envelope)
    return review


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("attempts", type=Path)
    add = sub.add_parser("add")
    add.add_argument("--attempts", required=True, type=Path)
    add.add_argument("--envelope", required=True, type=Path)
    add.add_argument("--task-sha256", required=True)
    add.add_argument("--reviewed-by", required=True)
    add.add_argument("--evidence-ref", required=True)
    add.add_argument("--min-attempts", required=True, type=int)
    add.add_argument("--min-success-rate", required=True, type=float)
    add.add_argument("--home-tolerance", required=True, type=float)
    add.add_argument("--confirm-physical-review", action="store_true")
    args = ap.parse_args(argv)
    if args.command == "list":
        tasks = review_candidates(_rows(args.attempts))
        print(json.dumps({k: {f: v[f] for f in ("scope", "attempts", "successes", "attempts_sha256", "observed_success_fraction")}
                          for k, v in tasks.items()}, indent=1))
        return 0
    try:
        review = add_review(args.attempts, args.envelope, task_sha256=args.task_sha256, reviewed_by=args.reviewed_by,
                            evidence_ref=args.evidence_ref, min_attempts=args.min_attempts, min_success_rate=args.min_success_rate,
                            home_tolerance_units=args.home_tolerance, confirmed=args.confirm_physical_review)
    except (ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"recorded": review}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
