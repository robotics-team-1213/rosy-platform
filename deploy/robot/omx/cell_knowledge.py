#!/usr/bin/env python3
"""What the arm S cell has learned, as data the decision model can read (rosy.omx-cell-knowledge.v1).

Entries: {"id", "topic", "statement" (one sentence), "status" verified|partial|unverified, "evidence"
(commit/test/log names, no hosts or serials), "date", "applies_when" [grasp, lift, map, approach, idle,
any, ...]}. Background for the judge seat only: it never changes what the measurement allows.
  python cell_knowledge.py cell-knowledge.example.json [next-step]   # validate, and show what that step selects
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCHEMA = "rosy.omx-cell-knowledge.v1"
TOPICS = ("arm", "camera", "map", "objects", "operations", "safety", "policy")
STATUS = ("verified", "partial", "unverified")
FIELDS = ("id", "topic", "statement", "status", "evidence", "date", "applies_when")
IMPLIES = {"grasp": ("approach",)}  # a next step also pulls the entries of the steps it contains


def validate(data: dict) -> list[dict]:
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("entries"), list):
        raise ValueError(f"not a {SCHEMA} file")
    seen = set()
    for i, e in enumerate(data["entries"]):
        where = f"entry {i}"
        if not isinstance(e, dict) or any(k not in e for k in FIELDS):
            raise ValueError(f"{where}: needs {FIELDS}")
        where = f"entry {e['id']!r}"
        if e["id"] in seen:
            raise ValueError(f"{where}: duplicate id")
        seen.add(e["id"])
        if e["topic"] not in TOPICS or e["status"] not in STATUS:
            raise ValueError(f"{where}: topic {TOPICS} / status {STATUS}")
        if not isinstance(e["statement"], str) or not e["statement"].strip():
            raise ValueError(f"{where}: empty statement")
        if not isinstance(e["evidence"], list) or not all(isinstance(x, str) for x in e["evidence"]):
            raise ValueError(f"{where}: evidence is a list of names")
        if not isinstance(e["applies_when"], list) or not e["applies_when"]:
            raise ValueError(f"{where}: applies_when is a non-empty list")
    return data["entries"]


def load(path) -> dict:
    """{"entries", "sha"}: the validated file and a digest of its bytes (rows say which knowledge they ran with)."""
    raw = Path(path).read_bytes()
    return {"entries": validate(json.loads(raw)), "sha": hashlib.sha256(raw).hexdigest()[:12]}


def select(knowledge, facts: dict, limit: int = 6, chars: int = 300) -> list[dict]:
    """Verified and partial entries that bear on this step (facts["next"], facts["applies"]), verified first."""
    if not knowledge:
        return []
    step = facts.get("next")
    wanted = {"any", step, *IMPLIES.get(step, ()), *facts.get("applies", ())}
    hits = [e for e in knowledge["entries"] if e["status"] != "unverified" and wanted & set(e["applies_when"])]
    hits.sort(key=lambda e: ("any" not in e["applies_when"], e["status"] != "verified"))  # standing rules first
    return [{**e, "statement": e["statement"][:chars]} for e in hits[:limit]]


if __name__ == "__main__":
    k = load(sys.argv[1])
    print(len(k["entries"]), "entries ok, sha", k["sha"])
    if len(sys.argv) > 2:
        for e in select(k, {"next": sys.argv[2]}):
            print(e["id"], e["status"], e["statement"])
