"""Competing values for one cell, each with where it came from and how it did for real (D-872).

A taught value (a leader demonstration, a taught reference), a measured one (what the arm or a camera
showed) and a simulated one are candidates side by side; none wins by default. Each real try adds an
outcome, and the value used is the one that has done best for that purpose, with the others kept as
fallbacks. Names carry the purpose: the taught top reference belongs to the taught replay, the
measured start pixel to the top-down plan (2026-10-25: both right, each for its own plan).

  rosy.omx-cell-choices.v1: {"schema", "values": {"<name>": [{"value", "source", "ok", "tries", "last"}]}}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "rosy.omx-cell-choices.v1"


class Choices:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"schema": SCHEMA, "values": {}}
        if self.data.get("schema") != SCHEMA:
            raise SystemExit(f"{path}: not a {SCHEMA} file")

    def _find(self, name, value):
        return next((c for c in self.data["values"].get(name, []) if c["value"] == value), None)

    def offer(self, name: str, value, source: str):
        """Add a candidate once; offering it again keeps its record."""
        if self._find(name, value) is None:
            self.data["values"].setdefault(name, []).append(
                {"value": value, "source": source, "ok": 0, "tries": 0, "last": None})

    def outcome(self, name: str, value, ok: bool, note: str | None = None):
        candidate = self._find(name, value)
        if candidate is None:
            raise KeyError(f"{name}: {value!r} was never offered")
        candidate["tries"] += 1
        candidate["ok"] += bool(ok)
        candidate["last"] = {"ok": bool(ok), "note": note, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def best(self, name: str, default=None):
        """The candidate with the best record: (ok + 1) / (tries + 2), so one success beats an untried value
        and an untried value beats one failure; ties go to the one tried more."""
        candidates = self.data["values"].get(name, [])
        if not candidates:
            return default
        return max(candidates, key=lambda c: ((c["ok"] + 1) / (c["tries"] + 2), c["tries"]))["value"]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)
