"""Pre-session refusal for dual ACT transfers without matching post-placement evidence."""
def transfer_refusal(tasks, *, dry_run):
    if dry_run:
        return None
    from cell_route_check import temp_to_ship

    verification = {}
    blocked = False
    for arm, task in tasks.items():
        source, dest = (v.strip() if isinstance(v, str) else v for v in (task["src"], task["dst"]))
        named = temp_to_ship(source, dest)
        blocked |= named
        verification["arm_" + arm] = {
            "source": source, "destination": dest, "verified": False,
            "reason": ("dual policy lacks source-clearance and post-release destination verification"
                       if named else "paired run did not start"),
        }
    if blocked:
        return {"result": "refused", "error_code": "UNVERIFIED_NAMED_TRANSFER",
                "motion_commands": 0, "verification": verification}
    return None
