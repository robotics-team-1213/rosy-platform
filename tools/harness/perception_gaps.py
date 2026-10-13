"""Perception blind-spot registry: validate rows and render the table.

Wired into ``rosy_harness.py lint`` / ``generate`` through ``harness.yaml`` keys
``perception_gaps`` and ``perception_table``. Tests: ``test/test_perception_gaps.py``.
Malformed input is reported as errors, never raised.

One row is one blind spot. It is born from a recording id, a dated device read,
or an in-repo note, and a CLOSED row must name a replay that exists in the
repo. D-578 sends non-label causes to this list. This module does not train a
model and does not switch sensors.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import sim2real

SCHEMA = "rosy.perception-gaps.v1"
REQUIRED = ("id", "kind", "spot", "born", "evidence", "replay", "owner", "status", "next")
KINDS = ("miss", "candidate")
STATUSES = ("OPEN", "IN-PROGRESS", "CLOSED", "HOLD")
CANDIDATE_STATUSES = ("HOLD", "CLOSED")
SPOT_ID = re.compile(r"^P-\d{2}$")
RECORDING = re.compile(r"^\d{8}T\d{6}Z$")
DEVICE_READ = re.compile(r"^device:(\d{4}-\d{2}-\d{2})$")
UNBUILT = "unbuilt"

load = sim2real.load
read = sim2real.read


def _device_date(token: str) -> bool:
    match = DEVICE_READ.match(token)
    if match is None:
        return False
    try:
        dt.date.fromisoformat(match.group(1))
    except ValueError:
        return False
    return True


def _born_errors(where: str, born, repo: Path) -> list[str]:
    if not isinstance(born, str):
        return [f"{where}: born must be a recording id, device:YYYY-MM-DD, or an in-repo .md path"]
    if RECORDING.match(born) or _device_date(born):
        return []
    if born.endswith(".md") and sim2real._inside_repo(born) and (repo / born).is_file():
        return []
    if born.endswith(".md") and sim2real._inside_repo(born):
        return [f"{where}: born note not found: {born}"]
    return [f"{where}: born must be a recording id, device:YYYY-MM-DD, or an in-repo .md path"]


def _replay_errors(where: str, replay, status, repo: Path) -> list[str]:
    if not isinstance(replay, str):
        return [f"{where}: replay must be a repo path or {UNBUILT!r}"]
    if replay == UNBUILT:
        if status == "CLOSED":
            return [f"{where}: CLOSED replay cannot be {UNBUILT}"]
        return []
    if ":" in replay or not sim2real._inside_repo(replay):
        return [f"{where}: replay outside the repository: {replay}"]
    if not (repo / replay).is_file():
        return [f"{where}: replay not found: {replay}"]
    return []


def validate(registry, repo: Path, known_adrs: set[str]) -> tuple[list[str], list[str]]:
    if not isinstance(registry, dict):
        return ["registry must be a mapping with a spots list"], []
    errors: list[str] = []
    warnings: list[str] = []
    schema = registry.get("schema")
    if schema is not None and schema != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    rows = registry.get("spots")
    if not isinstance(rows, list):
        return errors + ["spots must be a list"], []
    seen: set[str] = set()
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"row {number}: must be a mapping")
            continue
        spot_id = row.get("id")
        valid_id = isinstance(spot_id, str) and bool(SPOT_ID.match(spot_id))
        where = spot_id if valid_id else f"row {number}"
        errors += [f"{where}: missing field: {key}" for key in REQUIRED if row.get(key) in (None, "", [])]
        if spot_id is not None and not valid_id:
            errors.append(f"{where}: malformed id {spot_id!r} (want P-NN)")
        elif valid_id and spot_id in seen:
            errors.append(f"{where}: duplicate id")
        elif valid_id:
            seen.add(spot_id)
        kind = row.get("kind")
        if kind is not None and kind not in KINDS:
            errors.append(f"{where}: unknown kind {kind!r}")
        status = row.get("status")
        if status is not None and (not isinstance(status, str) or status not in STATUSES):
            errors.append(f"{where}: unknown status {status!r}")
        elif kind == "candidate" and status not in CANDIDATE_STATUSES:
            errors.append(f"{where}: candidate status must be HOLD or CLOSED")
        if row.get("born") not in (None, "", []):
            errors += _born_errors(where, row.get("born"), repo)
        if row.get("replay") not in (None, "", []):
            errors += _replay_errors(where, row.get("replay"), status, repo)
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
            item_errors, item_warnings = sim2real._check_evidence(repo, label, item, known_adrs, strict)
            errors += item_errors
            warnings += item_warnings
    return errors, warnings


def _replay_text(replay) -> str:
    return UNBUILT if replay == UNBUILT else f"`{replay}`"


def render(registry) -> str:
    """The table. Total on any input: lint reports shape errors, this only renders."""
    lines = [
        "<!-- GENERATED by tools/harness/rosy_harness.py generate. "
        "Edit tools/harness/perception_gaps.yaml instead. -->",
        "# perception blind spots",
        "",
        "한 행은 인식 맹점 하나다. `born`은 녹음 id, `device:YYYY-MM-DD` 장치 읽기, "
        "또는 저장소 안 기록이다. `replay`가 `unbuilt`인 행은 CLOSED가 될 수 없다. "
        "candidate는 HOLD 또는 CLOSED만 된다. 규칙은 `rosy_harness.py lint`가 정한다. "
        "D-578이 라벨 후보가 아닌 원인을 보내는 목록이 여기다. sim2real 목록(D-480)과는 별개다.",
        "",
        "| id | kind | spot | born | evidence | replay | owner | status | next |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    rows = registry.get("spots") if isinstance(registry, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        evidence = row.get("evidence") or []
        evidence = evidence if isinstance(evidence, list) else [evidence]
        status = row.get("status")
        if row.get("validated_by"):
            status = f"{status} ({sim2real._evidence_text(row['validated_by'])})"
        lines.append("| " + " | ".join([
            sim2real._cell(row.get("id")), sim2real._cell(row.get("kind")), sim2real._cell(row.get("spot")),
            sim2real._cell(row.get("born")),
            "<br>".join(sim2real._cell(sim2real._evidence_text(item)) for item in evidence),
            sim2real._cell(_replay_text(row.get("replay"))), sim2real._cell(row.get("owner")),
            sim2real._cell(status), sim2real._cell(row.get("next")),
        ]) + " |")
    return "\n".join(lines) + "\n"
