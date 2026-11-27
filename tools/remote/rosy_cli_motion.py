"""rosy CLI: typed cell-task motions (free-position pick, push). Split from rosy_cli (600-line rule). Stdlib only.

Pixels from a frame, never metres; the server derives the sites. frame_seq/frame_sha256 are an audit record of the chosen frame only:
the cell re-measures at run time (D-1081).
"""
from __future__ import annotations

import argparse
from typing import Any

import rosy_agent_bridge as br

FRAME_HELP = "audit record of the chosen frame only; the cell re-measures at run time"


def _pair(text: str | None, *, sep=int) -> list | None:
    try:
        pair = [sep(x) for x in str(text).split(",")]
    except ValueError:
        pair = []
    return pair if len(pair) == 2 else None


def _motion_frame(args: argparse.Namespace) -> dict[str, Any]:
    return {"frame_seq": args.frame_seq, "frame_sha256": args.frame_sha256}


def _motion_error(detail: str) -> dict[str, Any]:
    return {"ok": False, "status": 400, "error_code": "INVALID_ARGS", "detail": detail}


def free_pick_motion(args: argparse.Namespace) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """-> (motion, None) or (None, error) for `rosy pick --free-anchor`."""
    at_px = _pair(args.at_px)
    if at_px is None or not args.dst or args.frame_seq is None or not args.frame_sha256 or args.src or args.preset or args.tiers:
        return None, _motion_error("--free-anchor needs --at-px U,V --dst SITE --frame-seq N --frame-sha256 SHA from 'rosy frame', and no --src/--preset/--tiers")
    return {"kind": "free_pick", "anchor_site": args.free_anchor, "at_px": at_px, "dst_site": args.dst,
            **_motion_frame(args), **{k: v for k, v in (("object", args.object), ("colour", args.colour)) if v}}, None


def cmd_push(bridge: br.RosyAgentBridge, args: argparse.Namespace) -> dict[str, Any]:
    """A push is always a proposal: a named human approves it in the Fleet console."""
    px, direction = _pair(args.px), _pair(args.dir, sep=float)
    if px is None or direction is None or args.frame_seq is None or not args.frame_sha256:
        return _motion_error("--site, --px U,V, --dir DX,DY, --mm, --frame-seq and --frame-sha256 are required")
    payload: dict[str, Any] = {"cell_id": args.cell, "motion": {"kind": "push", "site": args.site, "px": px, "dir": direction,
                                                              "mm": args.mm, **_motion_frame(args)}}
    if args.arm:
        payload["arm_id"] = args.arm
    if args.request_key:
        payload["request_key"] = args.request_key
    if args.dry_run:
        if err := br._validate_args(br.TOOL_MAP["fleet_propose_cell_task"], payload):
            return _motion_error(err)
        return {"ok": True, "dry_run": True, "tool": "fleet_propose_cell_task", "payload": payload}
    res = bridge.call_tool("fleet_propose_cell_task", payload)
    return {**res, "needs_approval": True} if res.get("ok") else res


def add_pick_args(p_pick: argparse.ArgumentParser) -> None:
    p_pick.add_argument("--free-anchor", default=None, help="pick at a pixel on this site (free position), not at a fixed slot")
    p_pick.add_argument("--at-px", default=None)
    p_pick.add_argument("--frame-seq", type=int, default=None)
    p_pick.add_argument("--frame-sha256", default=None, help=FRAME_HELP)
    p_pick.add_argument("--object", default=None)
    p_pick.add_argument("--colour", default=None)


def add_push_parser(sub) -> None:
    p_push = sub.add_parser("push")
    p_push.add_argument("--cell", choices=["cell_s", "cell_ab"], default="cell_ab")
    p_push.add_argument("--arm", default=None)
    p_push.add_argument("--site", required=True)
    p_push.add_argument("--px", required=True)
    p_push.add_argument("--dir", required=True, help="DX,DY; write a leading minus as --dir=-1,0")
    p_push.add_argument("--mm", type=float, required=True)
    p_push.add_argument("--frame-seq", type=int, default=None)
    p_push.add_argument("--frame-sha256", default=None, help=FRAME_HELP)
    p_push.add_argument("--request-key", default=None)
    p_push.add_argument("--dry-run", action="store_true")
