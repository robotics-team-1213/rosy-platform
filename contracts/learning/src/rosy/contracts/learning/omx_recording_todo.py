"""Shared OMX r08 recording geometry, curated manifest/inventory validation, and To-Do planner.

Stdlib-only contract consumed by `canonical_recording_todo.py`, `canonical_web.py`, and curation scripts.
Never accesses the filesystem, network, or hardware control paths (D-911, D-1024).
"""
from __future__ import annotations

import copy
import datetime as dt
import math

from rosy.contracts.learning.omx_canonical import (
    ARM_IDS,
    AUTHORITY_STAMP,
    CANONICAL_START_V1,
    DATA_GATE_HOME_LIMIT_RAD,
    WRIST_ROLL_BRANCH_LIMIT_NORM,
)

CURATED_MANIFEST_SCHEMA = "rosy.omx-curated-manifest/1"
COLLECTION_INVENTORY_SCHEMA = "rosy.omx-collection-inventory/1"
RECORDING_TODO_SCHEMA = "rosy.omx-recording-todo/1"

H1_POLICY_GOALS = tuple(f"ship-h1r{col}-l{tier}" for col in range(3) for tier in range(3)) + ("tray",)
BAYS = ("ship-h1", "ship-h2")
VALID_MANIFEST_BAYS = ("ship-h1", "ship-h2", "unload-ex")
VALID_DIRECTIONS = ("load", "unload")
VALID_SPLIT_ROLES = ("train", "eval_holdout", "exclude")
VALID_WRIST_BRANCHES = ("positive_canonical", "negative_raw", "flipped_to_canonical")
DEFAULT_TARGETS = {"ship-h1": 30, "ship-h2": 15}
NEAR_FIXED_PAN_STD_RAD = 0.08  # ~2.5 norm std dev -> pick pose variance warning

ARM_META = {
    "arm_b": {
        "arm_id": "arm_b",
        "label": "arm_b · 왼팔",
        "side": "left",
        "fixture_y_sign": "+y",
        "nearest_row": 2,
        "nearest_legacy": "S01",
    },
    "arm_a": {
        "arm_id": "arm_a",
        "label": "arm_a · 오른팔",
        "side": "right",
        "fixture_y_sign": "-y",
        "nearest_row": 0,
        "nearest_legacy": "S03",
    },
}

HOLD_META = {
    "ship-h1": {
        "bay": "ship-h1",
        "label": "ship-h1 · 선미 (벨트쪽 · 직선운반)",
        "legacy_slots": ("S01", "S02", "S03"),
        "in_h1_scope": True,
        "data_gate_scope": "h1",
    },
    "ship-h2": {
        "bay": "ship-h2",
        "label": "ship-h2 · 선수 (180° 회전 · 별도 범위)",
        "legacy_slots": ("S04", "S05", "S06"),
        "in_h1_scope": False,
        "data_gate_scope": "h2",
    },
}

LAYER_META = {
    "l0": {"layer": 0, "layer_id": "l0", "legacy_layer": "F01", "label": "1층 (l0 · 구 F01)", "tier_z_mm": 6.0},
    "l1": {"layer": 1, "layer_id": "l1", "legacy_layer": "F02", "label": "2층 (l1 · 구 F02)", "tier_z_mm": 38.4},
    "l2": {"layer": 2, "layer_id": "l2", "legacy_layer": "F03", "label": "3층 (l2 · 구 F03)", "tier_z_mm": 70.8},
}

_LEGACY_SLOT = {
    ("ship-h1", 2): "S01", ("ship-h1", 1): "S02", ("ship-h1", 0): "S03",
    ("ship-h2", 2): "S04", ("ship-h2", 1): "S05", ("ship-h2", 0): "S06",
}


def _build_slots() -> tuple[dict, ...]:
    out = []
    for bay in BAYS:
        in_h1 = bay == "ship-h1"
        site_hold = 2 if in_h1 else 1
        for layer in range(3):
            lm = LAYER_META[f"l{layer}"]
            for row in (2, 1, 0):  # r2(arm_b/S01) -> r1(center/S02) -> r0(arm_a/S03)
                slot_id = f"{bay}r{row}-l{layer}"
                out.append({
                    "slot_id": slot_id,
                    "bay": bay,
                    "row": row,
                    "layer": layer,
                    "layer_id": f"l{layer}",
                    "legacy_slot": _LEGACY_SLOT[(bay, row)],
                    "legacy_layer": lm["legacy_layer"],
                    "tier_z_mm": lm["tier_z_mm"],
                    "site_map_id": f"yard:r{row + 1}-s{site_hold}-t{layer + 1}",
                    "task_card_id": f"belt-to-{slot_id}",
                    "goal_index_h1": row * 3 + layer if in_h1 else None,
                    "canonical_task": f"Move the designated container from belt to {slot_id}.",
                    "data_gate_scope": "h1" if in_h1 else "h2",
                    "in_h1_scope": in_h1,
                })
    return tuple(out)


SLOTS = _build_slots()
SLOT_BY_ID = {s["slot_id"]: s for s in SLOTS}
CELL_GEOMETRY = {"arms": ARM_META, "holds": HOLD_META, "layers": LAYER_META, "slots": list(SLOTS)}

FILMING_PROTOCOL = {
    "cameras": [
        {"role": "top", "meaning": "상단 D435 오버헤드 (구 11-14~19 rs / 11-21 top)"},
        {"role": "side", "meaning": "공용 측면 카메라 (구 11-14~19 top / 11-21 bottom)"},
        {"role": "wrist", "meaning": "동작 팔 손목 카메라 (arm_b -48 분기는 정렬 시 180도 회전)"},
    ],
    "data_gate": {
        "min_frames": 60,
        "black_reject_s": 1.0,
        "frozen_review_s": 3.0,
        "home_review_rad": DATA_GATE_HOME_LIMIT_RAD,
        "layout": "random",
        "layout_warning": "고정 배치 금지: 매 에피소드 벨트 픽업 위치·컨테이너 각도를 조금씩 바꾸어 촬영하세요.",
    },
    "canonical_start": {
        arm: {
            "norm": list(CANONICAL_START_V1["canonical_start"][arm]["norm"]),
            "gripper_units": CANONICAL_START_V1["canonical_start"][arm]["gripper_units"],
        }
        for arm in ARM_IDS
    },
    "wrist_roll_safe_bands": {"arm_a": [36.0, 62.0], "arm_b": [36.0, 63.0]},
    "wrist_roll_branch_limit_norm": WRIST_ROLL_BRANCH_LIMIT_NORM,
    "hf_repo": "robotteam/rosy-omx-data",
    "curated_prefix": "curated/omx-real-v1",
    "naming_template": "real/curated/{arm_side}_{arm_id}_{legacy_layer}_{slot_range}_{yyyymmdd}",
    "authority_note": (
        "수집 목표·현황 뷰입니다. 실물 촬영은 셀 PC bench_record.py의 task_card_id로 진행하며, "
        "학습 투입은 data_gate 통과본만 허용되고 실물 적용은 Fleet 승인이 별도 필요합니다(D-911)."
    ),
}


def _int_ge0(val, label: str) -> int:
    if type(val) is not int or val < 0:
        raise ValueError(f"{label} must be non-negative int")
    return val


def _finite_opt(val, label: str) -> float | None:
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
        raise ValueError(f"{label} must be finite number or null")
    return float(val)


def _str_opt(val, label: str, max_len: int = 256) -> str | None:
    if val is None:
        return None
    if not isinstance(val, str) or len(val) > max_len or any(ord(c) < 32 for c in val):
        raise ValueError(f"{label} must be bounded safe string")
    return val


def validate_manifest(doc: dict) -> dict:
    if not isinstance(doc, dict) or doc.get("schema") != CURATED_MANIFEST_SCHEMA:
        raise ValueError(f"manifest requires schema {CURATED_MANIFEST_SCHEMA}")
    datasets = doc.get("datasets")
    if not isinstance(datasets, list) or len(datasets) > 512:
        raise ValueError("manifest datasets must be a bounded list")
    for idx, entry in enumerate(datasets):
        if not isinstance(entry, dict):
            raise ValueError(f"datasets[{idx}] must be mapping")
        if entry.get("arm") not in ARM_IDS:
            raise ValueError(f"datasets[{idx}].arm invalid")
        if entry.get("direction") not in VALID_DIRECTIONS:
            raise ValueError(f"datasets[{idx}].direction invalid")
        bay = entry.get("bay")
        if bay not in VALID_MANIFEST_BAYS:
            raise ValueError(f"datasets[{idx}].bay invalid")
        if entry.get("split_role") not in VALID_SPLIT_ROLES:
            raise ValueError(f"datasets[{idx}].split_role invalid")
        if entry["direction"] == "load":
            if entry.get("slot_id") not in SLOT_BY_ID or SLOT_BY_ID[entry["slot_id"]]["bay"] != bay:
                raise ValueError(f"datasets[{idx}].slot_id mismatches bay")
        eps = entry.get("episodes") or {}
        _int_ge0(eps.get("raw_total", 0), f"datasets[{idx}].episodes.raw_total")
        _int_ge0(eps.get("curated_total", 0), f"datasets[{idx}].episodes.curated_total")
        dg = entry.get("data_gate") or {}
        counts = dg.get("counts") or {}
        for k in ("pass", "review", "reject"):
            _int_ge0(counts.get(k, 0), f"datasets[{idx}].data_gate.counts.{k}")
        wb = entry.get("wrist_roll_branch") or {}
        if wb and wb.get("branch") not in VALID_WRIST_BRANCHES:
            raise ValueError(f"datasets[{idx}].wrist_roll_branch.branch invalid")
        _finite_opt(entry.get("pick_pan_std_rad"), f"datasets[{idx}].pick_pan_std_rad")
    return doc


def validate_inventory(doc: dict) -> dict:
    if not isinstance(doc, dict) or doc.get("schema") != COLLECTION_INVENTORY_SCHEMA:
        raise ValueError(f"inventory requires schema {COLLECTION_INVENTORY_SCHEMA}")
    slots = doc.get("slots")
    if not isinstance(slots, list) or len(slots) > 128:
        raise ValueError("inventory slots must be bounded list")
    for idx, item in enumerate(slots):
        if not isinstance(item, dict):
            raise ValueError(f"slots[{idx}] must be mapping")
        if item.get("arm") not in ARM_IDS or item.get("slot_id") not in SLOT_BY_ID:
            raise ValueError(f"slots[{idx}] invalid arm or slot_id")
        for key in ("target_episodes", "episodes_raw", "episodes_pass", "episodes_review", "episodes_reject", "remaining_episodes"):
            if key in item:
                _int_ge0(item[key], f"slots[{idx}].{key}")
        _finite_opt(item.get("pick_pan_std_rad"), f"slots[{idx}].pick_pan_std_rad")
    return doc


def derive_inventory_from_manifest(manifest: dict, *, targets: dict[str, int] | None = None,
                                   generated_at: str | None = None, manifest_sha256: str | None = None) -> dict:
    validate_manifest(manifest)
    tmap = {**DEFAULT_TARGETS, **(targets or {})}
    buckets: dict[tuple[str, str], dict] = {}
    for arm in ("arm_b", "arm_a"):
        for slot in SLOTS:
            buckets[(arm, slot["slot_id"])] = {
                "raw": 0, "pass": 0, "rev": 0, "rej": 0, "canon": 0, "neg": 0, "holdout": 0,
                "pan_stds": [], "ds_ids": [],
            }
    for entry in manifest["datasets"]:
        if entry["direction"] != "load" or entry["bay"] not in BAYS:
            continue
        b = buckets[(entry["arm"], entry["slot_id"])]
        dg = entry.get("data_gate") or {}
        cnt = dg.get("counts") or {}
        if entry["split_role"] == "eval_holdout":
            b["holdout"] += int((entry.get("episodes") or {}).get("raw_total", 0))
            b["ds_ids"].append(str(entry.get("dataset_id") or "")[:64])
            continue
        if entry["split_role"] != "train" or dg.get("goal_scope") != SLOT_BY_ID[entry["slot_id"]]["data_gate_scope"]:
            continue
        b["ds_ids"].append(str(entry.get("dataset_id") or "")[:64])
        b["raw"] += int((entry.get("episodes") or {}).get("raw_total", 0))
        if dg.get("admissible") is True and not dg.get("dataset_reject"):
            passed = int(cnt.get("pass", 0))
            b["pass"] += passed
            b["rev"] += int(cnt.get("review", 0))
            b["rej"] += int(cnt.get("reject", 0))
            branch = (entry.get("wrist_roll_branch") or {}).get("branch")
            if branch == "negative_raw":
                b["neg"] += passed
            elif branch in ("positive_canonical", "flipped_to_canonical"):
                b["canon"] += passed
        if entry.get("pick_pan_std_rad") is not None:
            b["pan_stds"].append(float(entry["pick_pan_std_rad"]))

    rows = []
    for (arm, slot_id), b in buckets.items():
        slot = SLOT_BY_ID[slot_id]
        target = int(tmap[slot["bay"]])
        rem = max(0, target - b["pass"])
        pan_min = min(b["pan_stds"]) if b["pan_stds"] else None
        neg_only = b["pass"] > 0 and b["canon"] == 0 and b["neg"] > 0
        near_fixed = pan_min is not None and pan_min < NEAR_FIXED_PAN_STD_RAD
        if slot["bay"] == "ship-h1":
            priority = "P1" if b["pass"] == 0 else ("P2" if (rem > 0 or neg_only or near_fixed) else "DONE")
        else:
            priority = "P3" if rem > 0 else "DONE"
        status = "missing" if b["pass"] == 0 else ("needs_more" if rem > 0 else ("branch_mismatch_only" if neg_only else ("near_fixed_warning" if near_fixed else "done")))
        rows.append({
            "arm": arm, "bay": slot["bay"], "slot_id": slot_id, "row": slot["row"], "layer": slot["layer"],
            "legacy_slot": slot["legacy_slot"], "legacy_layer": slot["legacy_layer"],
            "site_map_id": slot["site_map_id"], "task_card_id": slot["task_card_id"],
            "goal_index_h1": slot["goal_index_h1"], "canonical_task": slot["canonical_task"],
            "target_episodes": target, "episodes_raw": b["raw"], "episodes_pass": b["pass"],
            "episodes_review": b["rev"], "episodes_reject": b["rej"],
            "episodes_canonical_branch": b["canon"], "episodes_negative_branch": b["neg"],
            "holdout_episodes": b["holdout"], "pick_pan_std_rad": round(pan_min, 4) if pan_min is not None else None,
            "negative_branch_only": neg_only, "near_fixed_layout": near_fixed,
            "remaining_episodes": rem, "status": status, "priority": priority, "dataset_ids": [d for d in b["ds_ids"] if d],
        })
    return {
        "schema": COLLECTION_INVENTORY_SCHEMA,
        "curated_version": _str_opt(manifest.get("curated_version"), "curated_version") or "omx-real-v1",
        "hf_repo": _str_opt(manifest.get("hf_repo"), "hf_repo") or "robotteam/rosy-omx-data",
        "hf_revision": _str_opt(manifest.get("hf_revision"), "hf_revision", 64),
        "manifest_sha256": _str_opt(manifest_sha256, "manifest_sha256", 64),
        "generated_at": _str_opt(generated_at or manifest.get("generated_at"), "generated_at", 64) or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "slots": rows,
        **AUTHORITY_STAMP,
    }


def _local_goal_counts(local_receipts: list[dict] | None) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for rec in local_receipts or []:
        arm = rec.get("arm")
        if arm not in ARM_IDS or rec.get("dataset_reject"):
            continue
        for g, n in (rec.get("goals_passing_counts") or {}).items():
            out[(arm, g)] = max(out.get((arm, g), 0), int(n))
    return out


def build_recording_todo(inventory: dict | None, *, local_receipts: list[dict] | None = None,
                         source_state: str = "unconfigured") -> dict:
    base = {
        "schema": RECORDING_TODO_SCHEMA,
        "inventory_status": source_state,
        "cell_geometry": copy.deepcopy(CELL_GEOMETRY),
        "filming_protocol": copy.deepcopy(FILMING_PROTOCOL),
        **AUTHORITY_STAMP,
    }
    if inventory is None:
        return {**base, "provenance": None, "summary": None, "cards": []}
    validate_inventory(inventory)
    local_counts = _local_goal_counts(local_receipts)
    groups: dict[tuple[str, str, int], list[dict]] = {}
    for row in inventory["slots"]:
        slot = SLOT_BY_ID[row["slot_id"]]
        key = (row["arm"], slot["bay"], slot["layer"])
        groups.setdefault(key, []).append({**row, "local_gate_passed": local_counts.get((row["arm"], row["slot_id"]))})

    prio_rank = {"p1": 0, "p2": 1, "p3": 2, "done": 3}
    cards = []
    for (arm, bay, layer), items in groups.items():
        items.sort(key=lambda r: -int(r["row"]))
        lm = LAYER_META[f"l{layer}"]
        passed = sum(int(i.get("episodes_pass", 0)) for i in items)
        raw_total = sum(int(i.get("episodes_raw", 0)) for i in items)
        target = sum(int(i.get("target_episodes", 0)) for i in items)
        rem = sum(int(i.get("remaining_episodes", 0)) for i in items)
        holdout = sum(int(i.get("holdout_episodes", 0)) for i in items)
        neg_only = any(i.get("negative_branch_only") or (i.get("episodes_negative_branch", 0) > 0 and i.get("episodes_canonical_branch", 0) == 0) for i in items)
        near_fixed = any(i.get("near_fixed_layout") for i in items)
        all_zero_h1 = bay == "ship-h1" and passed == 0
        if bay == "ship-h1":
            prio = "p1" if all_zero_h1 else ("p2" if (rem > 0 or neg_only or near_fixed) else "done")
        else:
            prio = "p3" if rem > 0 else "done"
        warnings = []
        if neg_only:
            warnings.append("negative_wrist_branch")
        if near_fixed:
            warnings.append("near_fixed_layout")
        if bay == "ship-h2":
            warnings.append("h2_separate_scope")
        if holdout:
            warnings.append("holdout_excluded")
        legacy_slots = HOLD_META[bay]["legacy_slots"]
        slot_range = f"{legacy_slots[0]}..{legacy_slots[-1]}"
        arm_meta = ARM_META[arm]
        cards.append({
            "card_id": f"{arm}-{bay}-l{layer}",
            "priority": prio,
            "priority_label": {"p1": "우선순위 1 · 미촬영(0 ep)", "p2": "우선순위 2 · 부족/보강", "p3": "우선순위 3 · h2 별도", "done": "충족"}[prio],
            "arm": arm,
            "arm_label": arm_meta["label"],
            "bay": bay,
            "bay_label": HOLD_META[bay]["label"],
            "layer": layer,
            "layer_id": lm["layer_id"],
            "legacy_layer": lm["legacy_layer"],
            "layer_label": lm["label"],
            "tier_z_mm": lm["tier_z_mm"],
            "slot_range_label": f"r2~r0 (구 {slot_range})",
            "target_slot_ids": [i["slot_id"] for i in items],
            "episodes_raw": raw_total,
            "episodes_pass": passed,
            "episodes_target": target,
            "remaining_episodes": rem,
            "holdout_episodes": holdout,
            "warnings": warnings,
            "hf_path_hint": f"real/curated/{arm_meta['side'].capitalize()}_{arm}_{lm['legacy_layer']}_{legacy_slots[0]}_{legacy_slots[-1]}",
            "bench_card_ids": [i["task_card_id"] for i in items],
            "goal_text_examples": [SLOT_BY_ID[i["slot_id"]]["canonical_task"] for i in items],
            "slots": items,
        })
    cards.sort(key=lambda c: (prio_rank[c["priority"]], 0 if c["bay"] == "ship-h1" else 1, c["layer"], 0 if c["arm"] == "arm_b" else 1))
    h1_cards = [c for c in cards if c["bay"] == "ship-h1"]
    return {
        **base,
        "inventory_status": "ready",
        "provenance": {
            "hf_repo": inventory.get("hf_repo") or "robotteam/rosy-omx-data",
            "curated_version": inventory.get("curated_version") or "omx-real-v1",
            "hf_revision": inventory.get("hf_revision"),
            "manifest_sha256": inventory.get("manifest_sha256"),
            "generated_at": inventory.get("generated_at"),
            "source_state": source_state,
        },
        "summary": {
            "ship_h1_pass": sum(c["episodes_pass"] for c in h1_cards),
            "ship_h1_target": sum(c["episodes_target"] for c in h1_cards),
            "ship_h1_remaining": sum(c["remaining_episodes"] for c in h1_cards),
            "cards_total": len(cards),
            "cards_needing_action": sum(1 for c in cards if c["priority"] != "done"),
        },
        "cards": cards,
    }
