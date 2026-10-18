"""D-792 camera setup: build a reference from one frame and check a frame against it.

``features`` (default) needs no markers: ORB features of the static scene in the reference still
give a homography to the current frame, from which the screen shift, pan/tilt/roll and scale follow.
It cannot see centimetres. ``markers`` adds DICT_4X4_50 work-surface markers for height and distance:
the work surface is z = 0 in cm, z up, x right and y away from the camera as seen from above, each
marker printed with its top toward +y. Pure cv2/numpy, no I/O and no robot control; advice only.
"""
from pathlib import Path
import math
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'contracts/learning/src'))
from rosy.contracts.learning.artifacts import seal
from rosy.contracts.learning.camera_setup import (MIN_MARKERS, MIN_MATCHES, MOUNT, judge, pose_error,
                                                  validate_reference)

DICTIONARY = 'DICT_4X4_50'
FEATURES = 3000
MIN_REFERENCE_FEATURES = 500  # a blank or dark reference would make every later check unmeasurable


def _gray(frame):
    return frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _detector():
    """gray -> (corners, ids, rejected). Built per call site, never at import:
    OpenCV 4.6 has only DetectorParameters_create(); a bare DetectorParameters() there segfaults."""
    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(getattr(aruco, DICTIONARY))
    create = getattr(aruco, 'DetectorParameters_create', None)
    parameters = create() if create is not None else aruco.DetectorParameters()
    parameters.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX
    if hasattr(aruco, 'ArucoDetector'):
        return aruco.ArucoDetector(dictionary, parameters).detectMarkers
    return lambda gray: aruco.detectMarkers(gray, dictionary, parameters=parameters)


def detect(frame):
    """Marker id -> 4x2 corner pixels (top-left, top-right, bottom-right, bottom-left)."""
    corners, ids, _ = _detector()(_gray(frame))
    if ids is None:
        return {}
    return {int(i): c.reshape(4, 2).astype(float) for i, c in zip(ids.ravel(), corners)}


def _features(frame):
    # CLAHE keeps evening frames matchable: real frames held >= 295 inliers down to 10% light.
    gray = cv2.createCLAHE(2.0, (8, 8)).apply(_gray(frame))
    return cv2.ORB_create(FEATURES).detectAndCompute(gray, None)


def _camera(intrinsics):
    fx, fy, cx, cy = intrinsics['k']
    return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], float), np.array(intrinsics['dist'], float)


def _grid(width, height):
    return np.array([[x, y] for x in np.linspace(.1 * width, .9 * width, 9)
                     for y in np.linspace(.1 * height, .9 * height, 5)], np.float32)


def match_features(still, frame, intrinsics):
    """Homography still -> frame and its metrics, or (None, inliers) when the scene cannot be matched."""
    k0, d0 = _features(still)
    k1, d1 = _features(frame)
    if d0 is None or d1 is None or len(k1) < MIN_MATCHES:
        return None, 0
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d0, d1, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < MIN_MATCHES:
        return None, len(good)
    src = np.float32([k0[m.queryIdx].pt for m in good])
    dst = np.float32([k1[m.trainIdx].pt for m in good])
    h, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    inliers = int(mask.sum()) if mask is not None else 0
    if h is None or inliers < MIN_MATCHES or inliers < 0.5 * len(good):
        return None, inliers
    height, width = frame.shape[:2]
    grid = _grid(width, height)
    shift = np.linalg.norm(cv2.perspectiveTransform(grid[None], h)[0] - grid, axis=1)
    k, _ = _camera(intrinsics)
    m = np.linalg.inv(k) @ h @ k
    u, s, vt = np.linalg.svd(m)
    r = u @ vt
    if np.linalg.det(r) < 0:
        r = -r
    # shortcut: a homography treats the scene as far or flat; a sideways camera shift near the
    # arm leaks into pan/tilt. The pixel shift still drives the verdict, so alignment holds.
    return {'matches': inliers, 'px_mean': round(float(shift.mean()), 3), 'px_max': round(float(shift.max()), 3),
            'd_pan_deg': round(math.degrees(math.atan2(r[0, 2], r[2, 2])), 3),
            'd_tilt_deg': round(math.degrees(math.asin(max(-1.0, min(1.0, -r[1, 2])))), 3),
            'd_roll_deg': round(math.degrees(math.atan2(r[1, 0], r[0, 0])), 3),
            'd_scale_pct': round((math.sqrt(float(s[0] * s[1])) / float(s[2]) - 1) * 100, 3)}, h


def marker_world(marker):
    """The four corners of one layout marker in world cm, in ArUco corner order."""
    (x, y), h = marker['center_cm'], marker['size_cm'] / 2
    return np.array([[x - h, y + h, 0], [x + h, y + h, 0], [x + h, y - h, 0], [x - h, y - h, 0]], float)


def estimate_mount(found, layout, intrinsics):
    """Camera height, distance, tilt, pan and roll from the seen layout markers, or None under three."""
    seen = [m for m in layout if m['id'] in found]
    if len(seen) < MIN_MARKERS:
        return None
    world = np.vstack([marker_world(m) for m in seen])
    image = np.vstack([found[m['id']] for m in seen])
    k, dist = _camera(intrinsics)
    ok, rvec, tvec = cv2.solvePnP(world, image, k, dist, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None
    r, _ = cv2.Rodrigues(rvec)
    centre = (-r.T @ tvec).ravel()
    axis, right = r.T @ np.array([0, 0, 1.0]), r.T @ np.array([1.0, 0, 0])
    return {
        'height_cm': float(centre[2]),
        'distance_cm': float(math.hypot(centre[0], centre[1])),
        'tilt_deg': math.degrees(math.asin(max(-1.0, min(1.0, -axis[2])))),  # down is positive
        # shortcut: pan is ill-defined for a camera looking straight down; fine for workcell side views.
        'pan_deg': math.degrees(math.atan2(axis[1], axis[0])),
        'roll_deg': math.degrees(math.asin(max(-1.0, min(1.0, right[2])))),
    }


def make_reference(frame, *, camera_role, camera_identity, fps, intrinsics, measured, guides,
                   reference_still, created_at, created_by, method='features', layout=(), check_pose=None):
    """A sealed, validated reference from one frame (with every layout marker visible for ``markers``)."""
    height, width = frame.shape[:2]
    markers, estimated = [], None
    if method == 'markers':
        found = detect(frame)
        missing = [m['id'] for m in layout if m['id'] not in found]
        if missing:
            raise ValueError(f'reference frame does not show markers {missing}')
        estimated = estimate_mount(found, layout, intrinsics)
        if estimated is None:
            raise ValueError('camera pose could not be estimated from the reference frame')
        estimated = {key: round(v, 3) for key, v in estimated.items()}
        markers = [{**m, 'corners_px': [[round(float(x), 2), round(float(y), 2)] for x, y in found[m['id']]]}
                   for m in layout]
    elif layout:
        raise ValueError('a features reference takes no marker layout')
    elif len(_features(frame)[0]) < MIN_REFERENCE_FEATURES:
        raise ValueError('reference photo has too little texture or light to match later photos')
    return validate_reference(seal({
        'schema': 'rosy.camera-setup-reference/1',
        'camera_role': camera_role, 'camera_identity': camera_identity,
        'width': width, 'height': height, 'fps': fps, 'intrinsics': intrinsics, 'method': method,
        'marker_dictionary': DICTIONARY if method == 'markers' else None, 'markers': markers,
        'mount': {'measured': {key: measured.get(key) for key in MOUNT}, 'estimated': estimated},
        'check_pose': check_pose,
        'reference_still': reference_still, 'guides': guides,
        'created_at': created_at, 'created_by': created_by,
    }))


def unmeasurable(method, matches, pose=None):
    return {'method': method, 'matches': matches, 'pose_error_rad': pose, 'px_mean': None, 'px_max': None,
            **{key: None for key in ('d_pan_deg', 'd_tilt_deg', 'd_roll_deg', 'd_scale_pct',
                                     'd_height_cm', 'd_distance_cm')}, 'verdict': 'unmeasurable'}


def measure(frame, reference, camera_info_sha256, still=None, joints=None):
    """(setup check record, overlay). The overlay is ``{'homography': 3x3}`` for features or
    ``{'detected': {id: corners}}`` for markers, for drawing only; it is not part of the record.
    ``joints`` (name -> rad) is required when the reference has a check pose (wrist camera)."""
    height, width = frame.shape[:2]
    method = reference['method']
    pose = pose_error(reference, joints)
    if pose is not None:
        pose = round(pose, 5)
    if (camera_info_sha256 != reference['intrinsics']['camera_info_sha256']
            or (width, height) != (reference['width'], reference['height'])
            or (pose is not None and pose > reference['check_pose']['tolerance_rad'])):
        return unmeasurable(method, 0, pose), {}
    if method == 'features':
        if still is None or still.shape[:2] != frame.shape[:2]:
            raise ValueError('features check needs the reference still at the frame size')
        metrics, h = match_features(still, frame, reference['intrinsics'])
        if metrics is None:
            return unmeasurable(method, h, pose), {}
        record = {'method': method, **metrics, 'pose_error_rad': pose, 'd_height_cm': None, 'd_distance_cm': None}
        record['verdict'] = judge(record, width, height)
        return record, {'homography': np.round(h, 8).tolist()}
    found = detect(frame)
    layout = [m for m in reference['markers'] if m['id'] in found]
    current = estimate_mount(found, layout, reference['intrinsics'])
    overlay = {'detected': {str(i): np.round(c, 2).tolist() for i, c in found.items()}}
    if current is None:
        return unmeasurable(method, len(layout), pose), overlay
    errors = np.concatenate([np.linalg.norm(found[m['id']] - np.array(m['corners_px']), axis=1) for m in layout])
    estimated = reference['mount']['estimated']
    delta = {key: current[key] - estimated[key] for key in MOUNT}
    delta['pan_deg'] = (delta['pan_deg'] + 180) % 360 - 180
    record = {'method': method, 'matches': len(layout), 'pose_error_rad': pose, 'px_mean': round(float(errors.mean()), 3),
              'px_max': round(float(errors.max()), 3), 'd_scale_pct': None,
              **{'d_' + key: round(v, 3) for key, v in delta.items()}}
    record['verdict'] = judge(record, width, height)
    return record, overlay


def check(frame, reference, camera_info_sha256, still=None, joints=None):
    """One setup check record (Episode ``provenance.camera.setup.before``/``after`` shape)."""
    return measure(frame, reference, camera_info_sha256, still, joints)[0]
