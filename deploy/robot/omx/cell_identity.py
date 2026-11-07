#!/usr/bin/env python3
"""Which container is this, from read tags only (D-996 3-4). No FIFO, no "the last one we saw", no guess.

A reading point (conveyor end: top camera on the roof tag, side camera on the side tag; then the A/B wrist at hover)
takes N frames. A tag counts as read only when one container-tag id is seen in at least k of them; two ids that both
reach k is a MISMATCH, not a choice. Roof and side may each be unreadable, but two read faces that disagree are a
MISMATCH. The read tag becomes an object_ref through the site profile's container_tags table (ROSY's, never the
app's), and must equal the object_ref the trip declared. Anything unreadable at every point is UNREADABLE and goes
on only by a named person's attestation.

  cell_identity.py read FRAME.jpg [FRAME.jpg ...] [--k 3]     vote over frames of one face
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

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


def identify(points: list, declared: str | None, tag_table: dict) -> dict:
    """The intake fact from every reading point so far (conveyor end first, wrist hover last).

    {"identity": "observed", "object_ref"} when the read tag maps to the declared object_ref;
    {"failed": "MISMATCH" | "UNREADABLE", "object_ref": declared} otherwise. Unreadable never becomes observed."""
    if any(p["state"] == "mismatch" for p in points):
        return {"failed": "MISMATCH", "object_ref": declared}
    tags = {p["tag"] for p in points if p["state"] == "read"}
    if not tags:
        return {"failed": "UNREADABLE", "object_ref": declared}
    if len(tags) > 1:  # the end and the wrist read different containers
        return {"failed": "MISMATCH", "object_ref": declared}
    read = tag_table.get(str(next(iter(tags))))
    if read is None or declared is None or read != declared:  # an unknown tag or no declaration is not a match
        return {"failed": "MISMATCH", "object_ref": declared}
    return {"identity": "observed", "object_ref": read}


def place_gate(end: dict, wrist: dict, declared: str | None, tag_table: dict) -> dict:
    """Before A/B lets go: {"place": True, "fact"} or {"place": False, "hold": reason, "fact"}. A mismatch at the
    wrist holds before the place; an unreadable wrist keeps the end's reading (the end is the reference point)."""
    fact = identify([end, wrist], declared, tag_table)
    if "failed" in fact:
        return {"place": False, "hold": fact["failed"], "fact": fact}
    return {"place": True, "fact": fact}


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
    args = ap.parse_args(argv)
    print(json.dumps(read_frames([cv2.imread(f) for f in args.frames], args.k)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
