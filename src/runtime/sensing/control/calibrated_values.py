"""Runtime reads of the versioned calibration store for sensing nodes (D-47 addendum 2026-10-01).

The current accepted record of a kind wins over the static file; with no
accepted record (or no core_common in a sensing-only image) the static
values stand. The second return value is the line the node logs.
"""


def calibrated(kind, static_values, *, static_source, root=None, robot=None):
    try:
        from core_common.calibration_store import resolve
    except ImportError:
        return dict(static_values), f'{static_source} (calibration store unavailable)'
    return resolve(kind, static_values, fallback_source=static_source, root=root, robot=robot)
