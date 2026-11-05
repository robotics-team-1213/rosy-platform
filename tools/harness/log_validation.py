"""Validate scanned log entries without weakening historical record preservation."""

import datetime as dt
import re
from hashlib import sha256

LOG_FIELDS = ("변경", "증거", "gate 변화")
LOG_FIELD_ALIASES = {
    "변경": ("Change",),
    "증거": ("근거", "검증", "정적 확인", "장치 근거", "Evidence", "Local evidence"),
    "gate 변화": ("Gate", "gate", "gate 보류"),
}

# Both immutable docs/logs.md versions survive the ordinary 5fa2afae0f merge.
# The scanner normalizes the document; hash body.strip() as UTF-8, retaining body BOMs.
CONCURRENT_HEADING = (
    "## 2026-11-04 · uncommitted · feat(accounts): "
    "계정 화면의 역할 선택이 권한 묶음을 채움 (D-955 화면 보완)"
)
CONCURRENT_BODIES = frozenset({
    # 0f98efc00cfc39bdc3e3758c74231288e0785e42:docs/logs.md
    "b21a721f83d1926f3f99ea25e90683124df9755db7145d5266490132bf99437f",
    # 5501425d1dd9b9771b28dec0ec858b91d17167b5:docs/logs.md
    "55176e616c6882b6de3d2a85daaad8bfce88e043ee96af34e583bc31466fb0af",
})


def validate_entries(entries, errors: list[str], legacy_headings: frozenset[str]) -> list[str]:
    concurrent = [entry for entry in entries if entry.heading == CONCURRENT_HEADING]
    pinned_pair = len(concurrent) == 2 and {
        sha256(entry.body.strip().encode("utf-8")).hexdigest()
        for entry in concurrent
    } == CONCURRENT_BODIES
    seen: set[str] = set()
    previous: str | None = None
    for entry in entries:
        try:
            dt.date.fromisoformat(entry.date)
        except ValueError:
            errors.append(f"{entry.heading}: invalid date")
        if entry.heading in seen and not (entry.heading == CONCURRENT_HEADING and pinned_pair):
            errors.append(f"duplicate entry: {entry.heading}")
        seen.add(entry.heading)
        for name in LOG_FIELDS:
            if entry.heading in legacy_headings:
                # Preserve the existing legacy-field exemption independently of body pins.
                continue
            accepted_names = (name, *LOG_FIELD_ALIASES.get(name, ()))
            if not any(
                re.search(rf"^- {re.escape(accepted)}:", entry.body, flags=re.MULTILINE)
                for accepted in accepted_names
            ):
                errors.append(f"{entry.heading}: missing '- {name}:'")
        if previous is not None and entry.date < previous:
            errors.append(f"{entry.heading}: out of order (after {previous})")
        previous = max(previous or entry.date, entry.date)
    return errors
