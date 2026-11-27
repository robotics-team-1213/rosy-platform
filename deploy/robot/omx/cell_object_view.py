"""Side-effect-free catalog-only live object detector & bench pick-place proxy (`rosy.cell-detected-objects.v1`)."""
from __future__ import annotations

import json
import math
from pathlib import Path
import threading
import time
from typing import Any
import urllib.error
import urllib.request

from cell_auto_reach import past_pan_limit, past_park_reach
from cell_auto_safety import finger_room, square_entry
import cell_calibration as cal
import cell_finger_room
import cell_jaw_axis
import cell_objects
from cell_observe import predicted_pixel
import cell_params as prm
from cell_pick_geom import across, reachable_ends, surface_z
import cell_pivot
import cell_place_fit
import cell_robot_profile
from cell_target_binding import DEFAULT_TTL_S, bind_tol_mm
from cell_job_guards import IDEMPOTENCY_KEY_RE, read_json_dict, read_token_file
from cell_job_validators import _catalog_id, _centroid_mm, _object_ref, resolve_under_workdir

SCHEMA = "rosy.cell-detected-objects.v1"
ARMS = ("arm_s", "arm_a", "arm_b")
_ARM_SPECS: dict[str, tuple[str, str, tuple[int, int, int, int], str]] = {
    "arm_a": ("cell-arm-a-stack.json", "object-catalog-orange.json", (395, 360, 625, 478), "top"),
    "arm_b": ("cell-arm-b-stack.json", "object-catalog-orange.json", (10, 340, 230, 478), "top"),
    "arm_s": ("cell-auto-arm-s-live.json", "catalog-board-live-1113.json", (90, 150, 560, 450), "arm_s_top"),
}
_ARM_LETTER = {"arm_a": "a", "arm_b": "b", "arm_s": "s"}
_CACHE_LOCK = threading.Lock()
_DETECT_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _mtime_ns(path: Path | None) -> int:
    try:
        return path.stat().st_mtime_ns if path and path.is_file() else 0
    except OSError:
        return 0


def _resolve_arm_files(workdir: Path, arm: str, config_name: str | None = None, catalog_name: str | None = None) -> tuple[Path | None, Path | None, tuple[int, int, int, int], str]:
    if arm not in _ARM_SPECS:
        raise ValueError(f"unsupported arm {arm!r}")
    def_cfg, def_cat, def_roi, view = _ARM_SPECS[arm]
    cfg_p = resolve_under_workdir(workdir, config_name) if config_name else workdir / def_cfg
    if not config_name and not cfg_p.is_file():
        cfg_p = workdir / f"cell-{arm.split('_')[-1]}.json"
    cat_p = resolve_under_workdir(workdir, catalog_name) if catalog_name else workdir / def_cat
    if not catalog_name and not cat_p.is_file():
        for cand in ("object-catalog.json", "object-catalog.example.json", "catalog-live.json"):
            if (workdir / cand).is_file():
                cat_p = workdir / cand
                break
        else:
            fallback = Path(__file__).resolve().parent / "object-catalog.example.json"
            if fallback.is_file():
                cat_p = fallback
    return (cfg_p if cfg_p.is_file() else None), (cat_p if cat_p.is_file() else None), def_roi, view


def _load_runtime(cfg_p: Path, cat_p: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    try:
        cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        if cfg.get("params_path") and Path(cfg["params_path"]).expanduser().is_file():
            cfg["params"] = prm.load(cfg["params_path"])["values"]
        elif not isinstance(cfg.get("params"), dict):
            cfg["params"] = {}
        cal_path = cfg.get("calibration_path")
        if not cal_path:
            raise ValueError("calibration_path missing from cell config")
        calibration = cell_pivot.with_site_maps(cfg, cal.load(Path(cal_path).expanduser()))
        catalog = cell_objects.load_catalog(cat_p)
        return cfg, calibration, catalog
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc


def fetch_viewer_frame(viewer_url: str, view: str, *, urlopen_fn=urllib.request.urlopen, timeout: float = 2.0):
    """Fetch top JPEG and header timing from :8767 without taking `depth-d435.lock`."""
    import cv2
    import numpy as np

    with urlopen_fn(f"{viewer_url.rstrip('/')}/frame/{view}.jpg", timeout=timeout) as resp:
        raw = resp.read()
        seq_hdr = resp.headers.get("X-Frame-Seq")
        stamp_hdr = resp.headers.get("X-Source-Stamp")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"failed to decode frame for {view}")
    seq = int(seq_hdr) if seq_hdr is not None and str(seq_hdr).strip().lstrip("-").isdigit() else None
    try:
        observed_at = float(stamp_hdr) if stamp_hdr is not None else time.time()
    except ValueError:
        observed_at = time.time()
    h, w = img.shape[:2]
    return img, seq, observed_at, [int(w), int(h)]


def _px_safe(config: dict, calibration: dict, site: str, pt: tuple[float, float]) -> list[float] | None:
    try:
        px = predicted_pixel(config, calibration, site, pt)
        return [round(float(px[0]), 1), round(float(px[1]), 1)] if px is not None else None
    except (KeyError, ValueError, TypeError):
        return None


def _corner_px(config: dict, calibration: dict, site: str, obj: dict) -> tuple[list[float] | None, list[list[float]]]:
    cx, cy = float(obj["centre_mm"][0]), float(obj["centre_mm"][1])
    gx, gy = config["sites"][site].get("grip_offset_m", (0.0, 0.0))
    centre_px = _px_safe(config, calibration, site, (cx / 1000.0 + float(gx), cy / 1000.0 + float(gy)))
    hl, hw = max(1.0, float(obj.get("length_mm") or 30.0)) / 2.0, max(1.0, float(obj.get("width_mm") or 30.0)) / 2.0
    ang = math.radians(float(obj.get("long_axis_deg") or 0.0))
    ca, sa = math.cos(ang), math.sin(ang)
    corners: list[list[float]] = []
    for dx, dy in ((+hl, -hw), (+hl, +hw), (-hl, +hw), (-hl, -hw)):
        cp = _px_safe(config, calibration, site, ((cx + dx * ca - dy * sa) / 1000.0 + float(gx), (cy + dx * sa + dy * ca) / 1000.0 + float(gy)))
        if cp is None:
            corners = []
            break
        corners.append(cp)
    if centre_px is None and obj.get("hull_px"):
        hull = obj["hull_px"]
        centre_px = [round(sum(p[0] for p in hull) / len(hull), 1), round(sum(p[1] for p in hull) / len(hull), 1)]
    return centre_px, corners


def _payload_veto(config: dict, catalog: list[dict], obj_id: str) -> str | None:
    pl = cell_objects.payload(catalog, obj_id)
    kg = pl.get("kg")
    if kg is None or isinstance(kg, bool) or not isinstance(kg, (int, float)):
        return None
    bounds = [prm.get(config.get("params"), "auto.max_gross_kg", 0.08)]
    if isinstance(pl.get("max_gross_kg"), (int, float)) and pl["max_gross_kg"] > 0:
        bounds.append(float(pl["max_gross_kg"]))
    cond_max = (config.get("operating_conditions") or {}).get("payload_max_kg")
    if isinstance(cond_max, (int, float)) and cond_max > 0:
        bounds.append(float(cond_max))
    return f"payload {kg:.3f}kg > {min(bounds):.3f}kg" if float(kg) > min(bounds) else None


def _evaluate_pickable(config: dict, calibration: dict, site: str, site_roi, obj: dict, entries: dict[str, dict], mask) -> tuple[bool, str | None]:
    obj_id = obj["object"]
    entry = entries.get(obj_id)
    if entry is None:
        return False, "not in catalogue"
    raw_m = obj["raw_m"]
    if not (roi_px := _px_safe(config, calibration, site, raw_m)) or not (site_roi[0] + 12 <= roi_px[0] <= site_roi[2] - 12 and site_roi[1] + 12 <= roi_px[1] <= site_roi[3] - 12):
        return False, "not inside the camera view"
    if (pan := past_pan_limit(config, raw_m)) is not None:
        return False, f"out of reach: pan {pan} deg past joint1 limit"
    if (reach := past_park_reach(config, raw_m)) is not None:
        return False, f"out of reach: {reach} mm past park reach"
    if pv := _payload_veto(config, list(entries.values()), obj_id):
        return False, pv
    p = config.get("params") or {}
    if mask is not None and not square_entry(entries, obj):
        site_fp = {k: v for k, v in (config["sites"][site].get("finger_params") or {}).items() if k in prm.DEFAULTS}
        fp = {**p, **site_fp} if site_fp else p
        pixel_fn = lambda q: predicted_pixel(config, calibration, site, q)  # noqa: E731
        ends = obj["long_axis_deg"] if across(entry) == entry["length_mm"] else None
        room = finger_room(mask, site_roi, pixel_fn, obj, ends, fp, opening_width_mm=across(entry))
        if room["margin_mm"] is None:
            if not any(finger_room(mask, site_roi, pixel_fn, e, None, fp, opening_width_mm=across(entry))["margin_mm"] is not None
                       for e in reachable_ends(obj, entry, fp)):
                return False, f"no finger room: {room['free_mm'][0]} / {room['free_mm'][1]} mm free"
    try:
        if not square_entry(entries, obj):
            _, why = cell_jaw_axis.offset_for(config, entry, prm.get(p, "auto.closing_theory_deg", 90.0))
            if why:
                return False, why
    except Exception:
        pass
    return True, None


def detect_objects(
    workdir: Path, arm: str, *, site: str | None = None, config_name: str | None = None,
    catalog_name: str | None = None, viewer_url: str = "http://127.0.0.1:8767",
    cell_state_gen: int = 0, urlopen_fn=urllib.request.urlopen,
) -> dict[str, Any]:
    """Detect catalog-matched objects for `arm` from the live top viewer frame without side effects."""
    cfg_p, cat_p, default_roi, view = _resolve_arm_files(Path(workdir), arm, config_name=config_name, catalog_name=catalog_name)
    cell_id = "cell_s" if arm == "arm_s" else "cell_ab"
    if not (cfg_p and cat_p):
        return {"schema": SCHEMA, "cell_id": cell_id, "arm_id": arm, "camera_role": view,
                "cell_state_gen": int(cell_state_gen), "ttl_s": DEFAULT_TTL_S, "status": "config_unavailable", "objects": []}
    cfg, calibration, catalog = _load_runtime(cfg_p, cat_p)
    cfg, calibration = cell_place_fit.with_tiers(cfg, calibration, catalog)
    img, seq, observed_at, frame_wh = fetch_viewer_frame(viewer_url, view, urlopen_fn=urlopen_fn)
    top_cam = (cfg.get("cameras") or {}).get("top") or {}
    sites_cfg = cfg.get("sites") or {}
    if site is not None:
        if site not in sites_cfg:
            raise ValueError(f"unknown site {site!r}")
        site_names = [site]
    else:
        site_names = [s for s in sites_cfg if cell_pivot.map_record(calibration, s) is not None]
    entries = {e["id"]: e for e in catalog}
    raw_items: list[dict[str, Any]] = []
    cfg_mt, cat_mt = _mtime_ns(cfg_p), _mtime_ns(cat_p)

    for sname in site_names:
        cache_key = (arm, sname, seq, cfg_mt, cat_mt) if seq is not None else None
        if cache_key is not None:
            with _CACHE_LOCK:
                cached = _DETECT_CACHE.get(cache_key)
            if cached is not None:
                raw_items.extend(cached["items"])
                continue
        record = cell_pivot.map_record(calibration, sname)
        if record is None or not top_cam:
            continue
        scfg = sites_cfg[sname]
        sroi = tuple(scfg.get("detect_roi") or scfg.get("roi") or default_roi)
        try:
            sz = surface_z(cfg, sname)
        except SystemExit:
            continue
        detected = cell_objects.detect(
            img, sroi, record, top_cam, catalog, sz, cfg.get("params"),
            scfg.get("surface_px"), scfg.get("surface_lab"), (cfg.get("objects") or {}).get("hsv"),
        )
        gx, gy = scfg.get("grip_offset_m", (0.0, 0.0))
        mask = cell_finger_room.obstacle_mask(img, cfg, sname, sroi) if cfg.get("params") else None
        site_items: list[dict[str, Any]] = []
        for obj in detected:
            if obj.get("matched") is not True or not isinstance(obj.get("object"), str) or not obj["object"]:
                continue  # strict catalog-only gate
            cat_id = obj["object"]
            entry = entries.get(cat_id)
            if entry is None:
                continue
            obj = {**obj, "raw_m": [obj["centre_mm"][0] / 1000.0 + float(gx), obj["centre_mm"][1] / 1000.0 + float(gy)],
                   "layers_below": scfg.get("layers_below", 0)}
            cpx, corners = _corner_px(cfg, calibration, sname, obj)
            pickable, veto = _evaluate_pickable(cfg, calibration, sname, sroi, obj, entries, mask)
            site_items.append({
                "catalog_id": cat_id, "label": entry.get("kind") or cat_id,
                "site": sname, "colour": obj.get("colour"),
                "length_mm": float(obj.get("length_mm") or entry["length_mm"]),
                "width_mm": float(obj.get("width_mm") or entry["width_mm"]),
                "centre_mm": [round(float(obj["centre_mm"][0]), 1), round(float(obj["centre_mm"][1]), 1)],
                "centre_px": cpx, "corners_px": corners,
                "pickable": pickable, "veto_reason": veto, "bind_tol_mm": bind_tol_mm(entry),
            })
        if cache_key is not None:
            with _CACHE_LOCK:
                if len(_DETECT_CACHE) >= 32:
                    _DETECT_CACHE.pop(next(iter(_DETECT_CACHE)))
                _DETECT_CACHE[cache_key] = {"items": site_items}
        raw_items.extend(site_items)

    raw_items.sort(key=lambda it: (it["site"], it["catalog_id"], it["centre_mm"][0], it["centre_mm"][1]))
    seq_tag = seq if seq is not None else int(observed_at * 1000)
    return {
        "schema": SCHEMA, "cell_id": cell_id, "arm_id": arm, "camera_role": view,
        "frame_wh": frame_wh, "source_seq": seq, "observed_at": round(float(observed_at), 3),
        "ttl_s": DEFAULT_TTL_S, "cell_state_gen": int(cell_state_gen), "status": "ok",
        "objects": [{"object_ref": f"det:{seq_tag}:{idx}", **item} for idx, item in enumerate(raw_items)],
    }


def _bench_workdir(bench) -> Path:
    prep = Path(bench.prep)
    cfg = getattr(bench, "_config", {}) or {}
    if cfg.get("work_dir"):
        p = Path(cfg["work_dir"]).expanduser()
        return p if p.is_absolute() else (prep / p)
    for letter in ("a", "b", "s"):
        prof = read_json_dict(prep / f"arm-{letter}-robot-profile.json") or {}
        if prof.get("work_dir"):
            p = Path(prof["work_dir"]).expanduser()
            return p if p.is_absolute() else (prep / p)
    return prep


def _job_api_state_gen(job_api_url: str, token: str, *, urlopen_fn=urllib.request.urlopen) -> int:
    try:
        req = urllib.request.Request(f"{job_api_url.rstrip('/')}/readiness", headers={"Authorization": f"Bearer {token}"})
        with urlopen_fn(req, timeout=1.5) as resp:
            hdr = resp.headers.get("X-Cell-State-Gen")
            if hdr is not None and str(hdr).isdigit():
                return int(hdr)
            data = json.loads(resp.read().decode("utf-8"))
            return int(data.get("cell_state_gen") or 0)
    except Exception:
        return 0


def detect_for_bench(bench, *, arm: str, site: str | None = None, config_name: str | None = None,
                     catalog_name: str | None = None, viewer_url: str = "http://127.0.0.1:8767",
                     urlopen_fn=urllib.request.urlopen) -> dict[str, Any]:
    workdir = _bench_workdir(bench)
    cfg = getattr(bench, "_config", {}) or {}
    job_url = str(cfg.get("job_api_url") or "http://127.0.0.1:8781").rstrip("/")
    tok_p = Path(cfg.get("job_api_token_file") or (Path.home() / ".config/rosy/cell-job-api.token")).expanduser()
    state_gen = 0
    try:
        if tok_p.is_file():
            state_gen = _job_api_state_gen(job_url, read_token_file(tok_p), urlopen_fn=urlopen_fn)
    except (Exception, SystemExit):
        state_gen = 0
    return detect_objects(workdir, arm, site=site, config_name=config_name, catalog_name=catalog_name,
                          viewer_url=viewer_url, cell_state_gen=state_gen, urlopen_fn=urlopen_fn)


def proxy_pick_place(bench, body: dict[str, Any], *, header_idem_key: str | None = None,
                     urlopen_fn=urllib.request.urlopen) -> tuple[int, dict[str, Any]]:
    """Forward a bench UI one-shot `PICK_PLACE` request strictly through `:8781` (never spawn `cell_auto_pick.py`)."""
    arm = str(body.get("arm") or "").strip()
    if arm not in ARMS:
        return 400, {"error": f"unsupported arm {arm!r}"}
    tgt = body.get("target_object")
    if not isinstance(tgt, dict):
        return 400, {"error": "target_object object required"}
    dest_site = str(body.get("dest_site") or body.get("dest") or "").strip()
    if not dest_site:
        return 400, {"error": "dest_site required"}
    try:
        catalog_id = _catalog_id(tgt.get("catalog_id"))
        centroid = _centroid_mm(tgt.get("centroid_mm"))
        observed_at = float(tgt.get("observed_at"))
        if isinstance(tgt.get("observed_at"), bool) or not math.isfinite(observed_at):
            raise ValueError("observed_at must be finite")
        obj_ref = _object_ref(tgt["object_ref"]) if tgt.get("object_ref") is not None else None
        extra: dict[str, Any] = {}
        for src_k, dst_k, cast in (
            ("source_seq", "target_source_seq", int), ("ttl_s", "target_ttl_s", float),
            ("tolerance_mm", "target_tolerance_mm", float), ("cell_state_gen", "expected_cell_state_gen", int),
        ):
            if tgt.get(src_k) is not None:
                if isinstance(tgt[src_k], bool):
                    raise ValueError(f"{src_k} cannot be bool")
                extra[dst_k] = cast(tgt[src_k])
    except (TypeError, ValueError) as exc:
        return 400, {"error": str(exc)}
    dry_run = bool(body.get("dry_run", False))
    idem = str(header_idem_key or body.get("idempotency_key") or "").strip()
    if not dry_run and not IDEMPOTENCY_KEY_RE.fullmatch(idem):
        return 400, {"error": "valid Idempotency-Key required for moving pick_place"}

    cfg = getattr(bench, "_config", {}) or {}
    job_url = str(cfg.get("job_api_url") or "http://127.0.0.1:8781").rstrip("/")
    tok_p = Path(cfg.get("job_api_token_file") or (Path.home() / ".config/rosy/cell-job-api.token")).expanduser()
    if not tok_p.is_file():
        return 503, {"error": "cell-job-api token or endpoint not configured", "error_code": "JOB_API_UNCONFIGURED"}
    try:
        token = read_token_file(tok_p)
    except (ValueError, OSError, SystemExit) as exc:
        return 503, {"error": f"cell-job-api token invalid: {exc}", "error_code": "JOB_API_UNCONFIGURED"}

    workdir = _bench_workdir(bench)
    cfg_p, cat_p, def_roi, _ = _resolve_arm_files(workdir, arm, config_name=body.get("config"), catalog_name=body.get("catalog"))
    if cfg_p is None or cat_p is None:
        return 400, {"error": f"cell config or catalog missing for {arm}"}
    cfg_data = json.loads(cfg_p.read_text(encoding="utf-8"))
    source = str(body.get("source") or tgt.get("site") or ("pinky" if arm == "arm_s" else next(iter(cfg_data.get("sites") or {}), ""))).strip()
    scfg = (cfg_data.get("sites") or {}).get(source) or {}
    roi = body.get("roi") if "roi" in body and body.get("roi") is not None else (scfg.get("detect_roi") or scfg.get("roi") or def_roi)
    try:
        if not isinstance(roi, (list, tuple)) or len(roi) != 4 or any(isinstance(v, bool) for v in roi):
            raise ValueError("roi must be a 4-int sequence")
        roi_vals = [int(v) for v in roi]
    except (TypeError, ValueError) as exc:
        return 400, {"error": f"invalid roi: {exc}"}
    job_name = "auto_pick_dry_run" if dry_run else "auto_pick"
    payload: dict[str, Any] = {
        **({} if dry_run else {"arm": arm}),
        "config": cfg_p.name, "catalog": cat_p.name, "roi": roi_vals,
        "source": source, "dest": dest_site,
        "target_catalog_id": catalog_id, "target_centroid_mm": centroid, "target_observed_at": observed_at,
        **extra,
    }
    if obj_ref is not None:
        payload["target_object_ref"] = obj_ref
    if not dry_run:
        payload["one_shot"] = True
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if idem:
        headers["Idempotency-Key"] = idem
    req = urllib.request.Request(f"{job_url}/jobs/{job_name}", data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
    try:
        with urlopen_fn(req, timeout=10.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            err_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            err_body = {"error": f"cell-job-api returned HTTP {exc.code}"}
        return exc.code, err_body
    except OSError as exc:
        return 502, {"error": f"cell-job-api unreachable: {exc}"}
