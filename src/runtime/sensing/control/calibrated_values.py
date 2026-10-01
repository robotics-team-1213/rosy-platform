"""Runtime reads of the versioned calibration store for sensing nodes (D-47 addendum 2026-10-01).

The static file holds the URDF nominal (D-396 geometry.yaml). The current
accepted record of a kind wins over it; with no accepted record (or no
core_common in a sensing-only image) the static values stand. ``override``
(operator-set keys) wins over both. The second return value is the line the
node logs.
"""


def calibrated(kind, static_values, *, static_source, root=None, robot=None, override=None):
    try:
        from core_common.calibration_store import resolve
    except ImportError:
        chosen = {k: v for k, v in (override or {}).items() if v is not None}
        return {**static_values, **chosen}, f'{static_source} (calibration store unavailable)'
    return resolve(kind, static_values, fallback_source=static_source, root=root, robot=robot,
                   override=override)
