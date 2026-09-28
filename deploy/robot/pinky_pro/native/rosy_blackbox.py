"""L1 black box on the FAT32 boot partition (D-175).

A person holding only the card can read why the robot failed: insert it into
any PC and open ``rosy-diag/latest.txt``. One report per boot, rewritten only
when the stage changes, at most five boots and 2 MiB in total. Everything is
redacted first because anyone holding the card can read this partition.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time

from rosy_diag_redact import redact


DIRECTORY = "rosy-diag"
KEEP_BOOTS = 5
TAIL_LINES = 60
TOTAL_CAP_BYTES = 2 * 1024 * 1024
REPORT_CAP_BYTES = TOTAL_CAP_BYTES // (KEEP_BOOTS + 1)
# A crash-looping unit alternates stages; rewrite the FAT32 partition at most this
# often unless the change is a new failure or a recovery to CORE_READY.
REWRITE_INTERVAL_S = 300


def _fsync_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    if hasattr(os, "O_DIRECTORY"):  # persist the rename itself (vfat loses it on power cut)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _number(path: Path) -> int:
    part = path.stem.split("-")[1] if path.stem.count("-") >= 2 else ""
    return int(part) if part.isdigit() else -1


def _reports(directory: Path) -> list[Path]:
    return sorted(directory.glob("boot-*.json"), key=lambda path: (_number(path), path.name))


def _existing_for_boot(directory: Path, boot_id: str) -> Path | None:
    for path in _reports(directory):
        if path.stem.endswith(boot_id[:8]):
            return path
    return None


def needs_write(boot_partition: Path, record: dict) -> bool:
    directory = boot_partition / DIRECTORY
    existing = _existing_for_boot(directory, record.get("boot_id") or "unknown")
    if existing is None:
        return True
    try:
        previous = json.loads(existing.read_text(encoding="utf-8")).get("stage")
        age = time.time() - existing.stat().st_mtime
    except (OSError, ValueError):
        return True
    stage = str(record["stage"])
    if previous == stage:
        return False
    new_failure = stage.startswith("FAILED") and not str(previous).startswith("FAILED")
    return new_failure or stage == "CORE_READY" or age >= REWRITE_INTERVAL_S


def _fit(tails: dict[str, list[str]], budget: int) -> dict[str, list[str]]:
    """Keep the newest lines of each tail until the report fits its budget."""
    fitted = {unit: [redact(line[:2000]) for line in lines[-TAIL_LINES:]] for unit, lines in tails.items()}
    while len(json.dumps(fitted)) > budget and any(fitted.values()):
        longest = max(fitted, key=lambda unit: len(fitted[unit]))
        fitted[longest] = fitted[longest][1:]
    return fitted


def render_text(report: dict) -> str:
    lines = [
        "ROSY boot black box (D-175 L1). Newest boot report; details in boot-*.json.",
        f"device:   {report.get('device_name') or 'unprovisioned'}",
        f"release:  {report.get('release_id') or '?'}",
        f"stage:    {report['stage']}",
        f"boot_id:  {report.get('boot_id') or '?'}",
        f"updated:  {report.get('updated_at')}",
        f"address:  {', '.join(report.get('ipv4') or []) or 'none'}",
    ]
    if report.get("detail"):
        lines.append(f"detail:   {report['detail']}")
    for unit, state in sorted((report.get("units") or {}).items()):
        lines.append(f"unit:     {unit} = {state}")
    for unit, tail in (report.get("journal_tail") or {}).items():
        lines.append("")
        lines.append(f"--- last {len(tail)} journal lines of {unit} ---")
        lines.extend(tail)
    return redact("\n".join(lines) + "\n")


def write(boot_partition: Path, record: dict, tails: dict[str, list[str]]) -> Path:
    directory = boot_partition / DIRECTORY
    directory.mkdir(exist_ok=True)
    boot_id = record.get("boot_id") or "unknown"
    report = {key: (redact(value) if isinstance(value, str) else value) for key, value in record.items()}
    report["journal_tail"] = _fit(tails, REPORT_CAP_BYTES - len(json.dumps(report)) - 1024)

    target = _existing_for_boot(directory, boot_id)
    if target is None:
        numbers = [_number(path) for path in _reports(directory) if _number(path) >= 0]
        target = directory / f"boot-{(max(numbers) + 1) if numbers else 1:06d}-{boot_id[:8]}.json"
    _fsync_write(target, json.dumps(report, indent=1, sort_keys=True) + "\n")
    _fsync_write(directory / "latest.txt", render_text(report))

    for stale in _reports(directory)[:-KEEP_BOOTS]:
        stale.unlink(missing_ok=True)
    return target
