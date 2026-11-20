"""The turn clock helpers of land_checks (moved to keep that file under its line cap; behaviour unchanged)."""
from __future__ import annotations

import json
import re
from pathlib import Path


def turn_wanted(land, wt: Path) -> bool:
    """Whether another landing is ready ('waiting') for the turn. The turn cap only applies then: on 2026-10-31 an
    urgent landing's turn hit the 10 min cap at 584 s with no one waiting and redid its pretest outside for an hour."""
    try:
        mine = {t.name for t in land.land_queue._held}
        rows = land.land_queue.ahead(land.land_queue.queue_dir(wt), Path("~"))
        return any(r.get("status") == "waiting" and r["ticket"] not in mine for r in rows)
    except Exception:  # noqa: BLE001 - an unreadable queue keeps the cap
        return True


def overtimes(land, args) -> int:
    """How often the turn cap sent this landing back: in this process, or before a relaunch on main's new landing
    code (the ticket keeps it; 11-01 13:26 the rest bundle relaunched and went back once more). True counts as 1."""
    counts = [int(getattr(args, "_overtime", 0) or 0)]
    for ticket in land.land_queue._held:
        try:
            counts.append(int(json.loads(ticket.read_text(encoding="utf-8")).get("overtime") or 0))
        except (OSError, ValueError, TypeError):
            pass
    return max(counts)


URGENT_FULL_TURN_S = 3 * 3600  # D-889 addendum 39: an urgent FULL in the turn (~85 min) keeps it, bounded


def _full_in_turn(args) -> bool:
    return getattr(args, "_full_in_turn", False) is True  # land_prepare.full_in_turn


def turn_budget(land, args) -> float:
    if _full_in_turn(args):
        return URGENT_FULL_TURN_S
    sent_back = overtimes(land, args)
    return land.TURN_MAX_S if sent_back >= 2 else min(land.TURN_MAX_S, land.TURN_CAP_S * (3 if sent_back else 1))


def turn_deadline(land, args, round_no, *, maximum: bool = False) -> float | None:
    budget = land.TURN_MAX_S if maximum and not _full_in_turn(args) else turn_budget(land, args)
    if not (isinstance(round_no, int) or re.fullmatch(r"g\d+r?", str(round_no))):
        return None
    started = land.land_queue.turn_started()
    return (land.time.monotonic() if started is None else started) + budget
