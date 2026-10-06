"""D-480 sim2real gap registry: validate rows and render the table.

Wired into ``rosy_harness.py lint`` / ``generate`` through ``harness.yaml`` keys
``sim2real_gaps`` and ``sim2real_table``. Tests: ``test/test_sim2real_gaps.py``.
Malformed input is reported as errors, never raised.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

import yaml

ADR_ID = re.compile(r"^D-(\d+)$")
SIM2REAL_REQUIRED = ("id", "gap", "evidence", "tier", "owner", "status", "next")
SIM2REAL_TIERS = ("M", "R", "D", "infra")
SIM2REAL_STATUSES = ("OPEN", "IN-PROGRESS", "CLOSED", "HOLD")
GAP_ID = re.compile(r"^G-\d{2}$")
# A repo path with an optional line suffix: `a.py`, `a.py:33`, `a.py:26-33`, `a.py:33,108`.
EVIDENCE_PATH = re.compile(r"^(?P<path>[^:]+?)(?::(?P<lines>\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*))?$")


def git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                                encoding="utf-8", check=False)
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def load(path: Path) -> tuple[dict | None, str | None]:
    """(registry, None) or (None, error) for a missing file or a YAML syntax error."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}, None
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, f"cannot read {path.name}: {exc}".replace("\n", " ")


def read(path: Path) -> dict:
    """The registry for rendering; a read problem raises ValueError (check_generated reports it)."""
    registry, problem = load(path)
    if problem:
        raise ValueError(problem)
    return registry


# --- validation --------------------------------------------------------------


def _inside_repo(path: str) -> bool:
    pure = PurePosixPath(path.replace("\\", "/"))
    return not pure.is_absolute() and ".." not in pure.parts and not re.match(r"^[A-Za-z]:", path)


def _line_errors(where: str, rel: str, target: Path, lines: str) -> list[str]:
    errors = []
    count = target.read_text(encoding="utf-8", errors="replace").count("\n") + 1
    for span in lines.split(","):
        a, _, b = span.partition("-")
        first, last = int(a), int(b or a)
        if first < 1:
            errors.append(f"{where}: {rel} cites line {first}; lines start at 1")
        if first > last:
            errors.append(f"{where}: {rel} cites reversed range {span}")
        if max(first, last) > count:
            errors.append(f"{where}: {rel} has {count} lines, cites line {max(first, last)}")
    return errors


def _check_evidence(repo: Path, where: str, item, known_adrs: set[str],
                    strict: bool = False) -> tuple[list[str], list[str]]:
    """One evidence entry: an ADR id, a repo path (optional :lines), or {path, branch}.

    ``strict`` (validated_by): a branch that cannot be resolved is an error, not a warning.
    """
    if isinstance(item, dict):
        path, branch = item.get("path"), item.get("branch")
        if not isinstance(path, str) or not isinstance(branch, str):
            return [f"{where}: branch evidence needs string path and branch"], []
        if not _inside_repo(path):
            return [f"{where}: path outside the repository: {path}"], []
        for ref in (branch, f"origin/{branch}"):
            if git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
                if git(repo, "cat-file", "-e", f"{ref}:{path}") is None:
                    return [f"{where}: not found on {branch}: {path}"], []
                return [], []
        message = f"{where}: branch {branch} not available; {path} unchecked"
        # Evidence only warns: the branch landed (move the path) or this clone lacks it (CI).
        return ([message], []) if strict else ([], [message])
    if not isinstance(item, str):
        return [f"{where}: evidence must be a string or {{path, branch}}"], []
    if ADR_ID.match(item):
        return ([] if item in known_adrs else [f"{where}: unknown ADR: {item}"]), []
    match = EVIDENCE_PATH.match(item)
    if match is None:
        return [f"{where}: not an ADR id or repo path: {item}"], []
    rel, lines = match["path"], match["lines"]
    if not _inside_repo(rel):
        return [f"{where}: path outside the repository: {rel}"], []
    target = repo / rel
    if not target.exists():
        return [f"{where}: not found: {rel}"], []
    if lines:
        if not target.is_file():
            return [f"{where}: {rel} is not a file; line numbers need a file"], []
        return _line_errors(where, rel, target, lines), []
    return [], []


def _tier_ok(tier) -> bool:
    return (isinstance(tier, list) and bool(tier) and all(isinstance(t, str) for t in tier)
            and len(set(tier)) == len(tier) and all(t in SIM2REAL_TIERS for t in tier))


def validate(registry, repo: Path, known_adrs: set[str]) -> tuple[list[str], list[str]]:
    if not isinstance(registry, dict):
        return ["registry must be a mapping with a gaps list"], []
    rows = registry.get("gaps")
    if not isinstance(rows, list):
        return ["gaps must be a list"], []
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"row {number}: must be a mapping")
            continue
        gap_id = row.get("id")
        valid_id = isinstance(gap_id, str) and bool(GAP_ID.match(gap_id))
        where = gap_id if valid_id else f"row {number}"
        errors += [f"{where}: missing field: {key}" for key in SIM2REAL_REQUIRED if row.get(key) in (None, "", [])]
        if gap_id is not None and not valid_id:
            errors.append(f"{where}: malformed id {gap_id!r} (want G-NN)")
        elif valid_id and gap_id in seen:
            errors.append(f"{where}: duplicate id")
        elif valid_id:
            seen.add(gap_id)
        if row.get("tier") is not None and not _tier_ok(row["tier"]):
            errors.append(f"{where}: tier must be a non-empty list of distinct {'/'.join(SIM2REAL_TIERS)}")
        status = row.get("status")
        if status is not None and (not isinstance(status, str) or status not in SIM2REAL_STATUSES):
            errors.append(f"{where}: unknown status {status!r}")
        evidence = row.get("evidence")
        if evidence is not None and not isinstance(evidence, list):
            errors.append(f"{where}: evidence must be a list")
            evidence = []
        checks = [(f"{where} evidence", item, False) for item in evidence or []]
        if status == "CLOSED":
            if not row.get("validated_by"):
                errors.append(f"{where}: CLOSED requires validated_by")
            else:
                checks.append((f"{where} validated_by", row["validated_by"], True))
        for label, item, strict in checks:
            item_errors, item_warnings = _check_evidence(repo, label, item, known_adrs, strict)
            errors += item_errors
            warnings += item_warnings
    return errors, warnings


# --- rendering ---------------------------------------------------------------


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _evidence_text(item) -> str:
    if isinstance(item, dict):
        return f"`{item.get('path')}` (branch {item.get('branch')})"
    return str(item) if ADR_ID.match(str(item)) else f"`{item}`"


def render(registry) -> str:
    """The table. Total on any input: lint reports shape errors, this only renders."""
    lines = [
        "<!-- GENERATED by tools/harness/rosy_harness.py generate. "
        "Edit tools/harness/sim2real_gaps.yaml instead. -->",
        "# sim2real gap registry",
        "",
        "Tier: M 시뮬 모델링, R 실주행 재생, D 장치 런타임 지원, infra 실행 환경. "
        "첫 tier가 지금 자리이고 뒤 tier는 옮겨 갈 자리다. 규칙은 D-480 결정 7과 `rosy_harness.py lint`가 정한다.",
        "",
        "| id | gap | evidence | tier | owner | status | next |",
        "|---|---|---|---|---|---|---|",
    ]
    rows = registry.get("gaps") if isinstance(registry, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        evidence = row.get("evidence") or []
        evidence = evidence if isinstance(evidence, list) else [evidence]
        tier = row.get("tier") or []
        tier = "+".join(map(str, tier)) if isinstance(tier, list) else str(tier)
        status = row.get("status")
        if row.get("validated_by"):
            status = f"{status} ({_evidence_text(row['validated_by'])})"
        lines.append("| " + " | ".join([
            _cell(row.get("id")), _cell(row.get("gap")), "<br>".join(_cell(_evidence_text(e)) for e in evidence),
            _cell(tier), _cell(row.get("owner")), _cell(status), _cell(row.get("next")),
        ]) + " |")
    return "\n".join(lines) + "\n"
