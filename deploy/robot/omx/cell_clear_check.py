#!/usr/bin/env python3
"""Look before clearing an arm incident: the cell's own cameras and the AI PC's vision model, never the arm.

An arm held by an incident is cleared by a named operator with a note of what was checked (omx_incident clear). When no
one stands at the arm, this reads the arm's cell views from the site viewer and asks the situation model (judge_seat's
ollama backend) whether anything rests on the arm, wedges its shoulder or pulls a cable. The model only reports what a
picture shows; it cannot feel joint friction or a jammed gear, and a "parked" answer is not trusted (it does not know
the home pose: joint readback decides that). The result is a record plus a note text that names its basis honestly, for
the operator to pass to `omx_incident.py clear --note`; this tool clears nothing and moves nothing.

  cell_clear_check.py --arm arm_b [--viewer http://127.0.0.1:8767] [--model-url http://<ai-pc>:11434] [--out check.json]
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge_seat  # noqa: E402

SCHEMA = "rosy.omx-clear-check.v1"
VIEWS = {"arm_a": ("top", "side"), "arm_b": ("top", "side"), "arm_s": ("arm_s_top",)}  # cell S has no side camera
WHERE = {"arm_a": "the LEFT arm (arm_a)", "arm_b": "the RIGHT arm (arm_b)", "arm_s": "the single arm (arm_s) on the yellow plate"}
ANSWER = {"type": "object", "required": ["obstruction", "cable", "evidence"], "properties": {
    "obstruction": {"type": "string"}, "cable": {"enum": ["slack", "taut", "caught", "unclear"]}, "evidence": {"type": "string"}}}


def ask_views(arm: str, frames: dict, ask) -> dict:
    """One answer per view: what, if anything, touches or holds the arm near its shoulder or base."""
    prompt = (f"Robot cell camera view. Look only at {WHERE[arm]}. Is any object (container, cable, tool, part) touching, "
              "wedged against or resting on that arm near its shoulder or base, or anything that would stop its shoulder from "
              "lifting? Is any of its cables taut or caught? Answer JSON: obstruction ('none' or a short description), "
              "cable (slack/taut/caught/unclear), evidence (short).")
    return {view: ask(prompt, [base64.b64encode(img).decode()], ANSWER) for view, img in frames.items()}


def verdict(answers: dict) -> dict:
    """camera_clear only when every view says no obstruction and a slack cable; anything else needs a person."""
    worries = [f"{view}: {a.get('obstruction')} / cable {a.get('cable')}" for view, a in answers.items()
               if str(a.get("obstruction", "")).strip().lower() not in ("none", "no", "") or a.get("cable") != "slack"]
    return {"camera_clear": not worries and bool(answers), "worries": worries}


def note(arm: str, result: dict) -> str:
    views = ", ".join(result["answers"])
    if not result["verdict"]["camera_clear"]:
        return ""
    return (f"{arm}: checked by camera ({views}) and the AI PC vision model, no object on or wedged at the arm, cables slack; "
            "not a hand check: joint friction and gear state were not checked")


def check(arm: str, fetch, ask, now=time.time) -> dict:
    frames = {view: fetch(view) for view in VIEWS[arm]}
    answers = ask_views(arm, frames, ask)
    result = {"schema": SCHEMA, "arm": arm, "t": round(now(), 3), "model": getattr(ask, "__name__", "?"),
              "answers": answers, "verdict": verdict(answers)}
    result["note"] = note(arm, result)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True, choices=sorted(VIEWS))
    ap.add_argument("--viewer", default="http://127.0.0.1:8767")
    ap.add_argument("--model-url", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="qwen3-vl:8b-instruct")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    def fetch(view):
        with urllib.request.urlopen(f"{args.viewer}/frame/{view}.jpg", timeout=10) as reply:
            return reply.read()

    result = check(args.arm, fetch, judge_seat.ollama(args.model_url, args.model, timeout=300))
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["verdict"]["camera_clear"] else 2


if __name__ == "__main__":
    sys.exit(main())
