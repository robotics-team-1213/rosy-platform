"""The arm's object catalogue with measured masses, read only for the Cell page (D-934, D-935, 2026-10-30).

Fleet and the arm's field files share the Fleet PC, so the catalogue is a file named by ROSY_CELL_OBJECT_CATALOG
rather than an upload with its own credential. Nothing here writes. An object without a measured mass is shown as
blocked: the D-911 gate refuses an unknown payload (D-935).
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "rosy.omx-object-catalog.v1"
ENV = "ROSY_CELL_OBJECT_CATALOG"
FIELDS = ("id", "kind", "length_mm", "width_mm", "top_height_mm")


def _mass(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def view(path) -> dict:
    """{"objects": [...]} for the page; ValueError on a file that is not the catalogue."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("objects"), list):
        raise ValueError(f"not a {SCHEMA} file")
    out = []
    for o in data["objects"]:
        if not isinstance(o, dict) or not isinstance(o.get("id"), str) or not o["id"]:
            raise ValueError("a catalogue entry has no id")
        measured, known = o.get("mass_measured"), _mass(o.get("mass_kg"))
        out.append({**{key: o.get(key) for key in FIELDS},
                    "mass_kg": o["mass_kg"] if known else None,
                    "mass_measured": ({key: measured.get(key) for key in ("at", "source", "reading")}
                                      if known and isinstance(measured, dict) else None),
                    "max_gross_kg": o["max_gross_kg"] if _mass(o.get("max_gross_kg")) else None,
                    "carry": ("ok: the gate checks it against the reviewed bound" if known
                              else "blocked: no measured mass (D-935)")})
    return {"objects": out}
