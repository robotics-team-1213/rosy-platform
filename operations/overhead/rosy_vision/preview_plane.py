"""The legacy map-plane response adapter, separate from ingest transport."""
import asyncio
from rosy_vision.rectify import MapPlane, crop_map_plane, plane_observed_fraction


async def map_plane_response(ingest, source, frame, age, lease, *, unavailable, response, lens_header, warp):
    """D-560: the latest frame warped to the map plane, or 409; never the raw frame.

    The warp runs off the event loop, once per (frame, record revision) for all readers.
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
    if crop_map is not None:
        cropped = await asyncio.to_thread(crop_map_plane, plane, *crop_map)
        if cropped is None:
            return unavailable()
        jpeg, size, bounds = cropped
        rectified = "map-crop"
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
        "X-Frame-Observed-Fraction": f"{plane_observed_fraction(plane, crop_map):.6f}",
        **lens_header(ingest.source_lens(source)),
    })
