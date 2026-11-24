"""Offline read-only replay of saved `pivot-frames/<site>-<ts>/` captures (split from `cell_jaw_side.py`)."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402


def _replay_yaw_tries(ydir: Path, config: dict, jaws: dict | None, near, params):
    import cv2
    import cell_jaw_side as cjs
    import cell_pivot

    mark_cfg = config.get("jaw_mark") or {}
    follow, agree = prm.get(params, "pivot.follow_px", cell_pivot.FOLLOW_PX), prm.get(params, "pivot.agree_px", cell_pivot.AGREE_PX)
    files = sorted(((int(m.group(1)), f) for f in ydir.iterdir() if (m := re.fullmatch(r"try-(\d+)-closed\.jpg", f.name))), key=lambda t: t[0])
    if not files:
        return None, None, "no saved tries", None
    pairs = [(cv2.imread(str(cp)), cv2.imread(str(ydir / f"try-{i:02d}-open.jpg"))) for i, cp in files]
    if any(c is None or o is None for c, o in pairs):
        raise SystemExit(f"replay_pivot: missing or unreadable try pair in {ydir}")
    exp = mark_cfg.get("colour")
    det = (lambda c, o, pr, colour: cjs.marks(c, o, pr, colour=colour, jaws=jaws)) if jaws is not None else (
        cell_pivot.jaw_centres if mark_cfg.get("centre") else cell_pivot.jaw_blobs)
    tried, sides, saw = [], [], False
    for c_img, o_img in pairs:
        blobs = det(c_img, o_img, params, colour=bool(exp)) if exp is not None else (
            det(c_img, o_img, params, colour=False) or det(c_img, o_img, params, colour=True))
        saw |= bool(blobs)
        pick = (min((b for b in blobs if math.dist(b[:2], tried[-1]) <= follow), key=lambda b: math.dist(b[:2], tried[-1]), default=None) if tried
                else min((b for b in blobs if min(math.dist(b[:2], q) for q in near[0]) <= near[1]), key=lambda b: min(math.dist(b[:2], q) for q in near[0]), default=None) if near is not None
                else max(blobs, key=lambda b: b[2], default=None)) if blobs else None
        if pick is None:
            continue
        side = pick[3] if len(pick) > 3 else None
        close = [s for m, s in zip(tried, sides) if math.dist(pick[:2], m) <= agree]
        if close and not all(s == side for s in close):
            u = cell_pivot.jaw_blobs(pairs[0][0], pairs[0][1], params, colour=bool(exp))
            return None, None, "jaw sides switched between tries", [[round(float(v), 1) for v in b[:3]] for b in u]
        if close:
            return (pick[0], pick[1]), side, None, None
        tried.append(pick[:2])
        sides.append(side)
    u = cell_pivot.jaw_blobs(pairs[0][0], pairs[0][1], params, colour=bool(exp)) or (
        [] if exp is not None else cell_pivot.jaw_blobs(pairs[0][0], pairs[0][1], params, colour=True))
    why = "tries disagree" if tried else ("blobs outside near" if saw else "no changed blob")
    return None, None, why, [[round(float(v), 1) for v in b[:3]] for b in u]


def replay_pivot(frames_dir: Path, config: dict, calibration: dict, site: str | None = None) -> dict:
    """Offline read-only replay of a saved `pivot-frames/<site>-<ts>/` dir under current `config`/`calibration`."""
    import cv2
    import cell_jaw_side as cjs
    import cell_pivot

    root, p = Path(frames_dir), config.get("params")
    if not root.is_dir():
        raise SystemExit(f"replay_pivot: missing directory {root}")
    if site is None:
        m = re.match(r"^(.+)-\d{8}-\d{6}-\d{6}$", root.name)
        if not m:
            raise SystemExit(f"replay_pivot: cannot infer site from {root.name}")
        site = m.group(1)
    if (record := cell_pivot.map_record(calibration, site)) is None:
        raise SystemExit(f"replay_pivot: no map for site {site!r}")
    if not (yaw_dirs := sorted((d for d in root.iterdir() if d.is_dir() and d.name.isdigit()), key=lambda d: int(d.name))):
        raise SystemExit(f"replay_pivot: no yaw directories in {root}")
    top = (config.get("cameras") or {}).get("top") or {}
    arm_marks, tcps, hows, diag = [], [], [], []
    for ydir in yaw_dirs:
        try:
            info = json.loads((ydir / "jaws.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"replay_pivot: invalid {ydir / 'jaws.json'}: {exc}") from exc
        fk = info.get("fk") if isinstance(info, dict) else None
        if not fk or len(fk) < 4:
            diag.append({"dir": ydir.name, "skipped": "no_fk"}); continue
        try:
            places = cjs.jaw_places(record, config, site, fk[:2], fk[3], fk[2])
        except cjs._PLACE_ERRORS:
            places = None
        band = None
        if places is not None and prm.get(p, "jaw_side.depth_band"):
            raw_p, col_img = ydir / "depth.raw", cv2.imread(str(ydir / "depth-colour.jpg")) if (ydir / "depth-colour.jpg").is_file() else None
            if not raw_p.is_file() or col_img is None or top.get("height_m") is None:
                raise SystemExit(f"replay_pivot: jaw_side.depth_band enabled but depth artifacts missing in {ydir}")
            heights, tbl = cjs.heights_in_colour(np.frombuffer(raw_p.read_bytes(), np.uint16).reshape(col_img.shape[:2]), col_img)
            band = cjs.height_band(heights, tbl - 1000 * (float(top["height_m"]) - float(fk[2])), p)
        jaws = None if places is None else {"places": places, "radius_px": prm.get(p, "jaw_side.roi_px"), "band": band,
                                            "to": "middle" if (config.get("jaw_mark") or {}).get("centre") else "reference"}
        near = cjs.near_tcp(record, config, site, fk[:2], fk[2], prm.get(p, "pivot.follow_px", cell_pivot.FOLLOW_PX) + 40)
        pixel, side, why, unmasked = _replay_yaw_tries(ydir, config, jaws, near, p)
        how = {"side": side if pixel is not None else None, "path": "old" if jaws is None else "band" if band is not None else "discs"}
        diag.append({"dir": ydir.name, "fk_yaw_deg": round(float(fk[3]), 1), "mark_px": [round(float(v), 1) for v in pixel] if pixel else None,
                     "reason": why, **how, **({"unmasked_blobs": unmasked} if unmasked is not None else {})})
        if pixel is not None:
            arm_marks.append(cell_pivot.mark_to_arm(record, config, site, pixel, fk[2]))
            tcps.append(tuple(float(v) for v in fk[:4])); hows.append(how)
    why_rel, geometry = cjs.relabel(arm_marks, tcps, hows, config, frames=None), (config.get("pivot") or {}).get("geometry")
    arc = cell_pivot._yaw_arc_deg([t[3] for t in tcps])
    free_fit = cell_pivot.fit_pivot_yaw(arm_marks, [t[3] for t in tcps], mark_sigma_mm=float(prm.get(p, "verify.mark_sigma_mm"))) if len(arm_marks) >= 4 and arc >= cell_pivot.MIN_YAW_ARC_DEG else None
    if why_rel:
        out = {"result": why_rel}
    elif geometry is not None:
        out = cell_pivot.known_geometry_bias(arm_marks, tcps, geometry, site, record, p, hows, config.get("arm_id"))
    elif len(arm_marks) < 4:
        out = {"result": f"jaws marked at {len(arm_marks)} yaws, need 4"}
    elif arc < cell_pivot.MIN_YAW_ARC_DEG:
        out = {"result": f"circle refused: yaw arc {round(arc, 1)} deg < {int(cell_pivot.MIN_YAW_ARC_DEG)} deg"}
    elif free_fit["result"] != "fitted":
        out = {"result": f"circle refused: {free_fit['why']}"}
    elif (kept_arc := cell_pivot._yaw_arc_deg([tcps[i][3] for i in free_fit["kept_indices"]])) < cell_pivot.MIN_YAW_ARC_DEG:
        out = {"result": f"circle refused: yaw arc {round(kept_arc, 1)} deg < {int(cell_pivot.MIN_YAW_ARC_DEG)} deg"}
    else:
        k_tcps = [tcps[i] for i in free_fit["kept_indices"]]
        cx, cy = free_fit["centre_m"]; tx, ty = (float(np.mean([t[i] for t in k_tcps])) for i in (0, 1))
        why_s, sides = cjs.side_check(arm_marks, tcps, hows, k_tcps, free_fit["radius_mm"], free_fit["phase_deg"], p, config.get("arm_id"))
        bias = {"site": site, "kind": "pivot", **({"jaw_sides": sides} if sides else {}), "point_m": [round(tx, 4), round(ty, 4)],
                "bias_mm": [round(1000 * (cx - tx), 1), round(1000 * (cy - ty), 1)], "radius_mm": free_fit["radius_mm"], "phase_deg": free_fit["phase_deg"],
                "z_view": cell_pivot.pivot_z_view(config, site), "rms_mm": free_fit["rms_mm"], "n": len(k_tcps), "yaws_fk_deg": [round(t[3], 1) for t in k_tcps]}
        if free_fit["rms_m"] * 1000 > prm.get(p, "pivot.max_rms_mm") or not (prm.get(p, "pivot.radius_lo_mm") <= free_fit["radius_m"] * 1000 <= prm.get(p, "pivot.radius_hi_mm")):
            out = {"result": f"circle refused: radius {bias['radius_mm']} mm, rms {bias['rms_mm']} mm", "bias": bias}
        else:
            out = {"result": why_s or "calibrated", "bias": bias}
    return {**out, "site": site, "yaws": diag, **({"free_fit": free_fit} if free_fit is not None else {})}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Offline read-only replay of a saved pivot-frames directory.")
    ap.add_argument("--config", required=True, type=Path); ap.add_argument("--site"); ap.add_argument("frames_dir", type=Path)
    a = ap.parse_args(argv); cfg = json.loads(a.config.read_text(encoding="utf-8")); cfg["params"] = prm.load(cfg.get("params_path"))["values"]
    res = replay_pivot(a.frames_dir, cfg, json.loads(Path(cfg["calibration_path"]).expanduser().read_text(encoding="utf-8")), site=a.site)
    print(json.dumps(res, default=str), flush=True); raise SystemExit(0 if res.get("result") == "calibrated" else 2)


if __name__ == "__main__":
    main()
