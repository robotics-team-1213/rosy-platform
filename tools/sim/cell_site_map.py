"""Load and validate shared/web/cell-site-map.json (rosy.cell-site-map.v1), the cell's one list of places. Stdlib only.

Fleet's image holds only shared/web, so pass `path` there; the default is this checkout's file. Do not edit the JSON by hand: export_site_map.py makes it.
"""
import json
from pathlib import Path
import re

DEFAULT = Path(__file__).resolve().parents[2] / "shared/web/cell-site-map.json"
ID_RE = re.compile(r"^(yard|temp_a|temp_b|stand):r[1-3]-s[1-2](-t[1-3])?$")
TIERS = {"yard": 3, "temp_a": 3, "temp_b": 3, "stand": 1}
ARMS = {"yard": ["arm_a", "arm_b"], "temp_a": ["arm_a"], "temp_b": ["arm_b"], "stand": ["arm_a"]}
SLOTS = {"yard": 6, "temp_a": 3, "temp_b": 3, "stand": 1}


def validate(doc):
    """Raise ValueError on any broken rule; return the doc."""
    def need(ok, msg):
        if not ok:
            raise ValueError(msg)
    need(doc.get("schema") == "rosy.cell-site-map.v1", "schema")
    seen = set()
    for z in doc["zones"]:
        zid = z["id"]
        need(zid in TIERS and len(z["slots"]) == SLOTS[zid] and z["arms"] == ARMS[zid], f"zone {zid}: slots or arms")
        for s in z["slots"]:
            need(ID_RE.match(s["id"]) and "-t" not in s["id"] and s["id"].startswith(zid + ":"), f"slot id {s['id']}")
            need(s["arms"] and set(s["arms"]) <= set(ARMS[zid]), f"slot {s['id']}: arms")
            need([t["tier"] for t in s["tiers"]] == list(range(1, TIERS[zid] + 1)), f"slot {s['id']}: tiers")
            for t in s["tiers"]:
                need(ID_RE.match(t["id"]) and t["id"] == f"{s['id']}-t{t['tier']}" and t["id"] not in seen, f"tier id {t['id']}")
                seen.add(t["id"])
    places = {s["id"] for z in doc["zones"] for s in z["slots"]} | {f"not_places:{n['id']}" for n in doc["not_places"]}
    for group in doc["aliases"].values():
        for old, new in group.items():
            need(new is None or new in places or new in seen, f"alias {old} -> {new}")
    return doc


def load(path=None):
    return validate(json.loads(Path(path or DEFAULT).read_text(encoding="utf-8")))


def tier_places(doc):
    """tier id -> sim item name (None when the sim has no place)."""
    return {t["id"]: t["item"] for z in doc["zones"] for s in z["slots"] for t in s["tiers"]}
