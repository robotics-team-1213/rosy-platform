"""ONE place that maps the cell's refusal sentences to a code, the measured numbers and the allowed suggestions.

The sentences come from cell_auto_pick_plan.py, cell_place_fit.py (tier_mismatch), cell_object_pose.py and the job
checks (2026-11-27 dry runs). An unknown sentence is UNCLASSIFIED with only ask_human: fail closed, never guessed.
Suggestions are the only verbs a model may follow for that candidate: pick, retier(<site>-lN), push, free_pick, ask_human.
"""
from __future__ import annotations

import re
from typing import Any

_NUM = r"(-?\d+(?:\.\d+)?)"
# (code, regex, suggestions); the first match wins. {use} is filled from a named group of the sentence.
_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("EDGE_OF_VIEW", rf"^edge of view: .*?{_NUM} / {_NUM} mm free beside it", ("ask_human",)),
    ("NEIGHBOUR_CLEARANCE", rf"^neighbour clearance: {_NUM} / {_NUM} mm free beside it", ("push", "ask_human")),
    ("NEIGHBOUR_CLEARANCE", r"^neighbour clearance on either closing axis", ("push", "ask_human")),
    ("TANGLED_BLOB", r"^tangled blob", ("push", "ask_human")),
    ("NO_CATALOGUE_MATCH", r"^no catalogue match", ("push", "ask_human")),
    ("WRONG_OBJECT", r"^wanted object (?P<wanted>\S+), got (?P<got>\S+)", ("ask_human",)),
    ("TIER_MISMATCH", r"^tier mismatch: layers_below=(?P<hint>\d+) on base site (?P<site>\S+) plans at plate height; use source (?P<use>\S+)", ("retier",)),
    ("LIGHT_TOP", rf"^light top: mean {_NUM} < {_NUM}", ()),
    ("CAMERA_MOVED", r"^held: top camera moved since map reference", ()),
    ("NO_OBJECT", r"^(stopped: )?no usable object", ("ask_human",)),
    ("UNREACHABLE", r"^ik_unreachable", ("ask_human",)),
    ("PATH_NOT_CLEAR", r"^refused: path not clear", ("ask_human",)),
    ("API_REJECTED", r"^(catalog|config|source|roi|dest): |^unknown params|^missing param", ("ask_human",)),
)
#: codes after which no camera observation is possible: the pack becomes observable=false
UNOBSERVABLE_CODES = frozenset({"LIGHT_TOP", "CAMERA_MOVED"})


def classify(why: str | None) -> dict[str, Any]:
    """{code, numbers, suggestions, why} for one refusal sentence."""
    text = (why or "").strip()
    for code, rx, sugg in _RULES:
        m = re.match(rx, text)
        if not m:
            continue
        nums: dict[str, Any] = {}
        groups, named = m.groups(), m.groupdict()
        if code in ("NEIGHBOUR_CLEARANCE", "EDGE_OF_VIEW") and named == {} and len(groups) == 2:
            free = [float(g) for g in groups]
            nums = {"free_mm": free, "min_free_mm": min(free)}
        elif code == "LIGHT_TOP":
            nums = {"mean": float(groups[0]), "min": float(groups[1])}
        elif code == "WRONG_OBJECT":
            nums = {"wanted": named["wanted"].split(","), "got": named["got"]}
        elif code == "TIER_MISMATCH":
            nums = {"layers_below": int(named["hint"]), "site": named["site"], "use": named["use"]}
            sugg = (f"retier({named['use']})",)
        return {"code": code, "numbers": nums, "suggestions": list(sugg), "why": text}
    return {"code": "UNCLASSIFIED", "numbers": {}, "suggestions": ["ask_human"], "why": text}
