"""Automatic checkerboard camera-pose candidates from two independent images.

Uses the camera profile's intrinsics as a seed; does not calibrate intrinsics,
write runtime settings, promote records, or turn board-relative height into
floor height without a declared board elevation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
import yaml

SHAPES = ((9, 6), (8, 6), (8, 5), (7, 5), (6, 5), (7, 4), (6, 4), (5, 4), (4, 3))


def fit_corners(points, shape, k, square_m):
    points = np.asarray(points, np.float64).reshape(-1, 2)
    k = np.asarray(k, np.float64)
    if (not math.isfinite(square_m) or not 0 < square_m <= .1
            or len(points) < 12 or len(points) != shape[0]*shape[1]
            or not np.isfinite(points).all() or k.shape != (3, 3)
            or not np.isfinite(k).all() or k[0, 0] <= 0 or k[1, 1] <= 0
            or not np.allclose(k[2], [0, 0, 1])):
        raise ValueError('Invalid board scale, corners or intrinsics')
    obj = np.zeros((len(points), 3), np.float64)
    obj[:, :2] = np.mgrid[0:shape[0], 0:shape[1]].T.reshape(-1, 2)*square_m
    solutions = cv2.solvePnPGeneric(obj, points, k, None, flags=cv2.SOLVEPNP_IPPE)
    poses = []
    for rv, tv in zip(solutions[1], solutions[2]):
        rotation, _ = cv2.Rodrigues(rv)
        centre = (-rotation.T@tv).reshape(3)
        if not np.isfinite(centre).all() or not np.all((rotation@obj.T+tv)[2] > 0):
            continue
        normal = rotation[:, 2]*(1 if centre[2] > 0 else -1)
        predicted, _ = cv2.projectPoints(obj, rv, tv, k, None)
        error = np.linalg.norm(predicted.reshape(-1, 2)-points, axis=1)
        poses.append({'height_above_board_m': abs(float(centre[2])),
                      'pitch_rad': math.atan2(-float(normal[2]), math.hypot(float(normal[0]), float(normal[1]))),
                      'roll_rad': math.atan2(float(normal[0]), -float(normal[1])),
                      'rmse_px': float(np.sqrt(np.mean(error**2))),
                      'max_error_px': float(error.max()), 'corners': len(points), 'shape': list(shape)})
    poses.sort(key=lambda p: p['rmse_px'])
    if not poses or poses[0]['rmse_px'] > 1 or poses[0]['max_error_px'] > 2:
        raise ValueError('Original-image reprojection error too high')
    if len(poses) > 1 and poses[1]['rmse_px']-poses[0]['rmse_px'] < .2:
        raise ValueError('Planar pose ambiguous')
    best = poses[0]
    if not .005 < best['height_above_board_m'] < .2 or not 0 <= best['pitch_rad'] < math.radians(45):
        raise ValueError('Board pose outside floor-camera range')
    return best


def compare_views(reference, validation, board_elevation_m):
    if board_elevation_m is not None and (not math.isfinite(board_elevation_m) or not 0 <= board_elevation_m <= .1):
        raise ValueError('Invalid board elevation')
    height_difference = abs(reference['height_above_board_m']-validation['height_above_board_m'])
    pitch_difference = abs(reference['pitch_rad']-validation['pitch_rad'])
    roll_delta = reference['roll_rad']-validation['roll_rad']
    roll_difference = abs(math.atan2(math.sin(roll_delta), math.cos(roll_delta)))
    consistent = height_difference <= .005 and pitch_difference <= math.radians(.3) and roll_difference <= math.radians(1.5)
    reasons = ['intrinsics_seed_not_newly_calibrated']
    if not consistent:
        reasons.append('view_geometry_disagrees')
    if board_elevation_m is None:
        reasons.append('board_elevation_unknown')
    height = (reference['height_above_board_m']+validation['height_above_board_m'])/2
    return {'status': 'candidate', 'applied': False, 'view_consistency_pass': consistent,
            'height_above_board_m': height,
            'height_above_floor_m': None if board_elevation_m is None else height+board_elevation_m,
            'pitch_rad': (reference['pitch_rad']+validation['pitch_rad'])/2,
            'roll_rad': reference['roll_rad'] + math.atan2(math.sin(-roll_delta), math.cos(-roll_delta))/2,
            'height_difference_m': height_difference, 'pitch_difference_deg': math.degrees(pitch_difference),
            'roll_difference_deg': math.degrees(roll_difference), 'reasons': reasons}


def fit_image(gray, k, square_m, seed=None):
    images = [(gray, None)]
    if seed:
        pitch, roll, height = seed['pitch_rad'], seed.get('roll_rad', 0), seed['height_above_board_m']
        tilt = np.array([[1, 0, 0], [0, -math.sin(pitch), height*math.cos(pitch)],
                         [0, math.cos(pitch), height*math.sin(pitch)]])
        rotate = np.array([[math.cos(roll), -math.sin(roll), 0], [math.sin(roll), math.cos(roll), 0], [0, 0, 1]])
        canvas_to_ground = np.array([[.001, 0, -.2], [0, -.001, .5], [0, 0, 1]])
        canvas_to_image = k@rotate@tilt@canvas_to_ground
        rectified = cv2.warpPerspective(gray, np.linalg.inv(canvas_to_image), (400, 450))
        images.append((rectified, canvas_to_image))
    fits = []
    for image, transform in images:
        for shape in SHAPES:
            ok, points = cv2.findChessboardCornersSB(image, shape, cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_ACCURACY)
            if not ok:
                continue
            points = points.astype(np.float64).reshape(-1, 1, 2)
            if transform is not None:
                points = cv2.perspectiveTransform(points, transform)
            try:
                fit = fit_corners(points, shape, k, square_m)
            except ValueError:
                continue
            fit['detection'] = 'rectified' if transform is not None else 'direct'
            fits.append(fit)
    if not fits:
        raise ValueError('No unambiguous checkerboard with acceptable original-image reprojection')
    return sorted(fits, key=lambda p: (-p['corners'], p['rmse_px']))[0]


def main(argv=None):
    from camera_auto import checked_output
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--camera-profile', type=Path, required=True)
    parser.add_argument('--square-mm', type=float, required=True)
    parser.add_argument('--board-elevation-mm', type=float)
    parser.add_argument('--board-elevation-estimated', action='store_true',
                        help='Record an approximate rather than measured board elevation')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.board_elevation_estimated and args.board_elevation_mm is None:
        parser.error('Estimated elevation needs --board-elevation-mm')
    output = checked_output(args.output)
    if args.reference.resolve() == args.validation.resolve():
        parser.error('Reference and validation must be independent images')
    profile = yaml.safe_load(args.camera_profile.read_text(encoding='utf-8-sig'))
    k = np.array([[profile['fx'], 0, profile['cx']], [0, profile.get('fy', profile['fx']), profile['cy']], [0, 0, 1]], float)
    images = [cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) for path in (args.reference, args.validation)]
    for image in images:
        if image is None or image.shape != (profile['height'], profile['width']):
            parser.error('Image missing or incompatible with camera-profile resolution')
    if np.array_equal(images[0], images[1]):
        parser.error('Duplicate image pixels are not independent validation')
    reference = fit_image(images[0], k, args.square_mm/1000)
    validation = fit_image(images[1], k, args.square_mm/1000, seed=reference)
    result = compare_views(reference, validation, None if args.board_elevation_mm is None else args.board_elevation_mm/1000)
    result.update(reference=reference, validation=validation, square_size_mm=args.square_mm,
                  input_sha256={name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for name, path in (('reference', args.reference), ('validation', args.validation),
                                                   ('camera_profile', args.camera_profile))},
                  camera_matrix=k.tolist(), distortion_source='assumed_zero',
                  board_elevation_mm=args.board_elevation_mm,
                  board_elevation_source=('unknown' if args.board_elevation_mm is None else
                                          'operator_estimate' if args.board_elevation_estimated else 'operator_declared'),
                  intrinsics_source='existing_profile_seed', fy_source='profile' if 'fy' in profile else 'assumed_equal_to_fx')
    if args.board_elevation_estimated:
        result['reasons'].append('board_elevation_estimated')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps(result))
    return 0 if result['view_consistency_pass'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
