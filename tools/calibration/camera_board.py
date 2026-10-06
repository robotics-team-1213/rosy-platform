"""Automatic checkerboard camera-pose candidates from two independent images, or from
five or more board placements stored as a camera_profile candidate (--store ROBOT).

Uses the camera profile's intrinsics as a seed; does not calibrate intrinsics,
write runtime settings, promote records, or turn board-relative height into
floor height without a declared board elevation.

PC only. Board sessions are captured on the robot by the D-379 recorder (~/rosy_rec.sh,
camera/front, robot static) and fitted here on the PC; this tool refuses to run where the
robot runtime is installed. (camera_auto/camera_capture are a different path: they run
the wall-edge fitter on the robot over SSH.)

--store ROBOT writes one candidate record through CalibrationStore.add into the PC mirror
(never accepts it): values pitch_rad, roll_rad, height_m (above the floor: the board fit
plus the declared, measured board elevation); intervals.uncertainty pitch_deg, roll_deg,
height_m, each max(across-placement ci95, half the re-seat spread) — the re-seat spread is
over the placement mean and every --reseat view; intervals.systematic, |board - truth| + the
truth tolerance from an independent check (--truth-height-mm/-pitch-deg/-roll-deg VALUE TOL;
--store refuses without it, because view scatter cannot see shared error such as distortion,
seeded intrinsics, fy=fx, print scale or elevation); intervals.fit_step all zero (solvePnP
has no grid; lane_containment adds systematic instead of a grid floor); method camera_board/1.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

# Two views (or every placement) of one static mount must agree this closely.
VIEW_HEIGHT_TOL_M = 0.002
VIEW_PITCH_TOL_DEG = 0.15
VIEW_ROLL_TOL_DEG = 0.3
MIN_PLACEMENTS = 5
METHOD = 'camera_board/1'
# The robot runtime's install root; its presence means this process runs on a robot.
ROBOT_INSTALL = Path('/opt/rosy/current')
REPO = Path(__file__).resolve().parents[2]
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
    consistent = (height_difference <= VIEW_HEIGHT_TOL_M and pitch_difference <= math.radians(VIEW_PITCH_TOL_DEG)
                  and roll_difference <= math.radians(VIEW_ROLL_TOL_DEG))
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


def placement_fit(placements, *, board_elevation_m, reseats=()):
    """Camera pose over the floor from >= MIN_PLACEMENTS board placements (robot static).

    Values are the placement means; each half-band is max(t95 * sd / sqrt(n) over the
    placements, half the spread of the placement mean and every re-seat view). The
    placements must agree within the view gate (max - min) for consistency_pass."""
    if len(placements) < MIN_PLACEMENTS:
        raise ValueError(f'need at least {MIN_PLACEMENTS} placements, got {len(placements)}')
    if board_elevation_m is None or not math.isfinite(board_elevation_m) or not 0 <= board_elevation_m <= .1:
        raise ValueError('a measured board elevation is required for a floor height')

    def column(fits, key):
        return np.array([f[key] for f in fits], float)

    n = len(placements)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from analyze_session import t95
    t = t95(n - 1)
    values, uncertainty, spread = {}, {}, {}
    for key, band, scale, tol in (('pitch_rad', 'pitch_deg', math.degrees(1), VIEW_PITCH_TOL_DEG),
                                  ('roll_rad', 'roll_deg', math.degrees(1), VIEW_ROLL_TOL_DEG),
                                  ('height_above_board_m', 'height_m', 1.0, VIEW_HEIGHT_TOL_M)):
        x = column(placements, key)
        mean = float(x.mean())
        reseat = np.append(column(reseats, key), mean) if reseats else np.array([mean])
        ci95 = t * float(x.std(ddof=1)) / math.sqrt(n)
        uncertainty[band] = max(ci95, float(reseat.max() - reseat.min()) / 2) * scale
        spread[band] = float(x.max() - x.min()) * scale
        values['height_m' if band == 'height_m' else key] = mean + (board_elevation_m if band == 'height_m' else 0.)
    consistent = (spread['height_m'] <= VIEW_HEIGHT_TOL_M and spread['pitch_deg'] <= VIEW_PITCH_TOL_DEG
                  and spread['roll_deg'] <= VIEW_ROLL_TOL_DEG)
    return {'values': values, 'uncertainty': uncertainty, 'placement_spread': spread,
            'placements': n, 'reseats': len(reseats), 'consistency_pass': consistent}


def systematic_from_truth(fit, truth):
    """Shared error of the board fit from an independent truth check: per quantity
    |board value - truth| + the truth's own tolerance. truth: {pitch_deg, roll_deg, height_m}
    -> (value, tolerance), e.g. a tape-measured lens height and a known-geometry target."""
    board = {'pitch_deg': math.degrees(fit['values']['pitch_rad']), 'roll_deg': math.degrees(fit['values']['roll_rad']),
             'height_m': fit['values']['height_m']}
    return {key: abs(board[key] - value) + tol for key, (value, tol) in truth.items()}


def store_candidate(store, robot, fit, *, systematic, sessions, extra):
    """One camera_profile candidate record (never accepted here); returns its id."""
    return store.add(robot, 'camera_profile', dict(fit['values']), sessions=sessions, method=METHOD,
                     intervals={'uncertainty': dict(fit['uncertainty']), 'systematic': dict(systematic),
                                'fit_step': {'pitch_deg': 0., 'roll_deg': 0., 'height_m': 0.},
                                'across_placements': {'n': fit['placements'], 'reseats': fit['reseats']}},
                     extra=extra)


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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--validation', type=Path)
    parser.add_argument('--placement', type=Path, action='append', default=[],
                        help=f'one board placement image (robot static); --store needs {MIN_PLACEMENTS} or more')
    parser.add_argument('--reseat', type=Path, action='append', default=[],
                        help='a board image taken after re-seating the robot; widens the bands')
    parser.add_argument('--camera-profile', type=Path, required=True)
    parser.add_argument('--square-mm', type=float, required=True)
    parser.add_argument('--board-elevation-mm', type=float)
    parser.add_argument('--board-elevation-estimated', action='store_true',
                        help='Record an approximate rather than measured board elevation')
    parser.add_argument('--store', metavar='ROBOT',
                        help='write a camera_profile candidate for ROBOT (device name) into --store-root')
    parser.add_argument('--store-root', type=Path, default=REPO / 'data' / 'calibration',
                        help='PC mirror of the calibration store (gitignored data/)')
    for key, unit in (('height', 'mm'), ('pitch', 'deg'), ('roll', 'deg')):
        parser.add_argument(f'--truth-{key}-{unit}', type=float, nargs=2, metavar=('VALUE', 'TOL'),
                            help=f'independent truth check of the {key} ({unit}) and its tolerance; --store needs all three')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if ROBOT_INSTALL.exists():
        parser.error(f'{ROBOT_INSTALL} exists: board images are fitted on the PC, not on the robot')
    from camera_auto import checked_output
    if args.board_elevation_estimated and args.board_elevation_mm is None:
        parser.error('Estimated elevation needs --board-elevation-mm')
    if args.store:
        if args.reference or args.validation:
            parser.error('--store takes --placement images, not --reference/--validation')
        if len(args.placement) < MIN_PLACEMENTS:
            parser.error(f'--store needs at least {MIN_PLACEMENTS} --placement images')
        if args.board_elevation_mm is None or args.board_elevation_estimated:
            parser.error('--store needs a measured --board-elevation-mm (not estimated)')
        truth = (args.truth_height_mm, args.truth_pitch_deg, args.truth_roll_deg)
        if any(t is None for t in truth) or not all(math.isfinite(v) for t in truth for v in t)                 or min(t[1] for t in truth) < 0:
            parser.error('--store needs an independent truth check (--truth-height-mm, --truth-pitch-deg, '
                         '--truth-roll-deg, each VALUE TOL): board scatter cannot see shared systematic error')
        return store_main(parser, args, checked_output(args.output))
    if args.placement or args.reseat:
        parser.error('--placement/--reseat are for --store')
    if args.reference is None or args.validation is None:
        parser.error('--reference and --validation are required without --store')
    output = checked_output(args.output)
    if args.reference.resolve() == args.validation.resolve():
        parser.error('Reference and validation must be independent images')
    profile, k = load_intrinsics(args.camera_profile)
    images = load_images(parser, profile, (args.reference, args.validation))
    reference = fit_image(images[0], k, args.square_mm/1000)
    validation = fit_image(images[1], k, args.square_mm/1000, seed=reference)
    result = compare_views(reference, validation, None if args.board_elevation_mm is None else args.board_elevation_mm/1000)
    result.update(reference=reference, validation=validation, **provenance(args, profile, k, {
        'reference': args.reference, 'validation': args.validation}))
    if args.board_elevation_estimated:
        result['reasons'].append('board_elevation_estimated')
    write(output, result)
    return 0 if result['view_consistency_pass'] else 2


def load_intrinsics(path):
    profile = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    k = np.array([[profile['fx'], 0, profile['cx']], [0, profile.get('fy', profile['fx']), profile['cy']], [0, 0, 1]], float)
    return profile, k


def load_images(parser, profile, paths):
    images = [cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) for path in paths]
    for image in images:
        if image is None or image.shape != (profile['height'], profile['width']):
            parser.error('Image missing or incompatible with camera-profile resolution')
    for a in range(len(images)):
        for b in range(a + 1, len(images)):
            if paths[a].resolve() == paths[b].resolve() or np.array_equal(images[a], images[b]):
                parser.error('Duplicate image pixels are not independent validation')
    return images


def provenance(args, profile, k, named):
    return dict(square_size_mm=args.square_mm,
                input_sha256={**{name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in named.items()},
                              'camera_profile': hashlib.sha256(args.camera_profile.read_bytes()).hexdigest()},
                camera_matrix=k.tolist(), distortion_source='assumed_zero',
                board_elevation_mm=args.board_elevation_mm,
                board_elevation_source=('unknown' if args.board_elevation_mm is None else
                                        'operator_estimate' if args.board_elevation_estimated else 'operator_declared'),
                intrinsics_source='existing_profile_seed', fy_source='profile' if 'fy' in profile else 'assumed_equal_to_fx')


def write(output, result):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps(result))


def store_main(parser, args, output):
    """--store: fit every placement and re-seat view, then one candidate record if the placements agree."""
    profile, k = load_intrinsics(args.camera_profile)
    paths = [*args.placement, *args.reseat]
    images = load_images(parser, profile, paths)
    first = fit_image(images[0], k, args.square_mm/1000)
    fits = [first] + [fit_image(image, k, args.square_mm/1000, seed=first) for image in images[1:]]
    placements, reseats = fits[:len(args.placement)], fits[len(args.placement):]
    fit = placement_fit(placements, board_elevation_m=args.board_elevation_mm/1000, reseats=reseats)
    systematic = systematic_from_truth(fit, {
        'height_m': (args.truth_height_mm[0]/1000, args.truth_height_mm[1]/1000),
        'pitch_deg': tuple(args.truth_pitch_deg), 'roll_deg': tuple(args.truth_roll_deg)})
    named = {f'placement_{i}': path for i, path in enumerate(args.placement)}
    named.update({f'reseat_{i}': path for i, path in enumerate(args.reseat)})
    result = {'status': 'candidate', 'applied': False, **fit, 'placement_fits': placements, 'reseat_fits': reseats,
              'systematic': systematic, **provenance(args, profile, k, named), 'store_record': None}
    if fit['consistency_pass']:
        sys.path.insert(0, str(REPO / 'contracts' / 'foundation'))
        from core_common.calibration_store import CalibrationStore
        result['store_record'] = store_candidate(
            CalibrationStore(args.store_root), args.store, fit, systematic=systematic,
            sessions=[path.name for path in paths],
            extra={'input_sha256': result['input_sha256'], 'board_elevation_mm': args.board_elevation_mm,
                   'truth': {'height_mm': args.truth_height_mm, 'pitch_deg': args.truth_pitch_deg,
                             'roll_deg': args.truth_roll_deg},
                   'square_size_mm': args.square_mm, 'placement_fits': placements, 'reseat_fits': reseats})
    write(output, result)
    return 0 if result['store_record'] else 2

if __name__ == '__main__':
    raise SystemExit(main())
