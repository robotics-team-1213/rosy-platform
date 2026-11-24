"""Deterministic dual-mode cell plan solver/validator on canonical 37-site cell map (harbor_plan vs rosy_r)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fleet.pipeline.cell_site_targets import _index, _map_path, resolve_cell_task_targets

HARBOR_ARMS = {"A": "arm_a", "B": "arm_b"}
_ARM_LETTERS = {arm_id: letter for letter, arm_id in HARBOR_ARMS.items()}
REORDER_WIDTH = 4
PARK_WIDTH = 4
NODE_BUDGET = 20000
MAX_PLAN_STEPS = 32
_SUPPORTED_MODES = frozenset({"harbor_plan", "outbound", "rehandle", "goal"})


@dataclass(frozen=True)
class _CellLayout:
    sites: dict[str, dict[str, Any]]
    stack_at: dict[tuple[str, int], str]
    by_wire: dict[str, str]
    by_sim: dict[str, str]
    slots: dict[str, dict[str, Any]]


def _build_layout(web_common: Path | None = None) -> _CellLayout:
    idx = _index(str(_map_path(web_common).resolve()))
    sites: dict[str, dict[str, Any]] = {}
    stack_at: dict[tuple[str, int], str] = {}
    for rec in idx["sites"]:
        area = rec["area"]
        kind = "ship" if area == "yard" else "temp" if area in ("temp_a", "temp_b") else "stand"
        plate = "a" if area == "temp_a" else "b" if area == "temp_b" else None
        stack = rec["slot_id"]
        layer = int(rec["tier"]) - 1
        sites[rec["site_id"]] = {
            **rec,
            "kind": kind,
            "plate": plate,
            "stack": stack,
            "layer": layer,
            "row0": int(rec["row"]) - 1,
        }
        stack_at[(stack, layer)] = rec["site_id"]
    by_wire = {k: v["site_id"] for k, v in idx["by_wire"].items()}
    by_sim = {k: v["site_id"] for k, v in idx["by_sim"].items()}
    return _CellLayout(sites=sites, stack_at=stack_at, by_wire=by_wire, by_sim=by_sim, slots=idx["slots_by_id"])


def _zone(layout: _CellLayout, site_id: str) -> str:
    s = layout.sites[site_id]
    if s["kind"] == "temp":
        return s["plate"]
    if s["kind"] == "stand":
        return "a"
    return "a" if s["row0"] == 0 else "b" if s["row0"] == 2 else "mid"


def _resolve_site_id(raw: Any, layout: _CellLayout, *, allow_belt: bool = False) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("INVALID_CELL_TASK_INPUT")
    text = raw.strip()
    if text == "belt":
        if allow_belt:
            return "belt"
        raise ValueError("UNKNOWN_CELL_SITE")
    if text in layout.sites:
        return text
    if text in layout.by_wire:
        return layout.by_wire[text]
    if text in layout.by_sim:
        return layout.by_sim[text]
    raise ValueError("UNKNOWN_CELL_SITE")


def _normalize_arm(raw_arm: Any, raw_arms: Any) -> str | None:
    if raw_arm is not None and raw_arm != "":
        text = str(raw_arm).strip()
        if text in HARBOR_ARMS:
            return HARBOR_ARMS[text]
        if text in ("arm_a", "arm_b"):
            return text
        raise ValueError("INVALID_CELL_SITE_ARM")
    if raw_arms is not None:
        if not isinstance(raw_arms, list) or not raw_arms:
            raise ValueError("INVALID_CELL_SITE_ARM")
        first = str(raw_arms[0]).strip()
        if first in HARBOR_ARMS:
            return HARBOR_ARMS[first]
        if first in ("arm_a", "arm_b"):
            return first
        raise ValueError("INVALID_CELL_SITE_ARM")
    return None


def _normalize_state(raw_state: Any, layout: _CellLayout) -> dict[str, str]:
    if not isinstance(raw_state, dict):
        raise ValueError("INVALID_CELL_PLAN_STATE")
    normalized: dict[str, str] = {}
    used_sites: set[str] = set()
    for cargo_id, site_ref in raw_state.items():
        if not isinstance(cargo_id, str) or not cargo_id.strip():
            raise ValueError("INVALID_CELL_PLAN_STATE")
        site_id = _resolve_site_id(site_ref, layout)
        if site_id in used_sites:
            raise ValueError("DUPLICATE_STATE_OCCUPANCY")
        used_sites.add(site_id)
        normalized[cargo_id.strip()] = site_id
    for site_id in used_sites:
        info = layout.sites[site_id]
        if info["layer"] > 0:
            below = layout.stack_at.get((info["stack"], info["layer"] - 1))
            if below not in used_sites:
                raise ValueError("FLOATING_STATE_CARGO")
    return normalized


def _normalize_avoid(raw_avoid: Any, layout: _CellLayout) -> tuple[str, ...]:
    if raw_avoid is None:
        return ()
    if not isinstance(raw_avoid, (list, tuple)):
        raise ValueError("INVALID_CELL_TASK_INPUT")
    return tuple(_resolve_site_id(item, layout) for item in raw_avoid)


def _temp_spots(layout: _CellLayout, occupied: set[str], avoid: set[str]) -> list[str]:
    used = occupied | avoid
    spots = [
        sid for sid, info in layout.sites.items()
        if info["kind"] in ("temp", "ship")
        and sid not in used
        and (info["layer"] == 0 or layout.stack_at.get((info["stack"], info["layer"] - 1)) in occupied)
    ]
    return sorted(spots, key=lambda sid: (layout.sites[sid]["kind"] != "temp", layout.sites[sid]["layer"], sid))


def _can(layout: _CellLayout, src_id: str, dst_id: str) -> tuple[str, ...]:
    return tuple(arm for arm in ("arm_a", "arm_b") if arm in layout.sites[src_id]["arms"] and arm in layout.sites[dst_id]["arms"])


def _plan_outbound_or_rehandle(
    layout: _CellLayout, state: dict[str, str], request: dict[str, Any], avoid: tuple[str, ...],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    target = request.get("cargo_id")
    reorder = bool(request.get("reorder", False))
    if not isinstance(target, str) or not target.strip() or target.strip() not in state:
        return None, "OUTBOUND_NOT_OBSERVED"
    target = target.strip()
    target_site = state[target]
    t_info = layout.sites[target_site]
    key, base = t_info["stack"], t_info["layer"]
    blockers = sorted(
        (c for c, sid in state.items()
         if layout.sites[sid]["stack"] == key and (layout.sites[sid]["layer"] > base or (reorder and c == target))),
        key=lambda c: -layout.sites[state[c]]["layer"],
    )
    failures: list[str] = []

    def step(cur: dict[str, str], cargo: str, dst_id: str, phase: str) -> dict[str, Any] | None:
        src_id = cur[cargo]
        arms = _can(layout, src_id, dst_id)
        if not arms:
            return None
        return {
            "cargo_id": cargo,
            "src_site": src_id,
            "dst_site": dst_id,
            "arm_id": arms[0],
            "arms": list(arms),
            "phase_label": phase,
        }

    def seat(offset: int) -> str:
        return layout.stack_at[(key, base + offset)]

    def outbound_lanes(cur: dict[str, str]) -> list[str]:
        dest = request.get("destination")
        occupied = set(cur.values()) | set(avoid)
        if dest in (None, "", "stand", "stand:r1-s1", "stand:r1-s1-t1", "stand-r1-c1-l1"):
            return ["stand:r1-s1-t1"] if "stand:r1-s1-t1" in layout.sites and "stand:r1-s1-t1" not in occupied else []
        if dest == "temp":
            return sorted(
                sid for sid, info in layout.sites.items()
                if info["kind"] == "temp" and info["layer"] == 0 and sid not in occupied
            )
        dst_id = _resolve_site_id(dest, layout)
        return [dst_id] if layout.sites[dst_id]["layer"] == 0 and dst_id not in occupied else []

    def put(cur: dict[str, str], moves: list[dict[str, Any]], places: list[tuple[str, str, str]]) -> list[dict[str, Any]] | None:
        nxt_moves = list(moves)
        nxt_cur = dict(cur)
        for cargo, dst_id, phase in places:
            m = step(nxt_cur, cargo, dst_id, phase)
            if m is None:
                failures.append("NO_STAND_IN_REACH" if phase == "반출" else "NO_ARM_FOR_RESTORE")
                return None
            nxt_moves.append(m)
            nxt_cur[cargo] = dst_id
        return nxt_moves

    def finish(cur: dict[str, str], moves: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if reorder:
            return put(cur, moves, [(c, seat(i), "복귀") for i, c in enumerate(blockers[-1:] + blockers[:-1])])
        lanes = outbound_lanes(cur)
        if not lanes:
            failures.append("NO_FREE_OUTBOUND_LANE")
            return None
        for lane in lanes:
            done = put(cur, moves, [(target, lane, "반출")] + [(c, seat(i), "복귀") for i, c in enumerate(reversed(blockers))])
            if done is not None:
                return done
        return None

    def search(idx: int, cur: dict[str, str], moves: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if idx == len(blockers):
            return finish(cur, moves)
        cargo = blockers[idx]
        occupied = set(cur.values()) - {cur[cargo]}
        options = sorted(
            (t for t in _temp_spots(layout, occupied, set(avoid)) if layout.sites[t]["stack"] != key),
            key=lambda t: (layout.sites[t]["kind"] != "temp", _zone(layout, t) != _zone(layout, cur[cargo])),
        )
        for t in (options[:REORDER_WIDTH] if reorder else options):
            m = step(cur, cargo, t, "재취급")
            if m is not None:
                found = search(idx + 1, {**cur, cargo: t}, [*moves, m])
                if found is not None:
                    return found
        failures.append("NO_TEMPORARY_SPACE_IN_REACH")
        return None

    if not reorder:
        lanes = outbound_lanes(state)
        if not lanes:
            return None, "NO_FREE_OUTBOUND_LANE"
        if not any(_can(layout, target_site, lane) for lane in lanes):
            return None, "NO_STAND_IN_REACH"
    planned = search(0, dict(state), [])
    return (planned, None) if planned is not None else (None, failures[0] if failures else "NO_LEGAL_PLAN")


def _plan_goal_stacks(
    layout: _CellLayout, state: dict[str, str], raw_goal: Any, avoid: tuple[str, ...],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(raw_goal, dict) or not raw_goal:
        return None, "UNKNOWN_SITE"
    goal: dict[str, list[str]] = {}
    for raw_key, cargos in raw_goal.items():
        if not isinstance(cargos, list):
            return None, "UNKNOWN_SITE"
        key = str(raw_key)
        if key not in layout.slots:
            return None, "UNKNOWN_SITE"
        if len(cargos) > layout.slots[key]["max_tier"]:
            return None, "UNKNOWN_SITE"
        goal[key] = [str(c) for c in cargos]
    order = [(cargo, layout.stack_at[(k, t)]) for k, cargos in goal.items() for t, cargo in enumerate(cargos)]
    if not order:
        return None, "EMPTY_GOAL"
    if len({cargo for cargo, _ in order}) != len(order):
        return None, "DUPLICATE_GOAL_CARGO"
    if any(cargo not in state for cargo, _ in order):
        return None, "UNKNOWN_CARGO"
    if all(state[cargo] == dst_id for cargo, dst_id in order):
        return None, "GOAL_ALREADY_SATISFIED"

    goal_keys = set(goal)
    failures: list[str] = []
    nodes = [0]

    def above(cur: dict[str, str], site_id: str) -> list[str]:
        info = layout.sites[site_id]
        return [
            c for c, sid in cur.items()
            if layout.sites[sid]["stack"] == info["stack"] and layout.sites[sid]["layer"] > info["layer"]
        ]

    def blockers(cur: dict[str, str], cargo: str, dst_id: str) -> list[str]:
        d_info = layout.sites[dst_id]
        found = set(above(cur, cur[cargo])) | {
            c for c, sid in cur.items()
            if layout.sites[sid]["stack"] == d_info["stack"] and layout.sites[sid]["layer"] >= d_info["layer"]
        }
        return sorted(found, key=lambda c: -layout.sites[cur[c]]["layer"])

    def free_tiers(cur: dict[str, str], site_id: str) -> int:
        key = layout.sites[site_id]["stack"]
        return layout.slots[key]["max_tier"] - sum(layout.sites[sid]["stack"] == key for sid in cur.values())

    def step(cur: dict[str, str], moves: list[dict[str, Any]], cargo: str, dst_id: str, phase: str) -> dict[str, Any] | None:
        arms = list(_can(layout, cur[cargo], dst_id))
        if not arms:
            failures.append("UNREACHABLE")
            return None
        if moves and moves[-1]["arm_id"] in arms:
            prev_arm = moves[-1]["arm_id"]
            arms = [prev_arm, *(a for a in arms if a != prev_arm)]
        return {
            "cargo_id": cargo,
            "src_site": cur[cargo],
            "dst_site": dst_id,
            "arm_id": arms[0],
            "arms": arms,
            "phase_label": phase,
        }

    def go(cur: dict[str, str], moves: list[dict[str, Any]], idx: int) -> list[dict[str, Any]] | None:
        nodes[0] += 1
        if nodes[0] > NODE_BUDGET:
            return None
        if idx == len(order):
            return moves
        cargo, dst_id = order[idx]
        if cur[cargo] == dst_id:
            return go(cur, moves, idx + 1)
        rem = blockers(cur, cargo, dst_id)
        if rem:
            c = rem[0]
            occupied = set(cur.values()) - {cur[c]}
            spots = [t for t in _temp_spots(layout, occupied, set(avoid)) if layout.sites[t]["stack"] not in goal_keys]
            if not spots:
                failures.append("NO_BUFFER")
            spots.sort(key=lambda t: (layout.sites[t]["kind"] != "temp", layout.sites[t]["layer"], -free_tiers(cur, t)))
            for t in spots[:PARK_WIDTH]:
                m = step(cur, moves, c, t, "재취급")
                if m is not None:
                    done = go({**cur, c: t}, [*moves, m], idx)
                    if done is not None:
                        return done
            return None
        d_info = layout.sites[dst_id]
        if d_info["layer"] > 0 and layout.stack_at[(d_info["stack"], d_info["layer"] - 1)] not in cur.values():
            failures.append("NO_SUPPORT")
            return None
        m = step(cur, moves, cargo, dst_id, "장치")
        return None if m is None else go({**cur, cargo: dst_id}, [*moves, m], idx + 1)

    planned = go(dict(state), [], 0)
    return (planned, None) if planned is not None else (None, failures[0] if failures else "NO_LEGAL_PLAN")


def _validate_harbor_steps(
    raw_steps: Any, layout: _CellLayout, state: dict[str, str] | None, *, web_common: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
    if not isinstance(raw_steps, list) or not (1 <= len(raw_steps) <= MAX_PLAN_STEPS):
        raise ValueError("INVALID_HARBOR_PLAN_STEPS")
    current = dict(state) if state is not None else None
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise ValueError("INVALID_HARBOR_PLAN_STEPS")
        raw_src = raw.get("src_site") if "src_site" in raw else raw.get("source")
        raw_dst = raw.get("dst_site") if "dst_site" in raw else raw.get("destination")
        src_id = _resolve_site_id(raw_src, layout, allow_belt=True)
        dst_id = _resolve_site_id(raw_dst, layout, allow_belt=True)
        if src_id == dst_id:
            raise ValueError("INVALID_CELL_SITE")
        req_arm = _normalize_arm(raw.get("arm_id") or raw.get("arm") or raw.get("primary_arm"), raw.get("arms"))
        spec = {
            "src_site": src_id,
            "dst_site": dst_id,
            **({"arm_id": req_arm} if req_arm is not None else {}),
            **({"tier": raw["tier"]} if "tier" in raw else {}),
        }
        targets = resolve_cell_task_targets("cell_ab", spec, web_common=web_common, legacy_sites=("belt", "vehicle"))
        cargo_id = raw.get("cargo_id")
        if cargo_id is not None:
            if not isinstance(cargo_id, str) or not cargo_id.strip():
                raise ValueError("INVALID_HARBOR_PLAN_STEPS")
            cargo_id = cargo_id.strip()

        if current is not None:
            if src_id == "belt":
                moving_cargo = cargo_id or f"inbound-{idx + 1}"
                if moving_cargo in current:
                    raise ValueError("HARBOR_ORDER_NOT_EXECUTABLE")
            else:
                occupant = next((c for c, sid in current.items() if sid == src_id), None)
                if cargo_id is not None:
                    if current.get(cargo_id) != src_id:
                        raise ValueError("HARBOR_ORDER_NOT_EXECUTABLE")
                    moving_cargo = cargo_id
                else:
                    if occupant is None:
                        raise ValueError("EMPTY_SOURCE_SITE")
                    moving_cargo = occupant
                s_info = layout.sites[src_id]
                if any(
                    layout.stack_at.get((s_info["stack"], l)) in current.values()
                    for l in range(s_info["layer"] + 1, layout.slots[s_info["stack"]]["max_tier"])
                ):
                    raise ValueError("BLOCKED_SOURCE_CARGO")
            if dst_id == "belt":
                current.pop(moving_cargo, None)
            else:
                if dst_id in current.values():
                    raise ValueError("OCCUPIED_DESTINATION")
                d_info = layout.sites[dst_id]
                if d_info["layer"] > 0 and layout.stack_at.get((d_info["stack"], d_info["layer"] - 1)) not in current.values():
                    raise ValueError("UNSUPPORTED_DESTINATION_TIER")
                current[moving_cargo] = dst_id
            cargo_id = moving_cargo

        dst_wire = layout.sites[dst_id]["wire_ref"] if dst_id in layout.sites else None
        src_wire = layout.sites[src_id]["wire_ref"] if src_id in layout.sites else None
        normalized.append({
            "step_index": idx,
            "cargo_id": cargo_id,
            "src_site": src_id,
            "dst_site": dst_id,
            "src_wire_ref": src_wire,
            "dst_wire_ref": dst_wire,
            "src_sim_site": targets["src_site"],
            "dst_sim_site": targets["dst_site"],
            "arm_id": targets["arm_id"],
            "tier": targets["tier"],
            "phase_label": str(raw.get("phase_label") or "이동"),
        })
    return normalized, current


def plan_cell_moves(body: dict[str, Any], *, web_common: Path | None = None) -> dict[str, Any]:
    """Plan or validate sequential cell_ab moves for either explicit Harbor plans or autonomous ROSY directives."""
    if not isinstance(body, dict):
        raise ValueError("INVALID_CELL_PLAN_INPUT")
    mode = str(body.get("mode") or ("harbor_plan" if ("steps" in body or "harbor_order" in body) else "")).strip()
    if mode not in _SUPPORTED_MODES:
        raise ValueError("INVALID_PLAN_MODE")

    layout = _build_layout(web_common)
    has_explicit_steps = body.get("steps") is not None or body.get("harbor_order") is not None
    raw_state = body.get("state")

    if mode == "harbor_plan":
        raw_steps = body.get("steps") if body.get("steps") is not None else body.get("harbor_order")
        state = _normalize_state(raw_state, layout) if raw_state is not None else None
        moves, final_state = _validate_harbor_steps(raw_steps, layout, state, web_common=web_common)
        return {
            "ok": True,
            "mode": mode,
            "order_source": "harbor",
            "moves": moves,
            "final_state": final_state,
            "why": None,
        }

    if has_explicit_steps:
        raise ValueError("AMBIGUOUS_PLAN_MODE")
    if not isinstance(raw_state, dict) or not raw_state:
        raise ValueError("STATE_REQUIRED")
    state = _normalize_state(raw_state, layout)
    avoid = _normalize_avoid(body.get("avoid"), layout)

    if mode in ("outbound", "rehandle"):
        req = dict(body.get("request") or {})
        for key in ("cargo_id", "destination", "reorder"):
            if key in body and key not in req:
                req[key] = body[key]
        if mode == "rehandle":
            req["reorder"] = True
        raw_moves, why = _plan_outbound_or_rehandle(layout, state, req, avoid)
    else:
        raw_moves, why = _plan_goal_stacks(layout, state, body.get("goal"), avoid)

    if raw_moves is None:
        return {"ok": False, "mode": mode, "order_source": "rosy_r", "moves": None, "final_state": None, "why": why}

    moves, final_state = _validate_harbor_steps(raw_moves, layout, state, web_common=web_common)
    return {
        "ok": True,
        "mode": mode,
        "order_source": "rosy_r",
        "moves": moves,
        "final_state": final_state,
        "why": None,
    }
