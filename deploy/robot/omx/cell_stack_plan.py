"""Pure goal-driven stacking plan: from any observed state to goal stacks, serial moves, same move shape as cell_move_order."""

from cell_move_order import HARBOR_ARMS, planning_sites, stack_key, temp_spots

PARK_WIDTH = 4  # temp places tried per blocker before backing up
NODE_BUDGET = 20000
_LETTER = {name: letter for letter, name in HARBOR_ARMS.items()}


def plan_to_goal(layout, state, goal, can, avoid=()):
    """Return (moves, None) or (None, hold reason). `state` is {cargo: tier site}, `goal` is {stack key: [cargo l0, l1, l2]} (a shorter
    list leaves the upper tiers alone). Each goal cargo is placed bottom-up; whatever sits in the way is parked top first on a temp place
    that is neither a goal stack nor in `avoid`, and comes back when its own turn arrives. Reasons: UNKNOWN_SITE, UNKNOWN_CARGO,
    NO_BUFFER (no temp place), UNREACHABLE (no arm), NO_LEGAL_PLAN (search budget spent)."""
    tiers = {}
    for key, _ in layout.stack_at:
        tiers[key] = tiers.get(key, 0) + 1
    if any(s not in layout.sites for s in state.values()) or any(k not in tiers or len(g) > tiers[k] for k, g in goal.items()):
        return None, "UNKNOWN_SITE"
    order = [(c, layout.stack_at[(k, t)]) for k, g in goal.items() for t, c in enumerate(g)]
    if any(c not in state for c, _ in order):
        return None, "UNKNOWN_CARGO"
    goal_keys, names = set(goal), planning_sites(layout)
    failures, nodes = [], [0]

    def layer(site):
        return layout.sites[site].get("layer", 0)

    def above(cur, site):
        key = stack_key(layout, site)
        return [c for c, s in cur.items() if key in tiers and stack_key(layout, s) == key and layer(s) > layer(site)]

    def blockers(cur, cargo, dst):
        """Everything that must leave before `cargo` can be lifted and `dst` filled, top first."""
        key, base = stack_key(layout, dst), layer(dst)
        found = set(above(cur, cur[cargo])) | {c for c, s in cur.items() if stack_key(layout, s) == key and layer(s) >= base}
        return sorted(found, key=lambda c: -layer(cur[c]))

    def free_tiers(cur, site):
        key = stack_key(layout, site)
        return tiers[key] - sum(stack_key(layout, s) == key for s in cur.values())

    def step(cur, moves, cargo, dst, phase):
        src, here = cur[cargo], {c: s for c, s in cur.items() if c != cargo}
        arms = sorted(can(src, dst, here))
        if not arms:
            failures.append("UNREACHABLE")
            return None
        if moves and moves[-1]["arms"][0] in arms:  # one arm at a time: keep the previous one when it can
            arms.insert(0, arms.pop(arms.index(moves[-1]["arms"][0])))
        return dict(cargo_id=cargo, source=src, destination=dst, primary_arm=_LETTER.get(arms[0]),
                    alternate_arms=[_LETTER.get(a) for a in arms[1:]], phase_label=phase, arms=arms)

    def go(cur, moves, idx):
        nodes[0] += 1
        if nodes[0] > NODE_BUDGET:
            return None
        if idx == len(order):
            return moves
        cargo, dst = order[idx]
        if cur[cargo] == dst:
            return go(cur, moves, idx + 1)
        rem = blockers(cur, cargo, dst)
        if rem:
            c = rem[0]
            spots = temp_spots(layout, set(cur.values()) - {cur[c]}, set(avoid), names)
            spots = [t for t in spots if stack_key(layout, t) not in goal_keys]
            if not spots:
                failures.append("NO_BUFFER")
            spots.sort(key=lambda t: (layout.sites[t]["kind"] != "temp", layer(t), -free_tiers(cur, t)))  # stable: ties keep name order
            for t in spots[:PARK_WIDTH]:
                m = step(cur, moves, c, t, "재취급")
                if m is not None and (done := go({**cur, c: t}, moves + [m], idx)) is not None:
                    return done
            return None
        if layer(dst) and layout.stack_at[(stack_key(layout, dst), layer(dst) - 1)] not in cur.values():
            failures.append("NO_SUPPORT")
            return None
        m = step(cur, moves, cargo, dst, "장치")
        return None if m is None else go({**cur, cargo: dst}, moves + [m], idx + 1)

    moves = go(dict(state), [], 0)
    return (moves, None) if moves is not None else (None, failures[0] if failures else "NO_LEGAL_PLAN")
