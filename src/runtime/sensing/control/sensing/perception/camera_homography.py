"""Validated image-to-floor homography support.

The loader deliberately distinguishes a *candidate* from an *eligible* profile.
Small fit residuals are not enough to activate metric distance: the processed
image contract, independent holdout points and physical setup evidence must all
agree.  This module is ROS-free so the same verdict can be tested and displayed
without importing the camera driver.
"""
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class CalibrationThresholds:
    max_fit_rmse_cm: float = 0.8
    max_validation_rmse_cm: float = 1.0
    max_validation_error_cm: float = 2.0
    min_validation_points: int = 8
    min_validation_frames: int = 2
    min_validation_span_cm: float = 10.0
    max_range_m: float = 0.6

    def valid(self):
        """Keep tuning useful without admitting disable-by-extreme-value knobs."""
        return (
            _between(self.max_fit_rmse_cm, 0.05, 5.0)
            and _between(self.max_validation_rmse_cm, 0.05, 10.0)
            and _between(self.max_validation_error_cm, 0.1, 20.0)
            and isinstance(self.min_validation_points, int)
            and 4 <= self.min_validation_points <= 200
            and isinstance(self.min_validation_frames, int)
            and 2 <= self.min_validation_frames <= 20
            and _between(self.min_validation_span_cm, 3.0, 100.0)
            and _between(self.max_range_m, 0.05, 3.0)
        )

    def as_dict(self):
        return {
            'max_fit_rmse_cm': _json_number(self.max_fit_rmse_cm),
            'max_validation_rmse_cm': _json_number(self.max_validation_rmse_cm),
            'max_validation_error_cm': _json_number(self.max_validation_error_cm),
            'min_validation_points': int(self.min_validation_points),
            'min_validation_frames': int(self.min_validation_frames),
            'min_validation_span_cm': _json_number(self.min_validation_span_cm),
            'max_range_m': _json_number(self.max_range_m),
        }


class HomographyGroundPlane:
    """Map processed image pixels to metric floor coordinates.

    Matrix outputs are centimetres. Runtime pixels are scaled back into the
    calibration image only when the evaluator explicitly admitted a uniform
    resize.  A board-relative X coordinate never becomes robot lateral.
    """

    def __init__(self, matrix, *, runtime_image_size, profile_image_size,
                 min_range_m, max_range_m, lateral_robot_frame,
                 denominator_epsilon=1e-8):
        self.matrix = tuple(tuple(float(value) for value in row) for row in matrix)
        self.runtime_image_size = tuple(int(value) for value in runtime_image_size)
        self.profile_image_size = tuple(int(value) for value in profile_image_size)
        self.min_range_m = float(min_range_m)
        self.max_range_m = float(max_range_m)
        self.lateral_robot_frame = bool(lateral_robot_frame)
        self.denominator_epsilon = float(denominator_epsilon)
        self._scale_x = self.profile_image_size[0] / self.runtime_image_size[0]
        self._scale_y = self.profile_image_size[1] / self.runtime_image_size[1]

    def _project(self, column, row):
        try:
            u = float(column) * self._scale_x
            v = float(row) * self._scale_y
        except (TypeError, ValueError, OverflowError):
            return None
        if not _finite(u, v):
            return None
        h = self.matrix
        denominator = h[2][0] * u + h[2][1] * v + h[2][2]
        if not _finite(denominator) or abs(denominator) <= self.denominator_epsilon:
            return None
        x_cm = (h[0][0] * u + h[0][1] * v + h[0][2]) / denominator
        y_cm = (h[1][0] * u + h[1][1] * v + h[1][2]) / denominator
        if not _finite(x_cm, y_cm):
            return None
        return x_cm / 100.0, y_cm / 100.0

    def distance(self, row, column=None):
        if column is None:
            column = self.runtime_image_size[0] / 2.0
        point = self._project(column, row)
        if point is None:
            return None
        metres = point[1]
        if metres < self.min_range_m or metres > self.max_range_m:
            return None
        return metres

    def lateral(self, column, row):
        if not self.lateral_robot_frame:
            return None
        point = self._project(column, row)
        if point is None or self.distance(row, column) is None:
            return None
        return point[0]

    def region_distance(self, bbox_xyxy):
        try:
            left, right, bottom = bbox_xyxy[0], bbox_xyxy[2], bbox_xyxy[3]
            column = (float(left) + float(right)) / 2.0
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        return self.distance(bottom, column)


@dataclass
class HomographyEvaluation:
    candidate: bool
    eligible: bool
    checks: dict
    metrics: dict = field(default_factory=dict)
    model: object = None
    source: str = ''
    source_sha256: str = ''
    method: str = ''
    profile_status: str = ''
    lateral_available: bool = False
    validated_range_m: list = field(default_factory=list)
    thresholds: CalibrationThresholds = field(default_factory=CalibrationThresholds)

    def status(self, enabled_requested=False, mode='homography'):
        active = bool(enabled_requested and self.eligible and self.model is not None)
        if not self.candidate:
            reason = 'profile_missing'
        elif not self.eligible:
            reason = 'validation_failed'
        elif not enabled_requested:
            reason = 'disabled'
        else:
            reason = 'active'
        return {
            'mode': str(mode),
            'candidate': bool(self.candidate),
            'eligible': bool(self.eligible),
            'enabled_requested': bool(enabled_requested),
            'active': active,
            'reason': reason,
            'source': self.source,
            'source_sha256': self.source_sha256,
            'method': self.method,
            'profile_status': self.profile_status,
            'checks': self.checks,
            'metrics': self.metrics,
            'validated_range_m': list(self.validated_range_m),
            'lateral_available': bool(self.lateral_available),
            'thresholds': self.thresholds.as_dict(),
            'session_only': True,
        }


def evaluate_homography_profile(profile, *, runtime_image_size,
                                 runtime_rotate_deg, runtime_profile_revision,
                                 thresholds=None, allow_uniform_resize=False,
                                 source='', source_sha256=''):
    thresholds = thresholds or CalibrationThresholds()
    checks = {}

    def check(name, passed, detail):
        checks[name] = {'passed': bool(passed), 'detail': str(detail)}
        return bool(passed)

    if not isinstance(profile, dict):
        check('profile_loaded', False, 'missing_or_invalid_json')
        return HomographyEvaluation(False, False, checks, source=source,
                                    source_sha256=source_sha256,
                                    thresholds=thresholds)
    check('profile_loaded', True, 'loaded')
    method = str(profile.get('method', ''))
    schema_ok = (isinstance(profile.get('version'), int)
                 and profile.get('version') >= 2
                 and 'homography' in method)
    check('schema', schema_ok, 'supported' if schema_ok else 'unsupported_schema')
    status = str(profile.get('status', ''))
    check('validated_status', status == 'validated', status or 'missing')
    check('thresholds', thresholds.valid(), 'bounded' if thresholds.valid() else 'out_of_bounds')

    matrix = _matrix(profile.get('image_to_ground_homography'))
    matrix_ok = matrix is not None and abs(_determinant(matrix)) > 1e-12
    check('matrix', matrix_ok, 'finite_nonsingular' if matrix_ok else 'invalid_or_singular')

    profile_size = _size(profile.get('image_size'))
    runtime_size = _size(runtime_image_size)
    exact_size = profile_size is not None and profile_size == runtime_size
    resize_ok = False
    resize_detail = 'mismatch'
    if profile_size and runtime_size and allow_uniform_resize:
        sx = runtime_size[0] / profile_size[0]
        sy = runtime_size[1] / profile_size[1]
        resize_ok = abs(sx - sy) <= 1e-9 and sx > 0
        if resize_ok:
            resize_detail = f'uniform_resize_{sx:.6f}'
    rotation_ok = profile.get('processed_rotate_deg') == int(runtime_rotate_deg)
    revision_ok = profile.get('camera_profile_revision') == str(runtime_profile_revision)
    contract_ok = (exact_size or resize_ok) and rotation_ok and revision_ok
    check('image_contract', contract_ok,
          'exact' if contract_ok and exact_size else resize_detail if contract_ok else 'mismatch')

    intrinsic = profile.get('intrinsic_calibration', {})
    intrinsic_ok = (
        isinstance(intrinsic, dict)
        and bool(str(intrinsic.get('revision', '')).strip())
        and bool(str(intrinsic.get('distortion_model', '')).strip())
        and intrinsic.get('points_undistorted') is True
        and _size(intrinsic.get('image_size')) == profile_size
    )
    check('intrinsic_calibration', intrinsic_ok,
          'undistorted_points_bound' if intrinsic_ok else
          'missing_or_distorted_point_contract')

    coordinates = profile.get('coordinates', {})
    x_description = str(coordinates.get('x', '')).lower()
    y_description = str(coordinates.get('y', '')).lower()
    coordinates_ok = 'forward' in y_description and ('cm' in y_description or 'centimet' in y_description)
    lateral_robot_frame = ('robot lateral' in x_description
                           and 'not robot lateral' not in x_description)
    check('coordinates', coordinates_ok,
          'forward_cm_robot_lateral' if lateral_robot_frame else
          'forward_cm_lateral_unavailable' if coordinates_ok else 'unsupported')

    fit = _residuals(profile.get('reference_frames'), matrix)
    fit_ok = (fit['points'] >= 4 and fit['rmse_cm'] is not None
              and fit['rmse_cm'] <= float(thresholds.max_fit_rmse_cm))
    check('reference_fit', fit_ok,
          _metric_detail(fit, thresholds.max_fit_rmse_cm, 'rmse'))

    validation = _residuals(profile.get('validation_frames'), matrix)
    reference_names = _frame_names(profile.get('reference_frames'))
    validation_names = _frame_names(profile.get('validation_frames'))
    names_independent = bool(validation_names and reference_names.isdisjoint(validation_names))
    validation_ok = (
        names_independent
        and validation['points'] >= int(thresholds.min_validation_points)
        and validation['frames'] >= int(thresholds.min_validation_frames)
        and validation['span_cm'] >= float(thresholds.min_validation_span_cm)
        and validation['rmse_cm'] is not None
        and validation['rmse_cm'] <= float(thresholds.max_validation_rmse_cm)
        and validation['max_error_cm'] <= float(thresholds.max_validation_error_cm)
    )
    check('independent_validation', validation_ok,
          _metric_detail(validation, thresholds.max_validation_rmse_cm, 'holdout')
          if names_independent else 'overlapping_or_missing_images')

    physical = profile.get('physical_validation', {})
    physical_keys = ('square_size_measured', 'board_flat', 'camera_mount_locked',
                     'robot_forward_axis_checked')
    physical_ok = isinstance(physical, dict) and all(physical.get(key) is True for key in physical_keys)
    check('physical_validation', physical_ok,
          'complete' if physical_ok else 'missing_required_attestation')

    metrics = {
        'fit_points': fit['points'],
        'fit_rmse_cm': fit['rmse_cm'],
        'fit_max_error_cm': fit['max_error_cm'],
        'validation_points': validation['points'],
        'validation_frames': validation['frames'],
        'validation_span_cm': validation['span_cm'],
        'validation_rmse_cm': validation['rmse_cm'],
        'validation_max_error_cm': validation['max_error_cm'],
    }
    essential = ('profile_loaded', 'schema', 'validated_status', 'thresholds',
                 'matrix', 'image_contract', 'intrinsic_calibration',
                 'coordinates', 'reference_fit',
                 'independent_validation', 'physical_validation')
    eligible = all(checks[name]['passed'] for name in essential)
    ground_y = validation['ground_y_cm']
    validated_range = ([min(ground_y) / 100.0, max(ground_y) / 100.0]
                       if ground_y else [])
    model = None
    if eligible and validated_range:
        model = HomographyGroundPlane(
            matrix, runtime_image_size=runtime_size,
            profile_image_size=profile_size,
            min_range_m=max(0.0, validated_range[0]),
            max_range_m=min(float(thresholds.max_range_m), validated_range[1]),
            lateral_robot_frame=lateral_robot_frame,
        )
    return HomographyEvaluation(
        candidate=matrix is not None,
        eligible=eligible and model is not None,
        checks=checks,
        metrics=metrics,
        model=model,
        source=str(source),
        source_sha256=str(source_sha256),
        method=method,
        profile_status=status,
        lateral_available=lateral_robot_frame,
        validated_range_m=validated_range,
        thresholds=thresholds,
    )


def load_homography_profile(path, **kwargs):
    source = str(path or '')
    if not source:
        return evaluate_homography_profile(None, source='', **kwargs)
    try:
        raw = Path(source).read_bytes()
        profile = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return evaluate_homography_profile(None, source=source, **kwargs)
    return evaluate_homography_profile(
        profile, source=source, source_sha256=hashlib.sha256(raw).hexdigest(), **kwargs)


def _residuals(frames, matrix):
    errors = []
    ground_y = []
    if matrix is None or not isinstance(frames, list):
        return {'frames': 0, 'points': 0, 'rmse_cm': None,
                'max_error_cm': None, 'span_cm': 0.0, 'ground_y_cm': []}
    valid_frames = 0
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        pixels = frame.get('pixel_points')
        grounds = frame.get('ground_points_cm')
        if not isinstance(pixels, list) or not isinstance(grounds, list) or len(pixels) != len(grounds):
            continue
        before = len(errors)
        for pixel, expected in zip(pixels, grounds):
            actual = _project(matrix, pixel)
            target = _point(expected)
            if actual is None or target is None:
                continue
            errors.append(math.hypot(actual[0] - target[0], actual[1] - target[1]))
            ground_y.append(target[1])
        if len(errors) > before:
            valid_frames += 1
    if not errors:
        return {'frames': 0, 'points': 0, 'rmse_cm': None,
                'max_error_cm': None, 'span_cm': 0.0, 'ground_y_cm': []}
    return {
        'frames': valid_frames,
        'points': len(errors),
        'rmse_cm': math.sqrt(sum(error * error for error in errors) / len(errors)),
        'max_error_cm': max(errors),
        'span_cm': max(ground_y) - min(ground_y),
        'ground_y_cm': ground_y,
    }


def _metric_detail(metric, threshold, label):
    if metric['rmse_cm'] is None:
        return 'missing_points'
    return (f'{label}_frames={metric["frames"]},points={metric["points"]},'
            f'span_cm={metric["span_cm"]:.6f},rmse_cm={metric["rmse_cm"]:.6f},'
            f'max_cm={metric["max_error_cm"]:.6f},threshold_cm={float(threshold):.6f}')


def _frame_names(frames):
    if not isinstance(frames, list):
        return set()
    return {str(frame.get('image')) for frame in frames
            if isinstance(frame, dict) and frame.get('image')}


def _project(matrix, point):
    point = _point(point)
    if matrix is None or point is None:
        return None
    u, v = point
    denominator = matrix[2][0] * u + matrix[2][1] * v + matrix[2][2]
    if not _finite(denominator) or abs(denominator) <= 1e-12:
        return None
    return (
        (matrix[0][0] * u + matrix[0][1] * v + matrix[0][2]) / denominator,
        (matrix[1][0] * u + matrix[1][1] * v + matrix[1][2]) / denominator,
    )


def _matrix(value):
    if not isinstance(value, list) or len(value) != 3:
        return None
    try:
        matrix = tuple(tuple(float(item) for item in row) for row in value)
    except (TypeError, ValueError, OverflowError):
        return None
    if any(len(row) != 3 for row in matrix) or not _finite(*(item for row in matrix for item in row)):
        return None
    return matrix


def _determinant(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _size(value):
    try:
        width, height = int(value[0]), int(value[1])
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _point(value):
    try:
        point = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    return point if _finite(*point) else None


def _between(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(value) and low <= value <= high


def _finite(*values):
    try:
        return all(math.isfinite(float(value)) for value in values)
    except (TypeError, ValueError, OverflowError):
        return False


def _json_number(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None
