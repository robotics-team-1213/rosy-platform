#!/usr/bin/env python3
"""Which container is this, from read tags only (D-996 3-4). No FIFO, no "the last one we saw", no guess.

A reading point (conveyor end: top camera on the roof tag, side camera on the side tag; then the A/B wrist at hover)
takes N frames. A tag counts as read only when one container-tag id is seen in at least k of them; two ids that both
reach k is a MISMATCH, not a choice. Roof and side may each be unreadable, but two read faces that disagree are a
MISMATCH. The read tag becomes an object_ref through the site profile's container_tags table in the cell
Fleet, which also compares it with the trip's declaration (intake_readings); this PC sends tag ids only.
Anything unreadable at every point is UNREADABLE and goes on only by a named person's attestation.

  cell_identity.py read FRAME.jpg [FRAME.jpg ...] [--k 3]     vote over frames of one face
  cell_identity.py end --top T.jpg ... --side S.jpg ... --out end.json [--queue]
                                                             conveyor-end reading, kept for the wrist gate
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

#: D-996 6: container tags are DICT_4X4_250 100-199; anything else in view (arm, ChArUco, Pinky) is not a vote
TAG_IDS = range(100, 200)
DEFAULT_N, DEFAULT_K = 5, 3


def vote(frames: list, k: int = DEFAULT_K) -> dict:
    """One face from N frames, each the set of marker ids seen. {"state": "read", "tag"} | "unreadable" | "mismatch"."""
    counts = Counter(i for seen in frames for i in set(seen) if i in TAG_IDS)
    winners = sorted(i for i, c in counts.items() if c >= k)
    if len(winners) > 1:
        return {"state": "mismatch", "tags": winners}
    if winners:
        return {"state": "read", "tag": winners[0], "votes": counts[winners[0]], "frames": len(frames)}
    return {"state": "unreadable", "frames": len(frames)}


def point(*faces: dict) -> dict:
    """One reading point from its faces' votes: one read face is enough, two that disagree are a mismatch."""
    if any(f["state"] == "mismatch" for f in faces):
        return {"state": "mismatch", "tags": sorted({t for f in faces for t in f.get("tags", [f.get("tag")]) if t})}
    tags = sorted({f["tag"] for f in faces if f["state"] == "read"})
    if len(tags) > 1:
        return {"state": "mismatch", "tags": tags}
    return {"state": "read", "tag": tags[0]} if tags else {"state": "unreadable"}


def place_gate(end: dict, wrist: dict) -> dict:
    """Before A/B picks the container off the conveyor end: {"place": True, "tag"} or {"place": False, "hold"}.
    The end and the wrist must not disagree; an unreadable wrist keeps the end's reading (the end is the reference
    point) and nothing read at either point holds for a person. The declared object_ref is compared by the cell Fleet
    (intake_readings), which alone holds the app's codes (D4)."""
    joined = point(end, wrist)
    if joined["state"] == "mismatch":
        return {"place": False, "hold": "MISMATCH", "tags": joined["tags"]}
    if joined["state"] == "unreadable":
        return {"place": False, "hold": "UNREADABLE"}
    return {"place": True, "tag": joined["tag"]}


def hook(config: dict, cell, queue_reading=None):
    """The hover hook (cell_hooks chain, before the descent): N wrist frames, the gate against the conveyor end's last
    reading (config identity.end_path), and the wrist reading queued for Fleet. None when config has no identity."""
    spec = config.get("identity")
    if not spec:
        return None

    def run():
        end_path = Path(spec["end_path"]).expanduser()
        end = json.loads(end_path.read_text(encoding="utf-8")) if end_path.exists() else {"state": "unreadable"}
        frames = [cell.frame(spec.get("camera", "wrist")) for _ in range(int(spec.get("frames", DEFAULT_N)))]
        wrist = read_frames(frames, int(spec.get("k", DEFAULT_K)))
        gate = place_gate(end, wrist)
        if queue_reading is not None:
            queue_reading("wrist", wrist, spec.get("arm_mission_id"))
        # a refusal parks before the descent (cell_transfer); the same mismatch again goes to a person (2 failures)
        return {"verdict": "pass" if gate["place"] else "refuse", "why": gate.get("hold"), "identity": gate}
    return run


def read_end(top_frames, side_frames, k: int = DEFAULT_K) -> dict:
    """The conveyor end's reading: the roof tag from the top camera, the side tag from the side camera."""
    return point(read_frames(top_frames, k), read_frames(side_frames, k))


def read_frames(images, k: int = DEFAULT_K) -> dict:
    """vote() over camera frames, through cell_marks.find (DICT_4X4_250)."""
    import cell_marks

    return vote([set(cell_marks.find(img)) for img in images], k)


def main(argv=None) -> int:
    import cv2

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("frames", nargs="+")
    r.add_argument("--k", type=int, default=DEFAULT_K)
    e = sub.add_parser("end")
    e.add_argument("--top", nargs="+", required=True)
    e.add_argument("--side", nargs="+", default=[])
    e.add_argument("--k", type=int, default=DEFAULT_K)
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--queue", action="store_true", help="also queue the reading for Fleet (port_event_outbox)")
    args = ap.parse_args(argv)
    if args.cmd == "read":
        print(json.dumps(read_frames([cv2.imread(f) for f in args.frames], args.k)))
        return 0
    end = read_end([cv2.imread(f) for f in args.top], [cv2.imread(f) for f in args.side], args.k)
    args.out.write_text(json.dumps(end), encoding="utf-8")
    if args.queue:
        import port_event_outbox as po

        po.queue(po.reading("conveyor_end", end))
    print(json.dumps(end))
    return 0


if __name__ == "__main__":
    sys.exit(main())
