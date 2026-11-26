"""Canonical 37-site cell coordinate resolution, 1-3 tier expansion, and D-1057 completion checks for Fleet."""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from typing import Any

ARM_CELL = {"arm_s": "cell_s", "arm_a": "cell_ab", "arm_b": "cell_ab"}
_STACKING_AREAS = frozenset({"pallet", "yard", "temp_a", "temp_b"})
_LEGACY_CELL_AB_AREAS = frozenset({"pallet", "belt", "temp_plate_a", "temp_plate_b"})
_SIM_AREA_PREFIXES = ("ship-", "tmp-a-", "tmp-b-", "yard:", "temp_a:", "temp_b:", "stand:", "yard-", "temp_a-", "temp_b-", "stand-")


@functools.lru_cache(maxsize=4)
def _index_cached(map_path_str: str, mtime_ns: int, size: int) -> dict[str, Any]:
    doc = json.loads(Path(map_path_str).read_text(encoding="utf-8"))
    by_tier_id: dict[str, dict[str, Any]] = {}
    by_sim: dict[str, dict[str, Any]] = {}
    by_wire: dict[str, dict[str, Any]] = {}
    slots_by_id: dict[str, dict[str, Any]] = {}
    canonical_list: list[dict[str, Any]] = []

    for zone in doc["zones"]:
        area = zone["id"]
        for slot in zone["slots"]:
            slot_id = slot["id"]
            arms = tuple(slot["arms"])
            col = int(slot["row"])       # row 1..3 maps to cell camera column 1..3
            zone_row = int(slot["slot"]) # slot 1..2 maps to depth-check row 1..2
            max_tier = len(slot["tiers"])
            slot_rec = {
                "slot_id": slot_id, "area": area, "col": col, "row": zone_row,
                "arms": arms, "max_tier": max_tier, "tiers": {},
            }
            for tier_entry in slot["tiers"]:
                tier = int(tier_entry["tier"])
                site_id = tier_entry["id"]
                sim_site = tier_entry["item"]
                base_site = sim_site.rsplit("-l", 1)[0]
                wire_ref = f"{area}-r{slot['row']}-c{slot['columns'][0]}-l{tier}"
                rec = {
                    "site_id": site_id, "slot_id": slot_id, "sim_site": sim_site,
                    "base_site": base_site, "wire_ref": wire_ref, "area": area,
                    "row": int(slot["row"]), "slot": int(slot["slot"]),
                    "col": col, "zone_row": zone_row, "tier": tier, "arms": arms,
                    "status": slot.get("status", "planned_unverified"),
                    "is_legacy_pallet": False, "encoded_tier": tier,
                }
                by_tier_id[site_id] = rec
                by_sim[sim_site] = rec
                by_wire[wire_ref] = rec
                slot_rec["tiers"][tier] = rec
                canonical_list.append(rec)
            slots_by_id[slot_id] = slot_rec

    for sim_name, mapped in (doc.get("aliases") or {}).get("legacy_sim", {}).items():
        if isinstance(mapped, str) and mapped in by_tier_id and sim_name not in by_sim:
            by_sim[sim_name] = by_tier_id[mapped]

    layout_aliases = {
        k: v for k, v in (doc.get("aliases") or {}).get("legacy_layout", {}).items()
        if isinstance(v, str) and v in slots_by_id
    }
    return {
        "doc": doc, "by_tier_id": by_tier_id, "by_sim": by_sim, "by_wire": by_wire,
        "slots_by_id": slots_by_id, "layout_aliases": layout_aliases, "sites": canonical_list,
    }


def _index(map_path_str: str) -> dict[str, Any]:
    """Return cached canonical cell-site index, automatically reloading when file mtime or size changes."""
    try:
        st = os.stat(map_path_str)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = (0, 0)
    return _index_cached(map_path_str, sig[0], sig[1])


_index.cache_clear = _index_cached.cache_clear


def _map_path(web_common: Path | None = None) -> Path:
    if web_common is not None and (web_common / "cell-site-map.json").is_file():
        return web_common / "cell-site-map.json"
    return Path(__file__).resolve().parents[4] / "shared/web/cell-site-map.json"


def list_canonical_sites(web_common: Path | None = None, *, include_zone_layout: bool = False) -> dict[str, Any]:
    idx = _index(str(_map_path(web_common).resolve()))
    doc = idx["doc"]
    status = doc.get("status", "planned_unverified")
    return {
        "schema": doc["schema"],
        "revision": doc.get("revision", 1),
        "status": status,
        "tier_height_mm": doc.get("tier_height_mm"),
        "count": len(idx["sites"]),
        "zones": [
            {
                "id": z["id"],
                "label": z["label"],
                "role": z["role"],
                "grid": {
                    "rows": int(z["grid"]["rows"]),
                    "columns": int(z["grid"]["columns"]),
                    "tiers": int(z["grid"]["tiers"]),
                },
                "slot_cells": int(z["slot_cells"]),
                "arms": list(z.get("arms") or ()),
                "status": z.get("status", status),
                **(_zone_layout(z) if include_zone_layout else {}),
            }
            for z in doc["zones"]
        ],
        "sites": [
            {
                "site_id": s["site_id"], "slot_id": s["slot_id"], "sim_site": s["sim_site"],
                "base_site": s["base_site"], "wire_ref": s["wire_ref"], "area": s["area"],
                "row": s["row"], "slot": s["slot"], "col": s["col"], "zone_row": s["zone_row"],
                "tier": s["tier"], "arms": list(s["arms"]), "status": s["status"],
            }
            for s in idx["sites"]
        ],
        "not_places": list(doc.get("not_places") or []),
    }


def _zone_layout(zone: dict[str, Any]) -> dict[str, Any]:
    layout: dict[str, Any] = {"slots": [
        {
            "id": slot["id"], "label": slot.get("label", slot["id"]),
            "row": slot["row"], "slot": slot["slot"], "columns": list(slot["columns"]),
            "hold": slot.get("hold"), "arms": list(slot["arms"]),
            "tiers": [{"id": tier["id"], "tier": tier["tier"]} for tier in slot["tiers"]],
            "status": slot.get("status", "planned_unverified"),
        }
        for slot in zone["slots"]
    ]}
    boundary = zone.get("hold_boundary") or {}
    if columns := boundary.get("columns"):
        layout["hold_boundary"] = {"columns": list(columns)}
    return layout


def _check_tier_value(raw_tier: Any) -> int:
    if type(raw_tier) is not int or raw_tier not in (1, 2, 3):
        raise ValueError("INVALID_CELL_TASK_INPUT")
    return raw_tier


def resolve_cell_ab_site(
    raw_site: Any,
    *,
    tier: Any = None,
    has_tier: bool = False,
    web_common: Path | None = None,
    allow_legacy_passthrough: bool = False,
    allow_generic_pallet: bool = False,
    legacy_sites: tuple[str, ...] | frozenset[str] = (),
) -> dict[str, Any]:
    idx = _index(str(_map_path(web_common).resolve()))
    site_str = "" if raw_site is None else str(raw_site).strip()
    if has_tier:
        tier_val = _check_tier_value(tier)
    else:
        tier_val = None

    if not site_str or site_str == "pallet":
        if tier_val is None and not (allow_generic_pallet and site_str == "pallet"):
            raise ValueError("INVALID_CELL_TASK_INPUT")
        eff_tier = tier_val if tier_val is not None else 1
        return {
            "sim_site": "pallet" if (allow_generic_pallet and site_str == "pallet" and tier_val is None) else f"pallet-l{eff_tier - 1}",
            "site_id": None, "slot_id": None, "wire_ref": None,
            "base_site": "pallet", "area": "pallet", "col": None, "row": None,
            "tier": eff_tier, "arms": ("arm_a", "arm_b"), "is_legacy_pallet": True, "encoded_tier": None,
        }
    if site_str in ("pallet-l0", "pallet-l1", "pallet-l2"):
        enc = int(site_str[-1]) + 1
        if tier_val is not None and tier_val != enc:
            raise ValueError("INVALID_CELL_TASK_INPUT")
        return {
            "sim_site": site_str, "site_id": None, "slot_id": None, "wire_ref": None,
            "base_site": "pallet", "area": "pallet", "col": None, "row": None,
            "tier": enc, "arms": ("arm_a", "arm_b"), "is_legacy_pallet": True, "encoded_tier": enc,
        }
    if allow_legacy_passthrough and (site_str in _LEGACY_CELL_AB_AREAS or site_str in legacy_sites):
        arms = ("arm_a",) if site_str == "temp_plate_a" else ("arm_b",) if site_str == "temp_plate_b" else ("arm_a", "arm_b")
        resolved_t = tier_val if tier_val is not None else 1
        return {
            "sim_site": site_str, "site_id": None, "slot_id": None, "wire_ref": None, "base_site": site_str,
            "area": site_str, "col": None, "row": None, "tier": resolved_t, "arms": arms,
            "is_legacy_pallet": True, "encoded_tier": None,
        }

    rec = idx["by_tier_id"].get(site_str) or idx["by_wire"].get(site_str) or idx["by_sim"].get(site_str)
    if rec is not None:
        if tier_val is not None and tier_val != rec["tier"]:
            raise ValueError("INVALID_CELL_TASK_INPUT")
        return dict(rec)

    slot_id = idx["layout_aliases"].get(site_str, site_str)
    slot_rec = idx["slots_by_id"].get(slot_id)
    if slot_rec is not None:
        if tier_val is None or tier_val not in slot_rec["tiers"]:
            raise ValueError("INVALID_CELL_TASK_INPUT")
        return {**slot_rec["tiers"][tier_val], "encoded_tier": None}

    raise ValueError("UNKNOWN_CELL_SITE")


def resolve_cell_task_targets(
    cell_id: str, spec: dict[str, Any], *, web_common: Path | None = None,
    default_cell_s_src: str = "vehicle", legacy_sites: tuple[str, ...] | frozenset[str] = (),
) -> dict[str, Any]:
    raw_src = spec.get("src_site")
    raw_dst = spec.get("dst_site")
    if cell_id != "cell_ab":
        for val in (raw_src, raw_dst):
            text = "" if val is None else str(val).strip()
            if text and (text == "stand" or text.startswith(_SIM_AREA_PREFIXES)):
                raise ValueError("INVALID_CELL_SITE")
        tier = spec.get("tier", 1) if "tier" in spec else 1
        return {
            "arm_id": str(spec.get("arm_id") or "arm_s"),
            "src_site": str(raw_src or default_cell_s_src),
            "src_site_id": None,
            "dst_site": str(raw_dst or "belt"),
            "dst_site_id": None,
            "dst_wire_ref": None,
            "dst_area": str(raw_dst or "belt"),
            "dst_slot": None,
            "tier": tier,
        }

    has_tier = "tier" in spec
    dst = resolve_cell_ab_site(raw_dst, tier=spec.get("tier"), has_tier=has_tier,
                               web_common=web_common,
                               allow_legacy_passthrough=(raw_dst == "belt" or raw_dst in legacy_sites),
                               legacy_sites=legacy_sites)
    src = resolve_cell_ab_site(raw_src if raw_src is not None else "belt", tier=None, has_tier=False,
                               web_common=web_common, allow_legacy_passthrough=True, allow_generic_pallet=True,
                               legacy_sites=legacy_sites) if (raw_src is None or raw_src != "") else None
    if src is None:
        raise ValueError("UNKNOWN_CELL_SITE")
    if dst["site_id"] is not None and src["site_id"] == dst["site_id"]:
        raise ValueError("INVALID_CELL_SITE")

    allowed_arms = tuple(a for a in dst["arms"] if a in src["arms"])
    if not allowed_arms:
        raise ValueError("INVALID_CELL_SITE_ARM")
    req_arm = spec.get("arm_id")
    if req_arm is not None and req_arm != "":
        if str(req_arm) not in allowed_arms:
            raise ValueError("INVALID_CELL_SITE_ARM")
        arm_id = str(req_arm)
    elif len(allowed_arms) == 1:
        arm_id = allowed_arms[0]
    else:
        arm_id = "arm_a" if dst["tier"] % 2 == 1 else "arm_b"

    slot_info = {"col": dst["col"], "row": dst["zone_row"], "tier": dst["tier"]} if dst["col"] is not None else None
    return {
        "arm_id": arm_id,
        "src_site": src["sim_site"],
        "src_site_id": src["site_id"],
        "dst_site": dst["sim_site"],
        "dst_site_id": dst["site_id"],
        "dst_wire_ref": dst.get("wire_ref"),
        "dst_area": dst["area"],
        "dst_slot": slot_info,
        "tier": dst["tier"],
    }


def expand_multi_tier_specs(
    body: dict[str, Any], *, base_id: str, web_common: Path | None = None,
    legacy_sites: tuple[str, ...] | frozenset[str] = (),
) -> list[dict[str, Any]]:
    cell_id = str(body.get("cell_id") or "cell_s")
    if cell_id != "cell_ab" or "tier" in body or body.get("preset"):
        raise ValueError("INVALID_CELL_TASK_INPUT")
    tiers = body.get("tiers")
    if not isinstance(tiers, list) or not (1 <= len(tiers) <= 3):
        raise ValueError("INVALID_CELL_TASK_INPUT")
    if any(type(t) is not int or t not in (1, 2, 3) for t in tiers) or tiers != sorted(set(tiers)):
        raise ValueError("INVALID_CELL_TASK_INPUT")
    if len(tiers) > 1 and any(k in body for k in ("object_ref", "identity", "identity_observation_ref")):
        raise ValueError("INVALID_CELL_TASK_INPUT")

    raw_dst = body.get("dst_site")
    dst_text = "" if raw_dst is None else str(raw_dst).strip()
    if dst_text in ("belt", "temp_plate_a", "temp_plate_b") or dst_text in legacy_sites:
        raise ValueError("UNKNOWN_CELL_SITE")

    base_spec = {k: v for k, v in body.items() if k not in ("tiers", "task_id", "depends_on")}
    specs: list[dict[str, Any]] = []
    prev_id = body.get("depends_on")
    for tier_val in tiers:
        step_id = f"{base_id}-t{tier_val}"
        step_spec = {**base_spec, "task_id": step_id, "tier": tier_val, "depends_on": prev_id}
        resolve_cell_task_targets("cell_ab", step_spec, web_common=web_common, legacy_sites=legacy_sites)
        specs.append(step_spec)
        prev_id = step_id
    return specs


def cell_ab_completion_verified(
    task: dict[str, Any], place: dict[str, Any], z_gate: dict[str, Any], verification: dict[str, Any] | None = None,
) -> bool:
    dst_area = str(task.get("dst_area") or "").strip().lower()
    if not dst_area:
        dst_site = str(task.get("dst_site") or "").strip()
        dst_area = "stand" if dst_site in ("stand", "stand:r1-s1", "stand:r1-s1-t1") else "pallet"
    place_area = str(place.get("area") or place.get("area_id") or "").strip().lower()
    tier_ok = type(place.get("tier")) is int and place["tier"] == task.get("tier")
    dst_site_id = task.get("dst_site_id")
    slot = task.get("dst_slot")
    if dst_area == "stand":
        if not (task.get("tier") == 1 and task.get("arm_id") == "arm_a" and place_area == "stand"
                and tier_ok and place.get("site") in ("stand", "stand:r1-s1", "stand:r1-s1-t1")):
            return False
    else:
        if dst_area not in _STACKING_AREAS or z_gate.get("verdict") != "PASS" or place_area != dst_area or not tier_ok:
            return False
        if dst_site_id and place.get("site") not in (task.get("dst_site"), dst_site_id):
            return False
    if dst_site_id and place.get("site_id") != dst_site_id:
        return False
    if isinstance(slot, dict) and (place.get("col") != slot.get("col") or place.get("row") != slot.get("row")):
        return False
    if dst_site_id and verification is not None:
        vt = verification.get("target")
        if not isinstance(vt, dict) or vt.get("site_id") != dst_site_id or vt.get("tier") != task.get("tier"):
            return False
        if str(vt.get("area") or "").strip().lower() != dst_area:
            return False
        if isinstance(slot, dict) and (vt.get("col") != slot.get("col") or vt.get("row") != slot.get("row")):
            return False
    return True


def act_route_refusal(cell_id: str, arm_id: str, src_site: str, dst_site: str,
                      tier: int, displaced_to: str | None) -> str | None:
    """Check the resolved task sites against the route the selected policy can represent."""
    if ARM_CELL.get(arm_id) != cell_id:
        return "ACT_POLICY_UNSUPPORTED_ARM"
    if displaced_to is not None:
        return "INVALID_EXECUTION_MODE"
    if cell_id == "cell_ab":
        if type(tier) is not int or tier not in (1, 2, 3) or src_site != "belt":
            return "ACT_POLICY_INVALID_TARGET"
        if dst_site not in (f"ship-h1r{row}-l{tier - 1}" for row in range(3)):
            return "ACT_POLICY_INVALID_TARGET"
    return None



def act_fallback_refusal(cell_id: str, task: dict | None) -> str | None:
    """Why a failed task's own route cannot be retried as an ACT fallback, else None."""
    if not task or not all(task.get(k) for k in ("arm_id", "src_site", "dst_site", "tier")):
        return "ORIGINAL_TASK_ROUTE_REQUIRED"
    if task.get("directive"):
        return "DIRECTIVE_REQUIRES_NEW_TASK"
    return act_route_refusal(cell_id, task["arm_id"], task["src_site"], task["dst_site"], task["tier"], task.get("displaced_to"))
