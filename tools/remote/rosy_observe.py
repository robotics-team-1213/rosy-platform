"""Observation pack: one read-only call per arm that gives an LLM (or a rule) everything it may decide on.

fetch_raw() talks to the cell through the bridge's tool call (cell_frame, cell_dry_run, cell_readiness; nothing moves);
assemble() is pure (raw -> pack), so recorded cases replay offline (rosy_llm_eval). A dark, stale or missing camera, or a
dry run that says the top camera is dark or moved, gives observable=false with the reason and nothing else.
The model never sees metres to type: candidates carry the cell's measured numbers and a closed suggestion set.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any, Callable

try:
    from . import rosy_observe_refusals as ref
except ImportError:  # run as a script from tools/remote
    import rosy_observe_refusals as ref

SCHEMA = "rosy.omx-observation.v1"
SOURCES = json.loads(Path(__file__).with_name("rosy_observe_sources.json").read_text(encoding="utf-8"))
MAX_AGE_S = 2.0  # D-1057 MAX_FRAME_AGE_S
MAX_REPEAT = 5  # dry runs take the one shared camera slot: a caller may not hold it
MIN_LUMA = 15.0  # the cell's own "light top" threshold
SAME_MM, SAME_SPREAD_MM = 3.0, 2.0  # repeat runs: same blob / same clearance
Call = Callable[[str, dict], dict]
_PROBE_ARGS = {"config": "cell-probe-none.json", "catalog": "cell-probe-none.json", "roi": [0, 0, 1, 1], "source": "probe", "dest": "probe"}


def arm_cfg(arm: str) -> dict[str, Any]:
    if arm not in SOURCES["arms"]:
        raise ValueError(f"unknown arm {arm!r}")
    return SOURCES["arms"][arm]


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _luma(jpeg: bytes) -> tuple[float | None, list[int] | None]:
    try:
        from PIL import Image, ImageStat
        im = Image.open(io.BytesIO(jpeg))
        return round(ImageStat.Stat(im.convert("L")).mean[0], 1), list(im.size)
    except Exception:  # no decoder or a broken JPEG: the caller fails closed
        return None, None


def _err(res: dict[str, Any]) -> str:
    d = res.get("detail")
    return str((d.get("error") if isinstance(d, dict) else d) or res.get("error_code") or res.get("status"))[:300]


def _frame(call: Call, view: str, now: Callable[[], float]) -> tuple[dict[str, Any], bytes]:
    res = call("cell_frame", {"view": view})
    t = now()
    if not res.get("ok"):
        return {"ok": False, "error": _err(res), "fetched_at": t}, b""
    h = res.get("frame_headers") or {}
    jpeg = base64.b64decode(res.get("image_b64") or "")
    luma, size = _luma(jpeg)
    return {"ok": True, "frame_seq": _f(h.get("X-Frame-Seq")), "source_stamp": _f(h.get("X-Source-Stamp")),
            "sha256": res.get("sha256"), "luma": luma, "size": size, "fetched_at": t}, jpeg


def _dry(call: Call, cfg: dict[str, Any], site: dict[str, Any], sleep: Callable[[float], None], poll_s: float, layers_below: int | None = None) -> dict[str, Any]:
    body = {"config": cfg["config"], "catalog": cfg["catalog"], "roi": site["roi"], "source": site["site"], "dest": site["dest"],
            "object": cfg["object"], "neighbour_clear_mm": cfg["neighbour_clear_mm"]}
    if layers_below:
        body["layers_below"] = layers_below  # a stack hint: the cell answers a base site with "tier mismatch ... use <site>-lN"
    res = call("cell_dry_run", body)
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    waited = 0.0
    while res.get("ok") and data.get("running") and waited < poll_s:
        sleep(1.0)
        waited += 1.0
        res = call("job_status", {"job_id": data.get("id")})
        data = res.get("data") if isinstance(res.get("data"), dict) else {}
    if not res.get("ok"):
        return {"ok": False, "error": _err(res)}
    return {"ok": True, "structured_result": data.get("structured_result"), "error": None if data.get("structured_result") else "no structured_result"}


def _probe(call: Call, tool: str, extra: dict[str, Any]) -> dict[str, Any]:
    """A request the cell rejects while validating (no such config file), so no job starts either way."""
    res = call(tool, {**extra})
    return {"status": res.get("status"), "error_code": res.get("error_code"), "text": json.dumps(res.get("detail"), ensure_ascii=False)[:300].lower()}


def fetch_raw(call: Call, arm: str, *, repeat: int = 1, layers_below: int | None = None, now: Callable[[], float] = time.time,
              sleep: Callable[[float], None] = time.sleep, poll_s: float = 20.0) -> tuple[dict[str, Any], bytes]:
    """Raw cell answers for one arm plus the top JPEG (bytes, for the annotated picture)."""
    cfg = arm_cfg(arm)
    raw: dict[str, Any] = {"arm": arm, "fetched_at": now(), "frames": {}, "dry_runs": []}
    top = b""
    for v in cfg["views"]:
        raw["frames"][v], jpeg = _frame(call, v, now)
        top = jpeg if v == cfg["top_view"] else top
    for s in cfg["sites"]:
        raw["dry_runs"].append({"site": s["site"], "results": [_dry(call, cfg, s, sleep, poll_s, layers_below) for _ in range(min(max(1, repeat), MAX_REPEAT))]})
    r = call("cell_readiness", {})
    raw["readiness"] = r.get("data") if r.get("ok") else {"error": _err(r)}
    raw["probe"] = {"at_px": _probe(call, "cell_dry_run", {**_PROBE_ARGS, "at_px": "1,1"}),
                    "push": _probe(call, "cell_push_dry_run", {"arm": arm, "config": _PROBE_ARGS["config"], "site": "probe",
                                                               "roi": [0, 0, 1, 1], "px_x": 0, "px_y": 0, "dir_x": 1, "dir_y": 0, "mm": 5})}
    return raw, top


def _best(*texts: Any) -> dict[str, Any]:
    out = ref.classify(None)
    for t in texts:
        if not t:
            continue
        for cand in (str(t), str(t).split(": ", 1)[-1]):
            out = ref.classify(cand)
            if out["code"] != "UNCLASSIFIED":
                return out
    return out


def _parse_run(res: dict[str, Any], site: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = {"site": site["site"], "role": site["role"], "dest": site["dest"]}
    sr = res.get("structured_result")
    if not res.get("ok") or not isinstance(sr, dict):
        return {**base, "result": "error", **_best(res.get("error"))}, []
    result = sr.get("result")
    info = {**base, "result": result, "map_pose_check": sr.get("map_pose_check")}
    untrusted = site.get("trusted") is False
    att = (sr.get("attempts") or [{}])[0]
    cands: list[dict[str, Any]] = []
    ch, plan = att.get("chosen"), att.get("plan")
    if ch and plan:
        p, q = plan["pick"], plan.get("place") or {}
        cands.append({"object": ch.get("object"), "colour": ch.get("colour"), "centre_mm": [round(p["x"] * 1000, 1), round(p["y"] * 1000, 1)],
                      "place_mm": [round(q["x"] * 1000, 1), round(q["y"] * 1000, 1)] if q else None,
                      "status": "planned", "code": None, "numbers": {}, "why": None, "suggestions": ["pick"]})
    for r in att.get("refused") or []:
        cands.append({"object": r.get("object"), "colour": r.get("colour"), "centre_mm": r.get("centre_mm"),
                      "status": "refused", **ref.classify(r.get("why"))})
    for c in cands:
        c.update(site=site["site"], at_px=None, matched_id=c["object"], untrusted=untrusted)
    for c, r in zip(cands[1 if ch and plan else 0:], att.get("refused") or []):
        c["at_px"] = r.get("at_px") or r.get("centre_px")
    if result != "planned" or not cands:
        info["refusal"] = _best(sr.get("error"), result)
        if any(s.startswith("retier(") for s in info["refusal"]["suggestions"]):  # a run-level hint becomes a candidate to follow
            cands.append({"object": None, "colour": None, "centre_mm": None, "status": "refused", "site": site["site"], "at_px": None,
                          "matched_id": None, "untrusted": untrusted, **info["refusal"]})
    if site["role"] == "dest" or untrusted:  # after the retier candidate is added, so no hint survives here
        for c in cands:
            c["suggestions"] = [] if site["role"] == "dest" else ["ask_human"]  # a destination is observed for verification only
    return info, cands


def _stable(a: dict[str, Any], b: list[dict[str, Any]]) -> bool:
    for o in b:
        if o["code"] == a["code"] and all(abs(x - y) <= SAME_MM for x, y in zip(o["centre_mm"] or [0, 0], a["centre_mm"] or [0, 0])):
            fa, fb = a["numbers"].get("min_free_mm"), o["numbers"].get("min_free_mm")
            if fa is None or fb is None or abs(fa - fb) <= SAME_SPREAD_MM:
                return True
    return False


def _readiness(raw: dict[str, Any], arm: str, peer: str | None) -> dict[str, Any]:
    d = raw.get("readiness") or {}
    arms = d.get("arms") if isinstance(d, dict) else None
    if not isinstance(arms, dict) or arm not in arms:
        return {"ok": False, "error": (d or {}).get("error", "no readiness for this arm")}
    pick = lambda i: {k: i.get(k) for k in ("folded", "incident_held", "incident_reason", "human_hold_latched", "fault", "dirty", "active_job_id", "live_state_age_s")}  # noqa: E731
    return {"ok": True, **pick(arms[arm]), "allowed_tiers_now": d.get("allowed_tiers_now"), "blocking_refusals": d.get("blocking_refusals"),
            "peer": {"arm": peer, **pick(arms[peer])} if peer and isinstance(arms.get(peer), dict) else None}


def _live_verbs(raw: dict[str, Any], cfg: dict[str, Any], any_dry_ok: bool) -> dict[str, bool]:
    at_px, push = (raw.get("probe") or {}).get("at_px") or {}, (raw.get("probe") or {}).get("push") or {}
    # only the cell's own validation answer counts: a client-side INVALID_ARGS never reached the cell
    cell_400 = lambda p: p.get("status") == 400 and p.get("error_code") != "INVALID_ARGS" and "no such file" in str(p.get("text"))  # noqa: E731
    return {"pick": any_dry_ok, "free_pick": bool(cfg.get("free_pick", True)) and cell_400(at_px), "push": cell_400(push), "idle": True, "ask_human": True}


def assemble(raw: dict[str, Any], *, max_age_s: float = MAX_AGE_S) -> dict[str, Any]:
    max_age_s = min(max_age_s, MAX_AGE_S)  # a caller can tighten the freshness gate, never widen it
    arm = raw["arm"]
    cfg = arm_cfg(arm)
    frames: dict[str, Any] = {}
    reason, warnings = None, []
    for v in cfg["views"]:
        f = raw["frames"].get(v) or {"ok": False, "error": "not fetched"}
        if not f.get("ok"):
            reason = reason or f"CAMERA_MISSING:{v}"
            continue
        stamp = f.get("source_stamp")
        age = round(f["fetched_at"] - stamp, 2) if stamp is not None else None
        frames[v] = {k: f.get(k) for k in ("frame_seq", "source_stamp", "luma", "size")} | {"age_s": age}
        if age is None or age > max_age_s or age < -max_age_s:
            reason = reason or f"STALE_FRAME:{v}:{age}"
        elif f.get("luma") is None and v == cfg["top_view"]:
            reason = reason or f"FRAME_UNDECODABLE:{v}"
        elif f.get("luma") is not None and f["luma"] < MIN_LUMA:
            if v == cfg["top_view"]:
                reason = reason or f"DARK_FRAME:{v}:{float(f['luma'])}"
            else:
                warnings.append(f"dark {v}: mean {f['luma']}")
    top = raw["frames"].get(cfg["top_view"]) or {}
    observed_at = top.get("fetched_at") or raw.get("fetched_at") or 0.0
    runs: list[dict[str, Any]] = []
    cands: list[dict[str, Any]] = []
    for entry in raw.get("dry_runs") or []:
        site = next(s for s in cfg["sites"] if s["site"] == entry["site"])
        info, cs = _parse_run(entry["results"][0], site)
        for later in entry["results"][1:]:
            _, other = _parse_run(later, site)
            for c in cs:
                if not _stable(c, other):
                    c.update(unstable=True, suggestions=["ask_human"])
        runs.append(info)
        cands += cs
        if (info.get("refusal") or {}).get("code") in ref.UNOBSERVABLE_CODES:
            reason = reason or info["refusal"]["code"]
    if reason:
        return _seal({"schema": SCHEMA, "arm": arm, "observable": False, "reason": reason, "observed_at": observed_at})
    for i, c in enumerate(cands, 1):
        c["id"] = f"c{i}"
    pack = {"schema": SCHEMA, "arm": arm, "observable": True, "observed_at": observed_at, "frames": frames,
            "image_px": SOURCES["image_px"], "grid_px": SOURCES["grid_px"], "reach": cfg["reach"],
            "regions": [{k: s.get(k) for k in ("site", "roi", "role", "dest", "trusted")} for s in cfg["sites"]],
            "dests": cfg["dests"], "candidates": cands, "runs": runs, "readiness": _readiness(raw, arm, cfg.get("peer")),
            "live_verbs": _live_verbs(raw, cfg, any(r.get("result") != "error" for r in runs)), "warnings": warnings}
    return _seal(pack)


def pack_id(pack: dict[str, Any]) -> str:
    """Hash of the pack content without its id: plan-check and verify recompute it, so an edited pack no longer matches."""
    body = {k: v for k, v in pack.items() if k != "observation_id"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _seal(pack: dict[str, Any]) -> dict[str, Any]:
    pack["observation_id"] = pack_id(pack)
    return pack


def annotate_top(jpeg: bytes, pack: dict[str, Any]) -> bytes | None:
    """The top frame with a labelled pixel grid and the named site regions (a reading aid; the pack's numbers are the truth)."""
    try:
        from PIL import Image, ImageDraw
        im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    except Exception:
        return None
    d, step = ImageDraw.Draw(im), int(pack.get("grid_px") or 50)
    for u in range(0, im.width, step):
        d.line([(u, 0), (u, im.height)], fill=(90, 90, 90), width=1)
        d.text((u + 2, 2), str(u), fill=(255, 255, 0))
    for v in range(step, im.height, step):
        d.line([(0, v), (im.width, v)], fill=(90, 90, 90), width=1)
        d.text((2, v + 2), str(v), fill=(255, 255, 0))
    for r in pack.get("regions") or []:
        d.rectangle(r["roi"], outline=(0, 200, 255) if r.get("trusted") is not False else (255, 80, 80), width=2)
        d.text((r["roi"][0] + 3, r["roi"][1] + 12), r["site"] + ("" if r.get("trusted") is not False else " (untrusted)"), fill=(0, 255, 255))
    for c in pack.get("candidates") or []:
        if c.get("at_px"):
            u, v = c["at_px"]
            d.ellipse([u - 6, v - 6, u + 6, v + 6], outline=(0, 255, 0), width=2)
            d.text((u + 8, v - 6), c["id"], fill=(0, 255, 0))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return out.getvalue()


def observe(call: Call, arm: str, *, repeat: int = 1, layers_below: int | None = None, max_age_s: float = MAX_AGE_S, now: Callable[[], float] = time.time,
            sleep: Callable[[float], None] = time.sleep) -> tuple[dict[str, Any], bytes | None]:
    raw, top = fetch_raw(call, arm, repeat=repeat, layers_below=layers_below, now=now, sleep=sleep)
    pack = assemble(raw, max_age_s=max_age_s)
    return pack, (annotate_top(top, pack) if pack["observable"] and top else None)
