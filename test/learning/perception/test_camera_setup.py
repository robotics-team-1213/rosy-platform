"""D-792 S1: a moved or tilted camera changes the setup verdict; hidden markers make it unmeasurable."""
import math

import cv2
import numpy as np
import pytest

import camera_setup

K = {'camera_info_sha256': 'c' * 64, 'revision': 'omx-front-2026-10-18', 'k': [600.0, 600.0, 320.0, 240.0],
     'dist': [0.0, 0.0, 0.0, 0.0, 0.0]}
LAYOUT = [{'id': i, 'size_cm': 6.0, 'center_cm': c}
          for i, c in enumerate([[-20.0, 0.0], [20.0, 0.0], [-20.0, 30.0], [20.0, 30.0]])]
PX_PER_CM, X0, Y1, SIZE = 10, -35.0, 45.0, 700  # texture covers x -35..35 cm, y -25..45 cm


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
    """640x480 view of the work surface from a camera at ``centre`` looking at ``target`` (cm)."""
    centre, target = np.array(centre, float), np.array(target, float)
    z = (target - centre) / np.linalg.norm(target - centre)
    x = np.cross(z, [0, 0, 1.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    a = math.radians(roll_deg)
    x, y = math.cos(a) * x + math.sin(a) * y, -math.sin(a) * x + math.cos(a) * y
    r = np.vstack([x, y, z])
    t = -r @ centre
    fx, fy, cx, cy = K['k']
    k = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
    world_to_image = k @ np.column_stack([r[:, 0], r[:, 1], t])
    texture_to_world = np.array([[1 / PX_PER_CM, 0, X0], [0, -1 / PX_PER_CM, Y1], [0, 0, 1]])
    return cv2.warpPerspective(_texture(), world_to_image @ texture_to_world, (640, 480), borderValue=180)


HOME = dict(centre=[0.0, -40.0, 45.0], target=[0.0, 15.0, 0.0])


@pytest.fixture(scope='module')
def reference():
    return camera_setup.make_reference(
        _render(**HOME), camera_role='front', camera_identity='omx-front-usb-1', fps=30, intrinsics=K,
        layout=LAYOUT, measured={'height_cm': 45.0, 'tilt_deg': 39.3}, guides=[
            {'kind': 'zone', 'label': 'work area', 'points': [[100, 300], [540, 300], [500, 120], [140, 120]],
             'closed': True}],
        reference_still='d' * 64, created_at='2026-10-18T09:00:00+09:00', created_by='operator')


def test_reference_estimates_the_mount(reference):
    est = reference['mount']['estimated']
    assert est['height_cm'] == pytest.approx(45.0, abs=0.5)
    assert est['distance_cm'] == pytest.approx(40.0, abs=0.5)
    assert est['tilt_deg'] == pytest.approx(math.degrees(math.atan2(45, 55)), abs=0.5)
    assert est['roll_deg'] == pytest.approx(0.0, abs=0.5)


def test_same_pose_is_ok(reference):
    result = camera_setup.check(_render(**HOME), reference, 'c' * 64)
    assert result['verdict'] == 'ok', result
    assert result['markers_seen'] == 4


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
        camera_setup.make_reference(frame, camera_role='front', camera_identity='x', fps=30, intrinsics=K,
                                    layout=LAYOUT, measured={}, guides=[], reference_still='d' * 64,
                                    created_at='t', created_by='operator')
