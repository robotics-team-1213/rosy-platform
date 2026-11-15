"""Pure move ordering shared by the OMX runtime and simulation planner."""

from collections import Counter
import logging

_LOG = logging.getLogger(__name__)
HARBOR_ARMS = {"A": "arm_a", "B": "arm_b"}
REORDER_WIDTH = 4


def zone(layout, site):
    s = layout.sites[site]
    if s["kind"] == "temp":
        return s["plate"]
    if s["kind"] == "ship":
        return "a" if s["row"] == 0 else "b" if s["row"] == 2 else "mid"
    return "mid"  # conveyor end


def planning_sites(layout):
    """Sites the plans use: all but ship hold 2, which the arms reach at grasp height but not on the validated carry from the conveyor
    (omx_two_arm_tasks refuses it with the stern at the table edge), and temporary lanes under the hull."""
    return [s for s, v in layout.sites.items() if not v.get("blocked") and (v["kind"] != "ship" or v["stack"].startswith("h1") or v["stack"] == "stern")]


def stack_key(layout, site):
    s = layout.sites[site]
    return s.get("stack", site)


def harbor_moves(layout, state, request, can, avoid=()):
    """Harbor-shaped moves for one outbound request on `state` (cargo -> site): every container above the target, top first, to a free
    temporary lane or free supported ship site, the target to a free lane of a temporary plate (the outbound place: Harbor names the lane
    per job, here the first that works), then the blockers back into the target's stack from its bottom,
    in their old order; the first complete plan wins (depth first, as harbor/spatial.plan_spatial searches complete plans). Each move
    carries `arms`, every arm that can do it in the state it runs in. Returns (moves, None) or (None, HOLD reason).
    `reorder` (재배치): the target stays; it and everything above it go out top first and come back in a new order (see finish)."""
    target, reorder = request["cargo_id"], request.get("reorder", False)
    if target not in state:
        return None, "OUTBOUND_NOT_OBSERVED"
    site = state[target]
    key, base = stack_key(layout, site), layout.sites[site].get("layer", 0)
    blockers = sorted((c for c, s in state.items() if stack_key(layout, s) == key and (layout.sites[s].get("layer", 0) > base or reorder and c == target)),
                      key=lambda c: -layout.sites[state[c]]["layer"])
    failures = []
    plan_sites = planning_sites(layout)  # built once, shared by finish() and every recursive temp_spots call below

    def step(cur, cargo, b, phase):
        a, here = cur[cargo], {c: s for c, s in cur.items() if c != cargo}
        found = [h for h, name in HARBOR_ARMS.items() if name in can(a, b, here)]
        if not found:
            return None
        return dict(cargo_id=cargo, source=a, destination=b, primary_arm=found[0], alternate_arms=found[1:], phase_label=phase,
                    arms=[HARBOR_ARMS[h] for h in found])

    def seat(i):
        return next(s for s, v in layout.sites.items() if v.get("stack") == key and v["layer"] == base + i)

    def finish(cur, moves):
        """Outbound to the first free lane that lets the whole job finish, then the blockers back, lowest first into the target's freed
        level; None when an arm is missing on the way. A reorder puts the old bottom back first, then the rest top first (the containers
        above it reversed): only the bottom needs the far arm, the rest stays with the near arm on its own side, so the two rows overlap."""
        if reorder:
            return put(cur, moves, [(c, seat(i), "복귀") for i, c in enumerate(blockers[-1:] + blockers[:-1])])
        lanes = sorted(s for s in plan_sites if layout.sites[s]["kind"] == "temp" and layout.sites[s]["layer"] == 0  # Pinky takes it off an empty lane
                       and s not in cur.values() and s not in avoid)
        if not lanes:
            failures.append("NO_FREE_OUTBOUND_LANE")
        return next((done for stand in lanes if (done := put(cur, moves, [(target, stand, "반출")] + [
            (c, seat(i), "복귀") for i, c in enumerate(reversed(blockers))]))), None)

    def put(cur, moves, places):
        for cargo, b, phase in places:
            m = step(cur, cargo, b, phase)
            if m is None:
                failures.append("NO_STAND_IN_REACH" if phase == "반출" else "NO_ARM_FOR_RESTORE")
                return None
            moves, cur = moves + [m], {**cur, cargo: b}
        return moves

    def search(i, cur, moves):
        """Blockers top first, each to a temporary place (same zone first); back up and try the next place when a later move has no arm
        (a blocker left where only the near arm reaches cannot come back under its wrist)."""
        if i == len(blockers):
            return finish(cur, moves)
        cargo = blockers[i]
        occupied = set(cur.values()) - {cur[cargo]}  # it does not hold itself up
        options = sorted((t for t in temp_spots(layout, occupied, set(avoid), plan_sites) if stack_key(layout, t) != key),
                         key=lambda t: zone(layout, t) != zone(layout, cur[cargo]))
        for t in options[:REORDER_WIDTH] if reorder else options:  # shortcut: a reorder tries the first places only (three levels of every place took >10 min on the validator), widen if a plan Harbor would find is missed
            m = step(cur, cargo, t, "재취급")
            if m is not None and (found := search(i + 1, {**cur, cargo: t}, moves + [m])):
                return found
        failures.append("NO_TEMPORARY_SPACE_IN_REACH")
        return None

    moves = search(0, dict(state), [])
    return (moves, None) if moves else (None, failures[0] if failures else "NO_LEGAL_PLAN")


def temp_spots(layout, occupied, avoid=frozenset(), names=None):
    """Temporary places in Harbor's order: the free temporary lane tiers on something (bottom tier first), then free ship sites standing
    on an occupied one (another 장치 칸). `names` reuses a caller's planning_sites(list)."""
    used = occupied | avoid
    names = planning_sites(layout) if names is None else names
    spots = [s for s in names for v in [layout.sites[s]] if v["kind"] in ("temp", "ship") and s not in used
             and (v["layer"] == 0 or layout.stack_at.get((v["stack"], v["layer"] - 1)) in occupied)]
    return sorted(spots, key=lambda s: (layout.sites[s]["kind"] != "temp", layout.sites[s]["layer"], s))


def resolve_order(job, layout, state, request, can, avoid=(), *, suggester=None):
    """Use Harbor's exact permutation or compute a ROSY R order; suggestions are shadow only."""
    proposed = job.get("harbor_order")
    requested = job.get("requested_moves")
    if proposed is not None:
        if not isinstance(proposed, list) or not isinstance(requested, list) or not requested:
            raise ValueError("Harbor order requires requested_moves")
        identity = lambda m: (m["cargo_id"], m["source"], m["destination"])
        try:
            if Counter(map(identity, proposed)) != Counter(map(identity, requested)):
                raise ValueError("Harbor order must cover exactly the requested moves")
        except (KeyError, TypeError) as exc:
            raise ValueError("invalid Harbor move") from exc
        current = dict(state)
        for move in proposed:
            cargo, src, dst = identity(move)
            if (current.get(cargo) != src or dst not in layout.sites or dst in current.values()
                    or not set(move.get("arms", ())) <= set(can(src, dst, {c: s for c, s in current.items() if c != cargo}))
                    or not move.get("arms")):
                raise ValueError("Harbor order is not executable from the observed state")
            current[cargo] = dst
        moves, source = proposed, "harbor"
    else:
        moves, why = harbor_moves(layout, state, request, can, avoid)
        if moves is None:
            return None, why
        source = "rosy_r"
    if suggester is not None:
        try:
            rule, _ = harbor_moves(layout, state, request, can, avoid)
            _LOG.info("OMX order shadow agreement=%s source=%s", suggester(request, state) == rule, source)
        except Exception:
            _LOG.exception("OMX order shadow unavailable")
    return {"moves": moves, "order_source": source}, None
