"""Canonical 37-site coordinate resolution, calibration/arm guards, and zone ROI helpers for OMX Cell."""
from __future__ import annotations

import functools
import json
import re
import hashlib
from pathlib import Path
from typing import Any

STACKING_AREAS = frozenset({"pallet", "yard", "temp_a", "temp_b"})
STAND_ALIASES = frozenset({"stand", "stand:r1-s1", "stand:r1-s1-t1", "stand-r1-c1-l1", "stand-1"})


@functools.lru_cache(maxsize=2)
def _index(map_path_str: str) -> dict[str, Any]:
    doc = json.loads(Path(map_path_str).read_text(encoding="utf-8"))
    by_tier_id: dict[str, dict[str, Any]] = {}
    by_sim: dict[str, dict[str, Any]] = {}
    by_wire: dict[str, dict[str, Any]] = {}
    slots_by_id: dict[str, dict[str, Any]] = {}
    for zone in doc["zones"]:
        area = zone["id"]
        for slot in zone["slots"]:
            slot_id = slot["id"]
            arms = tuple(slot["arms"])
            col = int(slot["row"])
            zone_row = int(slot["slot"])
            slot_rec = {"slot_id": slot_id, "area": area, "col": col, "row": zone_row, "arms": arms, "tiers": {}}
            for tier_entry in slot["tiers"]:
                tier = int(tier_entry["tier"])
                sim_site = tier_entry["item"]
                rec = {
                    "site_id": tier_entry["id"], "slot_id": slot_id, "sim_site": sim_site,
                    "base_site": sim_site.rsplit("-l", 1)[0],
                    "wire_ref": f"{area}-r{slot['row']}-c{slot['columns'][0]}-l{tier}",
                    "area": area, "col": col, "row": zone_row, "tier": tier, "arms": arms,
                    "is_legacy_pallet": False,
                }
                by_tier_id[rec["site_id"]] = rec
                by_sim[sim_site] = rec
                by_wire[rec["wire_ref"]] = rec
                slot_rec["tiers"][tier] = rec
            slots_by_id[slot_id] = slot_rec
    for sim_name, mapped in (doc.get("aliases") or {}).get("legacy_sim", {}).items():
        if isinstance(mapped, str) and mapped in by_tier_id and sim_name not in by_sim:
            by_sim[sim_name] = by_tier_id[mapped]
    layout_aliases = {
        k: v for k, v in (doc.get("aliases") or {}).get("legacy_layout", {}).items()
        if isinstance(v, str) and v in slots_by_id
    }
    return {
        "by_tier_id": by_tier_id, "by_sim": by_sim, "by_wire": by_wire,
        "slots_by_id": slots_by_id, "layout_aliases": layout_aliases,
    }


def _load_index() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "shared/web/cell-site-map.json"
    return _index(str(path.resolve()))


def resolve_cell_ab_site(
    raw_site: Any, tier: Any = None, *, allow_belt_temp: bool = True, allow_pallet_src: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(raw_site, str):
        return None
    s = raw_site
    idx = _load_index()
    tier_ok = type(tier) is int and tier in (1, 2, 3)

    if s in ("pallet", "pallet-l0", "pallet-l1", "pallet-l2"):
        enc = None if s == "pallet" else int(s[-1]) + 1
        eff_tier = enc if enc is not None else (tier if tier_ok else (1 if allow_pallet_src and s == "pallet" else None))
        if eff_tier is None or (enc is not None and tier_ok and tier != enc):
            return None
        return {
            "site_id": None, "slot_id": None, "sim_site": "pallet" if allow_pallet_src and s == "pallet" else f"pallet-l{eff_tier - 1}",
            "base_site": "pallet", "area": "pallet", "col": None, "row": None,
            "tier": eff_tier, "arms": ("arm_a", "arm_b"), "is_legacy_pallet": True,
        }
    if allow_belt_temp and s in ("belt", "temp_plate_a", "temp_plate_b"):
        arms = ("arm_a",) if s == "temp_plate_a" else ("arm_b",) if s == "temp_plate_b" else ("arm_a", "arm_b")
        return {
            "site_id": None, "slot_id": None, "sim_site": s, "base_site": s,
            "area": s, "col": None, "row": None, "tier": tier if tier_ok else 1,
            "arms": arms, "is_legacy_pallet": True,
        }
    rec = idx["by_tier_id"].get(s) or idx["by_wire"].get(s) or idx["by_sim"].get(s)
    if rec is not None:
        if tier is not None and tier != rec["tier"]:
            return None
        return dict(rec)
    slot_id = idx["layout_aliases"].get(s, s)
    slot_rec = idx["slots_by_id"].get(slot_id)
    if slot_rec is not None:
        if not tier_ok or tier not in slot_rec["tiers"]:
            return None
        return dict(slot_rec["tiers"][tier])
    return None


def is_canonical_37site(raw_site: Any) -> bool:
    if not isinstance(raw_site, str):
        return False
    idx = _load_index()
    s = raw_site.strip()
    return (
        s in idx["by_tier_id"] or s in idx["by_wire"] or s in idx["by_sim"]
        or idx["layout_aliases"].get(s, s) in idx["slots_by_id"]
    )


def default_arm_for_cell_ab(src_site: Any, dst_site: Any, tier: Any = None) -> str:
    d_raw, s_raw = str(dst_site or "").strip(), str(src_site or "").strip()
    dst = resolve_cell_ab_site(d_raw, tier) or (resolve_cell_ab_site(d_raw, 1) if tier is None else None)
    src = resolve_cell_ab_site(s_raw, None, allow_pallet_src=True) or resolve_cell_ab_site(s_raw, 1)
    arms = dst["arms"] if dst else ("arm_a", "arm_b")
    if src is not None:
        both = tuple(a for a in arms if a in src["arms"])
        if both:
            arms = both
    if len(arms) == 1:
        return arms[0]
    if type(tier) is int and tier in (1, 2, 3):
        return "arm_a" if tier % 2 == 1 else "arm_b"
    return "arm_b"


def validate_cell_ab_handoff(src: str, dst: str, tier: Any, arm_id: str = "") -> str | None:
    if type(tier) is not int or tier not in (1, 2, 3):
        return "UNKNOWN_SITE"
    if not isinstance(src, str) or not isinstance(dst, str) or src != src.strip() or dst != dst.strip():
        return "UNKNOWN_SITE"
    if dst in ("belt", "pinky", "temp_plate_a", "temp_plate_b") or src == "pinky":
        return "UNKNOWN_SITE"
    d = resolve_cell_ab_site(dst, tier, allow_belt_temp=False)
    s = resolve_cell_ab_site(src, None, allow_belt_temp=True, allow_pallet_src=True)
    if d is None or s is None:
        return "UNKNOWN_SITE"
    if d["site_id"] is not None and s["site_id"] == d["site_id"]:
        return "UNKNOWN_SITE"
    if not (set(d["arms"]) & set(s["arms"])):
        return "UNKNOWN_SITE"
    if arm_id and (arm_id not in d["arms"] or arm_id not in s["arms"]):
        return "UNKNOWN_SITE"
    if dst in ("pallet", "pallet-l0", "pallet-l1", "pallet-l2") and src != "belt":
        return "UNKNOWN_SITE"
    return None


def arm_refusal(src: str, dst: str, arm_id: str) -> str | None:
    d = resolve_cell_ab_site(dst, None, allow_belt_temp=True) or resolve_cell_ab_site(dst, 1, allow_belt_temp=True)
    s = resolve_cell_ab_site(src, None, allow_belt_temp=True, allow_pallet_src=True) or resolve_cell_ab_site(src, 1, allow_belt_temp=True)
    if (d and d["area"] == "stand") or (s and s["area"] == "stand") or dst in STAND_ALIASES or src in STAND_ALIASES:
        if arm_id != "arm_a":
            return "STAND_REQUIRES_ARM_A"
    if d and (not d["is_legacy_pallet"] or d["area"] in ("temp_plate_a", "temp_plate_b")) and arm_id not in d["arms"]:
        return "SITE_ARM_NOT_ALLOWED"
    if s and (not s["is_legacy_pallet"] or s["area"] in ("temp_plate_a", "temp_plate_b")) and arm_id not in s["arms"]:
        return "SITE_ARM_NOT_ALLOWED"
    return None


def _has_place_surface(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("place"), (list, tuple))
        and len(entry["place"]) == 2
        and "surface_z" in entry
    )


REGISTER_KEYS = ("status", "provenance", "history", "measured_xy", "measured_z")  # cell_site_register's; tier copies must not carry them
LEGACY_NAMES = frozenset({"pallet", "belt", "beltend", "temp_plate_a", "temp_plate_b", "stand", "plate_b", "strip_b", "col1", "stack", "pinky"})


def _unmeasured(entry: Any) -> bool:
    """A site written by cell_site_register stays refused until XY and Z are both measured; entries without status are legacy."""
    return isinstance(entry, dict) and "status" in entry and entry["status"] != "measured"


def unmeasured_refusal(sites: dict[str, Any], *names: Any) -> str | None:
    """The one shared answer for every motion path: SITE_NOT_MEASURED if a named site (or the base of a -lN tier copy) is not measured."""
    for name in names:
        entry = sites.get(name) if isinstance(name, str) else None
        if _unmeasured(entry) or (isinstance(entry, dict) and _unmeasured(sites.get(entry.get("tier_of")))):
            return "SITE_NOT_MEASURED"
    return None


def designated_slot_arms(name: Any) -> tuple[str, ...]:
    """Arms of a designated slot base name from cell-site-map (ship-h1r0, tmp-a-1 ...); () for anything else, legacy names included."""
    if not isinstance(name, str) or name in LEGACY_NAMES:
        return ()
    arms = {a for rec in _load_index()["by_sim"].values() if rec["base_site"] == name and not rec["is_legacy_pallet"] and rec["area"] != "stand" for a in rec["arms"]}
    return tuple(sorted(arms))


def site_digest(entry: dict[str, Any]) -> str:
    """Short digest of what a measurement is about: place, yaw and surface height."""
    try:
        key = [[round(float(v), 6) for v in entry["place"]], round(float(entry.get("yaw_deg", 0.0)), 6), round(float(entry["surface_z"]), 6)]
    except (KeyError, TypeError, ValueError):
        return "invalid"
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]


def calibration_refusal(cfg_sites: dict[str, Any], src: str, dst: str, tier: Any) -> str | None:
    if dst in ("temp_plate_a", "temp_plate_b") and not _has_place_surface(cfg_sites.get(dst)):
        return "SITE_NOT_CALIBRATED"
    d = resolve_cell_ab_site(dst, tier, allow_belt_temp=False)
    if d is None and (is_canonical_37site(dst) or dst in STAND_ALIASES):
        return "STAND_NOT_CALIBRATED" if dst in STAND_ALIASES or dst.startswith("stand:") else "SITE_NOT_CALIBRATED"
    if d is not None and not d["is_legacy_pallet"]:
        d_ok = _has_place_surface(cfg_sites.get(d["sim_site"])) or _has_place_surface(cfg_sites.get(d["base_site"]))
        if not d_ok:
            return "STAND_NOT_CALIBRATED" if d["area"] == "stand" else "SITE_NOT_CALIBRATED"
        if unmeasured_refusal(cfg_sites, d["sim_site"], d["base_site"]):
            return "SITE_NOT_MEASURED"
    s = resolve_cell_ab_site(src, None, allow_belt_temp=True, allow_pallet_src=True)
    if s is None and (is_canonical_37site(src) or src in STAND_ALIASES):
        return "STAND_NOT_CALIBRATED" if src in STAND_ALIASES or src.startswith("stand:") else "SITE_NOT_CALIBRATED"
    if s is not None and (not s["is_legacy_pallet"] or s["area"] in ("temp_plate_a", "temp_plate_b")):
        exact, base = cfg_sites.get(s["sim_site"]), cfg_sites.get(s["base_site"])
        s_ok = isinstance(exact, dict) or (isinstance(base, dict) and "surface_z" in base)
        if not s_ok:
            return "STAND_NOT_CALIBRATED" if s["area"] == "stand" else "SITE_NOT_CALIBRATED"
        if unmeasured_refusal(cfg_sites, s["sim_site"] if isinstance(exact, dict) else s["base_site"]):
            return "SITE_NOT_MEASURED"
    return None


def top_slot_roi(zone_rois: dict[str, Any] | None, place: dict[str, Any]) -> tuple[int, int, int, int] | None:
    top_tbl = (zone_rois or {}).get("top") or {}
    area = str(place.get("area") or place.get("area_id") or "").strip().lower()
    if area in ("stand", "stand:r1-s1", "stand:r1-s1-t1"):
        roi = top_tbl.get("stand")
        return tuple(int(v) for v in roi) if roi else None
    base = str(place.get("base_site") or "").strip()
    if base and base in top_tbl:
        return tuple(int(v) for v in top_tbl[base])
    if area in ("temp_a", "temp_b") or area.startswith(("temp_plate", "tmp-")):
        return None
    col, row = place.get("col"), place.get("row")
    roi = top_tbl.get(f"c{col}r{row}") if (col is not None and row is not None) else None
    return tuple(int(v) for v in roi) if roi else None


def temp_to_ship(source, dest):
    src, dst = (resolve_cell_ab_site(site, allow_belt_temp=False) for site in (source, dest))
    return bool(src and dst and src["area"] in ("temp_a", "temp_b") and src["tier"] == 2
                and dst["base_site"].startswith("ship-") and dst["tier"] == 1)


def source_transition_matches(zone, src, dst):
    if not temp_to_ship(src, dst):
        return True

    def record(row, key):
        value = row.get(key) if isinstance(row, dict) else None
        return value if isinstance(value, dict) else {}

    transition = record(zone, "source_transition")
    before = record(transition, "before")
    binding = record(before, "binding")
    prior, after = record(before, "source"), record(transition, "after")
    pre, post = record(before, "receipt"), record(transition, "after_receipt")
    hashes = [rec.get("depth_sha256") for rec in (pre, post)]
    times = [pre.get("last_stamp"), post.get("first_stamp")]
    return (all(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)
            and hashes[0] != hashes[1] and all(type(t) in (int, float) for t in times) and 0 < times[0] < times[1]
            and record(binding, "source").get("site") == resolve_cell_ab_site(src)["sim_site"]
            and record(binding, "destination").get("site") == resolve_cell_ab_site(dst)["sim_site"]
            and prior.get("tier_ok") is True and prior.get("tier") == 2
            and after.get("tier_ok") is True and type(after.get("tier")) is int and after["tier"] == 1)


def cell_ab_place_verified(
    handoff: dict[str, Any], place: dict[str, Any], z_gate: dict[str, Any], tier: int,
    verification: dict[str, Any] | None = None,
) -> bool:
    dst_raw = str(handoff.get("dst_site") or "").strip()
    resolved = resolve_cell_ab_site(dst_raw, tier, allow_belt_temp=False)
    if not source_transition_matches(verification, handoff.get("src_site"), resolved["sim_site"] if resolved else dst_raw):
        return False
    dst_area = str(handoff.get("dst_area") or (resolved["area"] if resolved else "pallet")).lower()
    place_area = str(place.get("area") or place.get("area_id") or "").strip().lower()
    tier_ok = type(place.get("tier")) is int and place["tier"] == tier
    canon = resolved if (resolved and not resolved["is_legacy_pallet"]) else None
    dst_id = handoff.get("dst_site_id") or (canon["site_id"] if canon else None)
    slot = handoff.get("dst_slot") if isinstance(handoff.get("dst_slot"), dict) else (
        {"col": canon["col"], "row": canon["row"]} if canon else None)
    if dst_area == "stand":
        ok = (tier == 1 and handoff.get("arm_id") == "arm_a" and place_area == "stand" and tier_ok
              and place.get("site") in ("stand", "stand:r1-s1", "stand:r1-s1-t1"))
    else:
        if dst_area not in STACKING_AREAS or z_gate.get("verdict") != "PASS" or place_area != dst_area or not tier_ok:
            return False
        ok = not dst_id or place.get("site") in (resolved["sim_site"] if resolved else dst_raw, dst_id)
    if not ok:
        return False
    if dst_id and place.get("site_id") != dst_id:
        return False
    if slot and (place.get("col") != slot.get("col") or place.get("row") != slot.get("row")):
        return False
    if dst_id and verification is not None:
        vt = verification.get("target")
        if not isinstance(vt, dict) or vt.get("site_id") != dst_id or vt.get("tier") != tier:
            return False
        if str(vt.get("area") or "").strip().lower() != dst_area:
            return False
        if slot and (vt.get("col") != slot.get("col") or vt.get("row") != slot.get("row")):
            return False
    return True
