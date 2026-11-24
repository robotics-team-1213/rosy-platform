"""Strict gate for factory flow run receipts (``rosy.factory-flow.receipt.v1``).

One receipt file is one JSON array of stage receipts for a single factory run::

    [{"schema": "rosy.factory-flow.receipt.v1",
      "run_id": "run-2026-11-23-001", "task_id": "task-417",
      "robot_id": "rosy_01", "cargo_id": "cargo-r08-7",
      "site_map_sha256": "<64 hex>", "stage": "c2_departure", "status": "pass",
      "evidence": [{"path": "ev/c2_departure-0.png", "sha256": "<64 hex>"}]},
     ... one receipt per stage, in STAGES order ...]

The file passes only when every documented field is present with no unknown
field; the seven stages each appear exactly once in STAGES order;
run_id/task_id/robot_id/cargo_id/site_map_sha256 are identical in every
receipt; every status is ``pass``; no field is a placeholder (TODO,
"simulated", a 64-times repeated hex digit, ...); every evidence path is a
relative forward-slash path that stays inside the receipt file's directory
and names an existing file whose SHA-256 matches; and no evidence path is
reused within a receipt or across stages.

Exit 0 prints the binding and stage report; exit 1 prints one ``REJECT``
line per problem on stderr. The verdict covers receipt integrity and stage
presence only -- it says nothing about the physical world. Physical truth
needs the native evidence reviewed separately (LOCAL evidence rules,
tools/sim/AGENTS.md).

Usage::

    python tools/sim/factory_flow_receipts.py RUN/receipts.json
    python tools/sim/factory_flow_receipts.py --self-check [--scratch DIR]

``--self-check`` writes a valid fixture plus one broken mutant per rejection
class into a fresh directory under ``--scratch`` (system temp by default) and
verifies each verdict. It is both the demo and the test of this file.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath

SCHEMA = "rosy.factory-flow.receipt.v1"
STAGES = ("c2_departure", "s1_yield", "s3_stop", "cell_claim",
          "arm_s_to_belt", "belt_transit", "ab_stack")
RECEIPT_FIELDS = frozenset({"schema", "run_id", "task_id", "robot_id", "cargo_id",
                            "site_map_sha256", "stage", "status", "evidence"})
EVIDENCE_FIELDS = frozenset({"path", "sha256"})
BINDING_FIELDS = ("run_id", "task_id", "robot_id", "cargo_id", "site_map_sha256")
TEXT_FIELDS = ("run_id", "task_id", "robot_id", "cargo_id", "stage", "status")
HEX64_RE = re.compile(r"[0-9a-fA-F]{64}")
# Values no real run id, status or evidence path ever carries.
PLACEHOLDERS = frozenset({"", "-", "?", "n/a", "na", "nil", "none", "null", "tbd",
                          "todo", "placeholder", "simulated", "simulation", "sim",
                          "dummy", "fake", "example", "sample", "test", "xxx"})


def is_placeholder(value: str) -> bool:
    return value.strip().lower() in PLACEHOLDERS


def is_placeholder_hash(value: str) -> bool:
    """64 x ``0`` / ``f`` / any single repeated hex digit."""
    return len(set(value.lower())) == 1


def sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def path_escape(rel: str) -> str | None:
    """Why ``rel`` is not a safe evidence path relative to the receipt file."""
    if "\\" in rel:
        return f"backslash in evidence path {rel!r}"
    posix = PurePosixPath(rel)
    if posix.is_absolute() or PureWindowsPath(rel).is_absolute() or PureWindowsPath(rel).drive:
        return f"absolute evidence path {rel!r}"
    if posix.parts == ():
        return "empty evidence path"
    if any(part == ".." for part in posix.parts):
        return f"evidence path escapes the receipt directory: {rel!r}"
    return None


def verify(receipts_path: Path, *, expected_stages=STAGES) -> tuple[list[str], dict[str, object]]:
    """All problems found in the receipt file, plus a report summary."""
    errors: list[str] = []
    summary: dict[str, object] = {"path": str(receipts_path)}
    try:
        raw = json.loads(receipts_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"cannot read receipt file: {exc}"], summary
    except (json.JSONDecodeError, UnicodeError) as exc:
        return [f"invalid JSON: {exc}"], summary
    if not isinstance(raw, list):
        return ["receipt file is not a JSON array"], summary
    if not raw:
        return ["receipt file is an empty array"], summary

    base_dir = receipts_path.resolve().parent
    stages: list[str] = []
    bindings: dict[str, str] = {}
    seen_paths: set[Path] = set()
    verified_files = 0

    for i, rec in enumerate(raw):
        where = f"receipts[{i}]"
        if not isinstance(rec, dict):
            errors.append(f"{where}: receipt is not an object")
            continue
        missing = sorted(RECEIPT_FIELDS - rec.keys())
        unknown = sorted(rec.keys() - RECEIPT_FIELDS)
        if missing:
            errors.append(f"{where}: missing field(s): {', '.join(missing)}")
        if unknown:
            errors.append(f"{where}: unknown field(s): {', '.join(unknown)}")
        if rec.get("schema") != SCHEMA:
            errors.append(f"{where}: schema {rec.get('schema')!r} != {SCHEMA!r}")
        for field in TEXT_FIELDS:
            value = rec.get(field)
            if not isinstance(value, str):
                errors.append(f"{where}: {field} is not a string")
            elif is_placeholder(value):
                errors.append(f"{where}: {field} is a placeholder value {value!r}")
        site_hash = rec.get("site_map_sha256")
        if isinstance(site_hash, str):
            if not HEX64_RE.fullmatch(site_hash):
                errors.append(f"{where}: site_map_sha256 is not 64 hex chars")
            elif is_placeholder_hash(site_hash):
                errors.append(f"{where}: site_map_sha256 is a placeholder hash")
        stage = rec.get("stage")
        if isinstance(stage, str):
            stages.append(stage)
            if stage not in expected_stages:
                errors.append(f"{where}: unknown stage {stage!r}")
        status = rec.get("status")
        if isinstance(status, str) and status != "pass":
            errors.append(f"{where}: status {status!r} is not 'pass'")
        for field in BINDING_FIELDS:
            value = rec.get(field)
            if isinstance(value, str) and value and not is_placeholder(value):
                if field in bindings and bindings[field] != value:
                    errors.append(f"{where}: mixed binding {field}: "
                                  f"{bindings[field]!r} vs {value!r}")
                bindings.setdefault(field, value)

        evidence = rec.get("evidence")
        if not isinstance(evidence, list):
            errors.append(f"{where}: evidence is not a list")
            continue
        if not evidence:
            errors.append(f"{where}: evidence is empty")
            continue
        for j, entry in enumerate(evidence):
            at = f"{where}.evidence[{j}]"
            if not isinstance(entry, dict):
                errors.append(f"{at}: entry is not an object")
                continue
            emissing = sorted(EVIDENCE_FIELDS - entry.keys())
            eunknown = sorted(entry.keys() - EVIDENCE_FIELDS)
            if emissing:
                errors.append(f"{at}: missing field(s): {', '.join(emissing)}")
            if eunknown:
                errors.append(f"{at}: unknown field(s): {', '.join(eunknown)}")
            rel = entry.get("path")
            claimed = entry.get("sha256")
            if not isinstance(rel, str):
                errors.append(f"{at}: path is not a string")
                continue
            if not isinstance(claimed, str):
                errors.append(f"{at}: sha256 is not a string")
                continue
            if not HEX64_RE.fullmatch(claimed):
                errors.append(f"{at}: sha256 is not 64 hex chars")
                continue
            if is_placeholder_hash(claimed):
                errors.append(f"{at}: sha256 is a placeholder hash")
            if is_placeholder(rel):
                errors.append(f"{at}: path is a placeholder value {rel!r}")
            escape = path_escape(rel)
            if escape:
                errors.append(f"{at}: {escape}")
                continue
            try:
                path = (base_dir / Path(*PurePosixPath(rel).parts)).resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                errors.append(f"{at}: evidence file missing or unreadable: {rel}")
                continue
            if not path.is_relative_to(base_dir) or not path.is_file():
                errors.append(f"{at}: evidence must be a file inside the receipt directory: {rel}")
                continue
            if path in seen_paths:
                errors.append(f"{at}: duplicate evidence file: {rel}")
                continue
            seen_paths.add(path)
            actual = sha256_file(path)
            if actual is None:
                errors.append(f"{at}: evidence file missing or unreadable: {rel}")
            elif actual != claimed.lower():
                errors.append(f"{at}: hash mismatch for {rel}: file {actual} != receipt {claimed.lower()}")
            else:
                verified_files += 1

    counts = Counter(s for s in stages if s in expected_stages)
    for stage in expected_stages:
        if counts[stage] == 0:
            errors.append(f"missing stage {stage}")
        elif counts[stage] > 1:
            errors.append(f"duplicate stage {stage} ({counts[stage]} receipts)")
    if counts == dict.fromkeys(expected_stages, 1) and stages != list(expected_stages):
        errors.append(f"wrong stage order: {' -> '.join(stages)}")

    summary.update(bindings=bindings, stages=stages, receipts=len(raw),
                   evidence_files=verified_files)
    if not errors:
        summary["verified_receipts"] = raw
    return errors, summary


def print_report(summary: dict[str, object]) -> None:
    bindings = summary.get("bindings", {})
    print(f"PASS {SCHEMA}")
    print(f"run_id={bindings.get('run_id')} task_id={bindings.get('task_id')} "
          f"robot_id={bindings.get('robot_id')} cargo_id={bindings.get('cargo_id')}")
    print(f"site_map_sha256={bindings.get('site_map_sha256')}")
    print(f"stages: {' -> '.join(STAGES)} ({len(STAGES)}/{len(STAGES)})")
    print(f"evidence: {summary.get('evidence_files', 0)} file(s), sha256 verified")
    print("NOTE: receipt integrity and stage presence only; "
          "physical truth requires native evidence reviewed separately")


def dump(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_run(root: Path) -> list[dict]:
    """Deterministic valid fixture: evidence files written, receipts returned."""
    ev = root / "ev"
    ev.mkdir(parents=True, exist_ok=True)
    receipts = []
    for stage in STAGES:
        entries = []
        for i in range(2):
            data = f"factory-flow evidence {stage} {i}\n".encode()
            (ev / f"{stage}-{i}.png").write_bytes(data)
            entries.append({"path": f"ev/{stage}-{i}.png",
                            "sha256": hashlib.sha256(data).hexdigest()})
        receipts.append({"schema": SCHEMA, "run_id": "run-2026-11-23-001",
                         "task_id": "task-417", "robot_id": "rosy_01",
                         "cargo_id": "cargo-r08-7",
                         "site_map_sha256": hashlib.sha256(b"site-map").hexdigest(),
                         "stage": stage, "status": "pass", "evidence": entries})
    return receipts


def self_check(scratch: str | None) -> int:
    parent = Path(scratch) if scratch else None
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="factory-flow-receipts-", dir=scratch))
    ok_dir = base / "ok"
    receipts = build_run(ok_dir)
    dump(ok_dir / "receipts.json", receipts)
    failures: list[str] = []

    errors, _ = verify(ok_dir / "receipts.json")
    if errors:
        failures.append("ok")
        print(f"FAIL ok: valid fixture rejected ({errors[0]})")
    else:
        print(f"PASS ok: {len(STAGES)} stages, {sum(len(r['evidence']) for r in receipts)} evidence files")

    def check(name: str, payload: object, setup=None) -> None:
        case = base / "cases" / name
        case.mkdir(parents=True)
        shutil.copytree(ok_dir / "ev", case / "ev")
        dump(case / "receipts.json", payload)
        if setup:
            setup(case)
        errors, _ = verify(case / "receipts.json")
        if errors:
            print(f"PASS {name}: {errors[0]}")
        else:
            failures.append(name)
            print(f"FAIL {name}: broken mutant accepted")

    def mutant(name: str, change, setup=None) -> None:
        payload = copy.deepcopy(receipts)
        change(payload)
        check(name, payload, setup)

    mutant("wrong-order", lambda m: m.__setitem__(slice(0, 2), [m[1], m[0]]))
    mutant("duplicate-stage", lambda m: m.append(copy.deepcopy(m[3])))
    mutant("mixed-bindings", lambda m: m[2].__setitem__("robot_id", "rosy_02"))
    mutant("missing-evidence", lambda m: m[5].__setitem__("evidence", []))
    mutant("path-escape", lambda m: m[0]["evidence"][0].__setitem__("path", "../escape.png"),
           lambda case: (case.parent / "escape.png").write_bytes(
               (ok_dir / "ev" / "c2_departure-0.png").read_bytes()))
    mutant("hash-mismatch", lambda m: m[6]["evidence"][1].__setitem__(
        "sha256", ("0" if m[6]["evidence"][1]["sha256"][0] != "0" else "1")
        + m[6]["evidence"][1]["sha256"][1:]))
    mutant("evidence-file-missing", lambda m: None,
           lambda case: (case / "ev" / "s3_stop-0.png").unlink())
    mutant("non-pass-status", lambda m: m[1].__setitem__("status", "fail"))
    mutant("arbitrary-status", lambda m: m[4].__setitem__("status", "completed"))
    mutant("placeholder-field", lambda m: m[0].__setitem__("task_id", "TODO"))
    mutant("placeholder-hash", lambda m: [r.__setitem__("site_map_sha256", "0" * 64) for r in m])
    mutant("unknown-stage", lambda m: m[3].__setitem__("stage", "cell_claims"))
    mutant("wrong-schema", lambda m: m[2].__setitem__("schema", "rosy.factory-flow.receipt.v2"))
    mutant("unknown-field", lambda m: m[0].__setitem__("notes", "hi"))
    mutant("duplicate-evidence-path", lambda m: m[6]["evidence"].append(dict(m[6]["evidence"][0])))
    check("not-an-array", {"receipts": copy.deepcopy(receipts)})

    print(f"fixtures: {base}")
    if failures:
        print(f"SELF-CHECK FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("SELF-CHECK OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strict gate for rosy.factory-flow.receipt.v1 run receipt files.")
    parser.add_argument("receipts", nargs="?", help="receipt file (JSON array)")
    parser.add_argument("--self-check", action="store_true",
                        help="build demo fixtures in a scratch dir and verify every rejection class")
    parser.add_argument("--scratch", help="parent dir for --self-check fixtures (default: system temp)")
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check(args.scratch)
    if not args.receipts:
        parser.error("receipts file required (or --self-check)")
    errors, summary = verify(Path(args.receipts))
    if errors:
        for error in errors:
            print(f"REJECT {summary['path']}: {error}", file=sys.stderr)
        print(f"REJECTED: {len(errors)} problem(s)", file=sys.stderr)
        return 1
    print_report(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
