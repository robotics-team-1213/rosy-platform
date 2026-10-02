"""Runtime reads of the versioned calibration store for sensing nodes (D-47 addendum 2026-10-01).

The static file holds the URDF nominal (D-397 geometry.yaml). The current
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


def nominal_camera_profile(path, *, root=None, robot=None):
    """camera_nominal.yaml (URDF nominal, D-364 section 3) refined by the accepted camera_profile.

    An unreadable or unnamed file gives no profile at all, so nominal_ground_plane
    refuses and the regions stay unranged (D-423).
    """
    import yaml
    try:
        with open(path, encoding='utf-8') as handle:
            static = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        return {}, f'{path or "no profile file"} unreadable ({exc}); no NOMINAL ground'
    return calibrated('camera_profile', static, static_source=path, root=root, robot=robot)


def lidar_nose_rad(*, root=None, robot=None):
    """Scan angle of the robot's forward: URDF nominal NOSE_YAW < accepted lidar_mount record."""
    from .sensing.lidar import NOSE_YAW
    values, source = calibrated('lidar_mount', {'lidar_yaw_offset': NOSE_YAW},
                                static_source='URDF nominal lidar forward', root=root, robot=robot)
    return float(values['lidar_yaw_offset']), source
