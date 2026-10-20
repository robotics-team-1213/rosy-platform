"""D-792: a moved or rotated camera changes the setup verdict, with or without work-surface markers.

features (default): a textured scene stands in for a real workcell; camera rotations are applied
as K R K^-1, which is exact for a rotating camera. markers: a rendered work surface with four
DICT_4X4_50 markers at a known camera pose.
"""
import math

import cv2
import numpy as np
import pytest

import camera_setup

K = {'camera_info_sha256': 'c' * 64, 'revision': 'omx-front-2026-10-18', 'k': [600.0, 600.0, 320.0, 240.0],
     'dist': [0.0, 0.0, 0.0, 0.0, 0.0]}
KM = np.array([[600.0, 0, 320], [0, 600, 240], [0, 0, 1]])
LAYOUT = [{'id': i, 'size_cm': 6.0, 'center_cm': c}
          for i, c in enumerate([[-20.0, 0.0], [20.0, 0.0], [-20.0, 30.0], [20.0, 30.0]])]
PX_PER_CM, X0, Y1, SIZE = 10, -35.0, 45.0, 700  # texture covers x -35..35 cm, y -25..45 cm
COMMON = dict(camera_role='front', camera_identity='omx-front-usb-1', fps=30, intrinsics=K, guides=[],
              reference_still='d' * 64, created_at='2026-10-18T09:00:00+09:00', created_by='operator')


def scene(seed=7):
    """640x480 stand-in for a workcell: shapes, edges and text-like strokes at many scales."""
    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), 90, np.uint8)
    for _ in range(160):
        colour = tuple(int(v) for v in rng.integers(0, 255, 3))
        x, y = int(rng.integers(0, 640)), int(rng.integers(0, 480))
        kind = rng.integers(0, 3)
        if kind == 0:
            cv2.rectangle(img, (x, y), (x + int(rng.integers(8, 70)), y + int(rng.integers(8, 70))), colour, -1)
        elif kind == 1:
            cv2.circle(img, (x, y), int(rng.integers(4, 30)), colour, -1)
        else:
            cv2.line(img, (x, y), (int(rng.integers(0, 640)), int(rng.integers(0, 480))), colour, int(rng.integers(1, 4)))
    return cv2.GaussianBlur(img, (3, 3), 0)


def rotate(img, pan=0.0, tilt=0.0, roll=0.0):
    a, b, c = map(math.radians, (tilt, pan, roll))
    rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return cv2.warpPerspective(img, KM @ (rz @ ry @ rx) @ np.linalg.inv(KM), (640, 480), borderMode=cv2.BORDER_REPLICATE)


def zoom(img, scale):
    return cv2.warpAffine(img, cv2.getRotationMatrix2D((320, 240), 0, scale), (640, 480), borderMode=cv2.BORDER_REPLICATE)


@pytest.fixture(scope='module')
def features_reference():
    return camera_setup.make_reference(scene(), measured={}, **COMMON)


def test_features_reference_needs_no_markers(features_reference):
    assert features_reference['method'] == 'features'
    assert features_reference['markers'] == [] and features_reference['mount']['estimated'] is None


def test_features_same_pose_is_ok_even_with_a_moving_arm(features_reference):
    still = scene()
    arm = still.copy()
    cv2.rectangle(arm, (380, 120), (560, 420), (30, 30, 30), -1)  # about a fifth of the view changes
    for frame in (still, arm):
        result = camera_setup.check(frame, features_reference, 'c' * 64, still)
        assert result['verdict'] == 'ok', result
        assert result['matches'] >= 150 and result['d_height_cm'] is None


@pytest.mark.parametrize('frame, key, expected', [
    (rotate(scene(), pan=1.0), 'd_pan_deg', 1.0),
    (rotate(scene(), tilt=1.0), 'd_tilt_deg', 1.0),
    (rotate(scene(), roll=2.0), 'd_roll_deg', 2.0),
    (zoom(scene(), 1.03), 'd_scale_pct', 3.0),
])
def test_features_moved_camera_is_measured(features_reference, frame, key, expected):
    result = camera_setup.check(frame, features_reference, 'c' * 64, scene())
    assert result['verdict'] == 'adjust', result
    assert result[key] == pytest.approx(expected, abs=0.15)
    assert result['px_mean'] > 3
    assert all(type(v) in (int, float, str, type(None)) for v in result.values()), 'contract-exact types'


def test_features_near_darkness_is_unmeasurable_not_ok(features_reference):
    dark = np.clip(scene().astype(np.float32) * 0.03 + np.random.default_rng(0).normal(0, 6, (480, 640, 3)), 0, 255)
    result = camera_setup.check(dark.astype(np.uint8), features_reference, 'c' * 64, scene())
    assert result['verdict'] == 'unmeasurable', result
    assert result['px_mean'] is None


def test_features_reference_refuses_a_blank_photo():
    with pytest.raises(ValueError, match='too little texture'):
        camera_setup.make_reference(np.full((480, 640, 3), 120, np.uint8), measured={}, **COMMON)


def _texture():
    tex = np.full((SIZE, SIZE), 255, np.uint8)
    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    draw = getattr(aruco, 'generateImageMarker', None) or aruco.drawMarker
    for m in LAYOUT:
        side = int(m['size_cm'] * PX_PER_CM)
        u = int((m['center_cm'][0] - m['size_cm'] / 2 - X0) * PX_PER_CM)
        v = int((Y1 - m['center_cm'][1] - m['size_cm'] / 2) * PX_PER_CM)  # marker top toward +y
        tex[v:v + side, u:u + side] = draw(dictionary, m['id'], side)
    return tex


def _render(centre, target, roll_deg=0.0):
    """640x480 view of the marker work surface from a camera at ``centre`` looking at ``target`` (cm)."""
    centre, target = np.array(centre, float), np.array(target, float)
    z = (target - centre) / np.linalg.norm(target - centre)
    x = np.cross(z, [0, 0, 1.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    a = math.radians(roll_deg)
    x, y = math.cos(a) * x + math.sin(a) * y, -math.sin(a) * x + math.cos(a) * y
    r = np.vstack([x, y, z])
    t = -r @ centre
    world_to_image = KM @ np.column_stack([r[:, 0], r[:, 1], t])
    texture_to_world = np.array([[1 / PX_PER_CM, 0, X0], [0, -1 / PX_PER_CM, Y1], [0, 0, 1]])
    return cv2.warpPerspective(_texture(), world_to_image @ texture_to_world, (640, 480), borderValue=180)


HOME = dict(centre=[0.0, -40.0, 45.0], target=[0.0, 15.0, 0.0])


@pytest.fixture(scope='module')
def reference():
    return camera_setup.make_reference(
        _render(**HOME), method='markers', layout=LAYOUT, measured={'height_cm': 45.0, 'tilt_deg': 39.3},
        **{**COMMON, 'guides': [{'kind': 'zone', 'label': 'work area',
                                 'points': [[100, 300], [540, 300], [500, 120], [140, 120]], 'closed': True}]})


def test_reference_estimates_the_mount(reference):
    est = reference['mount']['estimated']
    assert est['height_cm'] == pytest.approx(45.0, abs=0.5)
    assert est['distance_cm'] == pytest.approx(40.0, abs=0.5)
    assert est['tilt_deg'] == pytest.approx(math.degrees(math.atan2(45, 55)), abs=0.5)
    assert est['roll_deg'] == pytest.approx(0.0, abs=0.5)


def test_same_pose_is_ok(reference):
    result = camera_setup.check(_render(**HOME), reference, 'c' * 64)
    assert result['verdict'] == 'ok', result
    assert result['matches'] == 4 and result['d_scale_pct'] is None


@pytest.mark.parametrize('pose, key, sign', [
    (dict(centre=[0.0, -40.0, 43.0], target=[0.0, 15.0, 0.0]), 'd_height_cm', -1),  # 2 cm lower
    (dict(centre=[0.0, -40.0, 45.0], target=[0.0, 18.5, 0.0]), 'd_tilt_deg', -1),   # ~2 deg less tilt
    (dict(centre=[0.0, -40.0, 45.0], target=[0.0, 15.0, 0.0], roll_deg=3.0), 'd_roll_deg', 0),
])
def test_moved_camera_needs_adjusting(reference, pose, key, sign):
    result = camera_setup.check(_render(**pose), reference, 'c' * 64)
    assert result['verdict'] == 'adjust', result
    assert abs(result[key]) > 1.0
    if sign:
        assert math.copysign(1, result[key]) == sign


def test_hidden_markers_or_other_calibration_are_unmeasurable(reference):
    frame = _render(**HOME)
    for corners in [np.array(m['corners_px']) for m in reference['markers'][:2]]:
        x0, y0 = corners.min(axis=0).astype(int) - 3
        x1, y1 = corners.max(axis=0).astype(int) + 3
        frame[y0:y1, x0:x1] = 255
    assert camera_setup.check(frame, reference, 'c' * 64)['verdict'] == 'unmeasurable'
    assert camera_setup.check(_render(**HOME), reference, 'e' * 64)['verdict'] == 'unmeasurable'


def test_reference_refuses_a_hidden_layout_marker():
    frame = _render(**HOME)
    frame[:, :200] = 255
    with pytest.raises(ValueError, match='does not show markers'):
        camera_setup.make_reference(frame, method='markers', layout=LAYOUT, measured={}, **COMMON)


WRIST_POSE = {'joint_names': ['joint1', 'joint2', 'joint3', 'joint4', 'joint5'],
              'positions_rad': [0.0, -0.6, 0.3, 1.2, 0.0], 'tolerance_rad': 0.01}


def test_wrist_camera_is_checked_only_at_its_check_pose():
    ref = camera_setup.make_reference(scene(), measured={}, check_pose=WRIST_POSE, **{**COMMON, 'camera_role': 'front'})
    at_pose = dict(zip(WRIST_POSE['joint_names'], WRIST_POSE['positions_rad']))
    result = camera_setup.check(scene(), ref, 'c' * 64, scene(), at_pose)
    assert result['verdict'] == 'ok' and result['pose_error_rad'] == 0
    # Same picture, arm elsewhere: the comparison would be meaningless, so it is not made.
    result = camera_setup.check(scene(), ref, 'c' * 64, scene(), {**at_pose, 'joint4': 1.25})
    assert result['verdict'] == 'unmeasurable' and result['pose_error_rad'] == pytest.approx(0.05)
    with pytest.raises(ValueError, match='joint readback'):
        camera_setup.check(scene(), ref, 'c' * 64, scene())
