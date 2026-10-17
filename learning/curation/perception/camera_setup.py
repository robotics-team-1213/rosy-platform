"""D-792 camera setup: build a reference from one frame and check a frame against it.

World frame: the work surface is z = 0 in cm, z up, x right and y away from the
camera as seen from above. Each marker is printed with its top toward +y.
Pure cv2/numpy, no I/O and no robot control; the verdict is advice to the recorder.
"""
from pathlib import Path
import math
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'contracts/learning/src'))
from rosy.contracts.learning.artifacts import seal
from rosy.contracts.learning.camera_setup import MIN_MARKERS, MOUNT, judge, validate_reference

DICTIONARY = 'DICT_4X4_50'


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
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _detector()(gray)
    if ids is None:
        return {}
    return {int(i): c.reshape(4, 2).astype(float) for i, c in zip(ids.ravel(), corners)}


def marker_world(marker):
    """The four corners of one layout marker in world cm, in ArUco corner order."""
    (x, y), h = marker['center_cm'], marker['size_cm'] / 2
    return np.array([[x - h, y + h, 0], [x + h, y + h, 0], [x + h, y - h, 0], [x - h, y - h, 0]], float)


def _camera(intrinsics):
    fx, fy, cx, cy = intrinsics['k']
    return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], float), np.array(intrinsics['dist'], float)


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


def make_reference(frame, *, camera_role, camera_identity, fps, intrinsics, layout, measured,
                   guides, reference_still, created_at, created_by):
    """A sealed, validated reference from one frame in which every layout marker is visible."""
    found = detect(frame)
    missing = [m['id'] for m in layout if m['id'] not in found]
    if missing:
        raise ValueError(f'reference frame does not show markers {missing}')
    estimated = estimate_mount(found, layout, intrinsics)
    if estimated is None:
        raise ValueError('camera pose could not be estimated from the reference frame')
    height, width = frame.shape[:2]
    return validate_reference(seal({
        'schema': 'rosy.camera-setup-reference/1',
        'camera_role': camera_role, 'camera_identity': camera_identity,
        'width': width, 'height': height, 'fps': fps, 'intrinsics': intrinsics,
        'marker_dictionary': DICTIONARY,
        'markers': [{**m, 'corners_px': [[round(float(x), 2), round(float(y), 2)] for x, y in found[m['id']]]}
                    for m in layout],
        'mount': {'measured': {key: measured.get(key) for key in MOUNT},
                  'estimated': {key: round(v, 3) for key, v in estimated.items()}},
        'reference_still': reference_still, 'guides': guides,
        'created_at': created_at, 'created_by': created_by,
    }))


def _unmeasurable(seen):
    return {'markers_seen': seen, 'marker_px_mean': None, 'marker_px_max': None, 'verdict': 'unmeasurable',
            **{'d_' + key: None for key in MOUNT}}


def check(frame, reference, camera_info_sha256):
    """One setup check: marker pixel error and mount difference against the reference, with a verdict."""
    height, width = frame.shape[:2]
    if (camera_info_sha256 != reference['intrinsics']['camera_info_sha256']
            or (width, height) != (reference['width'], reference['height'])):
        return _unmeasurable(0)
    found = detect(frame)
    layout = [m for m in reference['markers'] if m['id'] in found]
    current = estimate_mount(found, layout, reference['intrinsics'])
    if current is None:
        return _unmeasurable(len(layout))
    errors = np.concatenate([np.linalg.norm(found[m['id']] - np.array(m['corners_px']), axis=1) for m in layout])
    estimated = reference['mount']['estimated']
    delta = {key: current[key] - estimated[key] for key in MOUNT}
    delta['pan_deg'] = (delta['pan_deg'] + 180) % 360 - 180
    metrics = {'markers_seen': len(layout), 'marker_px_mean': round(float(errors.mean()), 3),
               'marker_px_max': round(float(errors.max()), 3),
               **{'d_' + key: round(v, 3) for key, v in delta.items()}}
    return {**metrics, 'verdict': judge(metrics, width, height)}
