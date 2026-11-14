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
SCENE = {"type": "object", "required": ["misplaced", "occupied_spots", "arm_leaning", "evidence"], "properties": {
    "misplaced": {"type": "string"}, "occupied_spots": {"type": "string"}, "arm_leaning": {"type": "string"}, "evidence": {"type": "string"}}}
ANSWER = {"type": "object", "required": ["obstruction", "cable", "evidence"], "properties": {
    "obstruction": {"type": "string"}, "cable": {"enum": ["slack", "taut", "caught", "unclear"]}, "evidence": {"type": "string"}}}


def ask_views(arm: str, frames: dict, ask) -> dict:
    """One answer per view: what, if anything, touches or holds the arm near its shoulder or base."""
    prompt = (f"Robot cell camera view. Look only at {WHERE[arm]}. Is any object (container, cable, tool, part) touching, "
              "wedged against or resting on that arm near its shoulder or base, or anything that would stop its shoulder from "
              "lifting? Is any of its cables taut or caught? Answer JSON: obstruction ('none' or a short description), "
              "cable (slack/taut/caught/unclear), evidence (short).")
    return {view: ask(prompt, [base64.b64encode(img).decode()], ANSWER) for view, img in frames.items()}


def ask_scene(arm: str, image: bytes, ask) -> dict:
    """The whole-cell view (a bird view): what sits out of place, what is occupied, and whether the arm leans on anything."""
    prompt = (f"Bird view of a robot cell. Focus on {WHERE[arm]} and the places it works (lanes, pallets, belt). Is any container "
              "not seated in its lane or slot (diagonal, across a line, half off)? Which pick or place spots are occupied? Is the arm "
              "resting or leaning on a container, plate or edge? Answer JSON: misplaced ('none' or which), occupied_spots (short), "
              "arm_leaning ('none' or what), evidence (short).")
    return ask(prompt, [base64.b64encode(image).decode()], SCENE)


def _none(text) -> bool:
    return str(text or "").strip().lower() in ("none", "no", "")


def verdict(answers: dict, scene: dict | None = None) -> dict:
    """camera_clear only when every view says no obstruction and a slack cable, and the scene shows nothing out of place or
    leaned on; anything else needs a person. Occupied spots are reported, not judged: placement measurement owns occupancy."""
    worries = [f"{view}: {a.get('obstruction')} / cable {a.get('cable')}" for view, a in answers.items()
               if not _none(a.get("obstruction")) or a.get("cable") != "slack"]
    if scene is not None:
        worries += [f"scene: {key} {scene.get(key)}" for key in ("misplaced", "arm_leaning") if not _none(scene.get(key))]
    return {"camera_clear": not worries and bool(answers), "worries": worries}


def note(arm: str, result: dict) -> str:
    views = ", ".join(result["answers"])
    if not result["verdict"]["camera_clear"]:
        return ""
    return (f"{arm}: checked by camera ({views}) and the AI PC vision model, no object on or wedged at the arm, cables slack; "
            "not a hand check: joint friction and gear state were not checked")


def check(arm: str, fetch, ask, now=time.time, scene_image: bytes | None = None) -> dict:
    frames = {view: fetch(view) for view in VIEWS[arm]}
    answers = ask_views(arm, frames, ask)
    scene = ask_scene(arm, scene_image, ask) if scene_image is not None else None
    result = {"schema": SCHEMA, "arm": arm, "t": round(now(), 3), "model": getattr(ask, "__name__", "?"),
              "answers": answers, "scene": scene, "verdict": verdict(answers, scene)}
    result["note"] = note(arm, result)
    return result


def fleet_frame(fleet: str, token: str, source: str) -> bytes:
    """One frame of a Fleet vision source through a 60 s preview lease (the only way Fleet hands out frames)."""
    import ssl
    ctx = ssl._create_unverified_context()  # shortcut: the cell's local Fleet uses a site certificate; verify it once the CA is on the cell
    request = urllib.request.Request(f"{fleet}/api/fleet/vision/lease", json.dumps({"source_id": source}).encode(),
                                     {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, context=ctx, timeout=10) as reply:
        lease = json.loads(reply.read())
    request = urllib.request.Request(fleet + lease["frame_path"], headers={"Authorization": f"Bearer {lease['lease']}"})
    with urllib.request.urlopen(request, context=ctx, timeout=15) as reply:
        return reply.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True, choices=sorted(VIEWS))
    ap.add_argument("--viewer", default="http://127.0.0.1:8767")
    ap.add_argument("--model-url", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="qwen3-vl:8b-instruct")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--fleet", help="Fleet base URL for the bird view, e.g. https://127.0.0.1:8543")
    ap.add_argument("--token-file", type=Path, help="operator bearer for --fleet")
    ap.add_argument("--scene-source", default="omx_overhead", help="Fleet vision source of the whole-cell view")
    args = ap.parse_args(argv)

    def fetch(view):
        # the site viewer answers only to its own Host name
        request = urllib.request.Request(f"{args.viewer}/frame/{view}.jpg", headers={"Host": "127.0.0.1:8767"})
        with urllib.request.urlopen(request, timeout=10) as reply:
            return reply.read()

    scene = fleet_frame(args.fleet, args.token_file.read_text().strip(), args.scene_source) if args.fleet else None
    result = check(args.arm, fetch, judge_seat.ollama(args.model_url, args.model, timeout=300), scene_image=scene)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["verdict"]["camera_clear"] else 2


if __name__ == "__main__":
    sys.exit(main())
