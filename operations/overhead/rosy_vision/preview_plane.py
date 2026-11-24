"""Preview encode adapters, separate from ingest transport: the legacy map plane and the rectified view."""
import asyncio
import math
from rosy_vision.birdview_overlay import overlay_signature, render_map_overlay_jpeg
from rosy_vision.rectify import MapPlane, crop_map_plane, map_plane_jpeg, plane_observed_fraction, rectify_jpeg


async def rectified_jpeg(ingest, source, frame, settings) -> bytes:
    """Network load: ``frame`` rectified with ``settings``, encoded once off the loop for every viewer.

    Kept per (source, settings) for the source's current frame only; a new frame drops the older ones.
    Per-viewer rate limits stay in ingest. A failure (TypeError, ValueError, cv2.error) reaches the caller.
    """
    cache = ingest.__dict__.setdefault("_rectify_cache", {})
    key = (source, repr(settings))   # repr: auto-mode corners may arrive as lists (unhashable)
    cached = cache.get(key)
    if cached is None or cached[0] is not frame:
        for old in [k for k, v in cache.items() if k[0] == source and v[0] is not frame]:
            del cache[old]
        task = asyncio.ensure_future(asyncio.to_thread(rectify_jpeg, frame.jpeg, settings))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        cached = cache[key] = (frame, task)
    return await asyncio.shield(cached[1])


def _collect_overlay_inputs(ingest, source: str) -> tuple[list[dict], list[dict], list[dict]]:
    ctx = (getattr(ingest, "_overlay_context", None) or {}).get(source) or {}
    places = list(ctx.get("places") or ())
    robots_by_id: dict[str, dict] = {}
    for row in ctx.get("robots") or ():
        if isinstance(row, dict) and row.get("robot_id"):
            robots_by_id[str(row["robot_id"])] = dict(row)
    arms: list[dict] = []
    tracker = getattr(ingest, "anchor_tracker", None)
    if tracker is not None:
        lock = getattr(tracker, "_lock", None)
        states_map = getattr(tracker, "_states", None)
        seen_map = getattr(tracker, "_marker_seen", None)
        if lock is not None and isinstance(states_map, dict):
            with lock:
                items = list(states_map.items())
                seen = dict(seen_map or {})
            for tid, st in items:
                kind = getattr(st, "kind", None)
                if kind == "omx_ai":
                    arms.append({
                        "target_id": tid,
                        "label": getattr(st, "label", tid),
                        "base_x": getattr(st, "base_x", None),
                        "base_y": getattr(st, "base_y", None),
                        "head_x": getattr(st, "head_x", None),
                        "head_y": getattr(st, "head_y", None),
                    })
                elif kind == "pinky" and seen.get(tid):
                    hx, hy = getattr(st, "base_x", None), getattr(st, "base_y", None)
                    hyaw = getattr(st, "base_yaw", None)
                    if all(isinstance(v, (int, float)) and math.isfinite(v) for v in (hx, hy)):
                        robots_by_id[tid] = {
                            "robot_id": tid,
                            "x": float(hx),
                            "y": float(hy),
                            **({"yaw": float(hyaw)} if isinstance(hyaw, (int, float)) and math.isfinite(hyaw) else {}),
                        }
    robots = [robots_by_id[k] for k in sorted(robots_by_id)]
    return places, robots, arms


async def map_plane_response(ingest, source, frame, age, lease, *, unavailable, response, lens_header,
                             warp=map_plane_jpeg, annotated: bool = False):
    """D-560: the latest frame warped to the map plane, or 409; never the raw frame.

    The warp runs off the event loop, once per (frame, record revision) for all readers.
    When ``annotated=True`` (``mode: map_overlay``), renders metric grid, lanes,
    places, robots and arm positions onto a separate cached JPEG copy.
    """
    reported = ingest._plane_records.get(source)
    if reported is None:
        return unavailable()
    record, map_id = reported
    revision = str(record.get("calibration_revision"))
    crop_map = lease.get("crop_map") if lease else None
    if crop_map is not None and (lease.get("crop_map_id") != map_id
                                 or lease.get("crop_revision") != revision):
        return unavailable()
    cached = ingest._plane_cache.get(source)
    if cached is None or cached[0] is not frame or cached[1] != revision:
        task = asyncio.ensure_future(asyncio.to_thread(
            warp, frame.jpeg, record, source_id=source, map_id=map_id,
            lens=ingest.source_lens(source)))
        # Retrieve a failure even when no reader is left to await it (no "never retrieved" log).
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        cached = (frame, revision, task)
        ingest._plane_cache[source] = cached
    plane: MapPlane | None = await asyncio.shield(cached[2])
    if plane is None:
        return unavailable()
    jpeg, size, bounds, rectified = plane.jpeg, plane.size, plane.bounds_m, "map"
    obs_fraction = plane_observed_fraction(plane, crop_map)
    if crop_map is not None:
        cropped = await asyncio.to_thread(crop_map_plane, plane, *crop_map)
        if cropped is None:
            return unavailable()
        jpeg, size, bounds = cropped
        rectified = "map-crop"
    elif annotated:
        places, robots, arms = _collect_overlay_inputs(ingest, source)
        map_paint = getattr(ingest, "map_paint", None)
        sig = (revision, overlay_signature(places, robots, arms), id(map_paint) if map_paint is not None else 0)
        ov_cache = ingest.__dict__.setdefault("_overlay_cache", {})
        ov_entry = ov_cache.get(source)
        if ov_entry is None or ov_entry[0] is not frame or ov_entry[1] != sig:
            ov_task = asyncio.ensure_future(asyncio.to_thread(
                render_map_overlay_jpeg,
                plane,
                map_paint=map_paint,
                places=places,
                robots=robots,
                arms=arms,
                observed_fraction=obs_fraction,
            ))
            ov_task.add_done_callback(lambda t: t.cancelled() or t.exception())
            ov_entry = (frame, sig, ov_task)
            ov_cache[source] = ov_entry
        jpeg = await asyncio.shield(ov_entry[2])
        rectified = "map-overlay"
    min_x, min_y, max_x, max_y = bounds
    return response(200, jpeg, extra={
        "Content-Type": "image/jpeg", "Cache-Control": "no-store",
        "X-Frame-Seq": str(frame.header.seq),
        "X-Frame-Age-Ms": str(round(age * 1000)),
        "X-Frame-Captured-At": str(frame.captured_at),
        "X-Frame-Width": str(size[0]),
        "X-Frame-Height": str(size[1]),
        "X-Frame-Rotation-Deg": "0",
        "X-Frame-Rectified": rectified,
        "X-Frame-Plane": ",".join(f"{v:.4f}" for v in (min_x, min_y, max_x, max_y, plane.px_per_m)),
        "X-Frame-Calibration": plane.revision,
        "X-Frame-Observed-Fraction": f"{obs_fraction:.6f}",
        **lens_header(ingest.source_lens(source)),
    })
