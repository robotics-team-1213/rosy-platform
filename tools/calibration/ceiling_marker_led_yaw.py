"""Calibrate from a stationary marker and a recorded Fleet lamp identification window."""
import math

from ceiling_marker_yaw import EstimateError, MAX_YAW_SPREAD_DEG, MIN_SAMPLES


def combine(cargo, led):
    """Retain an independently observed cue; require agreement when both are visible."""
    if cargo is None and led is None:
        raise EstimateError("no observable front direction")
    if cargo is None or led is None:
        return dict(cargo or led)
    delta = math.remainder(cargo["candidate_offset_deg"] - led["candidate_offset_deg"], 360)
    if abs(delta) > MAX_YAW_SPREAD_DEG:
        raise EstimateError("cargo and LED headings disagree")
    return {**cargo, "led_candidate_offset_deg": led["candidate_offset_deg"],
            "led_request_id": led["led_request_id"], "cue_difference_deg": round(delta, 2)}


def estimate_led(frames, record, *, source, marker, heading_edge, challenge, robot):
    """The challenge is the exact pending row from Fleet tracking/identity, with start and end."""
    import cv2
    import numpy as np
    from rosy_vision.detect import _DETECT_MARKERS
    from rosy_vision.project import MARKER_HEIGHT_M, ROBOT_ARUCO_SIDE_BAND_M
    from rosy_vision.track import geometry, led_identity
    from rosy_vision.track.calibration import from_record
    from rosy_vision.track.marker_sightings import marker_pose, solved_camera
    from rosy_vision.track.model import ROTATION_RADIUS_M

    if (record.get("source_id") != source or challenge.get("robot_id") != robot
            or source not in (challenge.get("sources") or [])
            or not challenge.get("request_id") or challenge.get("color") != "blue"):
        raise EstimateError("expected a named blue identification window on this camera")
    try:
        start, end = float(challenge["not_before"]), float(challenge["not_after"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EstimateError("incomplete identification window") from exc
    if not 0 < end - start <= led_identity.MAX_WINDOW_S:
        raise EstimateError("invalid identification window")

    samples, poses = [], []
    previous = -math.inf
    for stamp, jpeg in frames:
        if not start <= stamp <= end:
            continue
        if stamp <= previous:
            raise EstimateError("duplicate or unordered LED frames")
        previous = stamp
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise EstimateError("invalid LED frame")
        h, w = image.shape[:2]
        cal = from_record(record, source_id=source, map_id=record["map_id"], frame_size=(w, h), lens=record.get("lens"))
        camera = solved_camera(cal) if cal else None
        corners, ids, _ = _DETECT_MARKERS(image)
        ids = [] if ids is None else ids.ravel().tolist()
        if camera is None or ids.count(marker) != 1:
            raise EstimateError("LED frames need one marker and an approved projection")
        quad = corners[ids.index(marker)][0]
        pose = marker_pose(cal, quad, heading_edge, camera, side_band_m=ROBOT_ARUCO_SIDE_BAND_M)
        if pose is None:
            raise EstimateError("marker geometry rejected during LED observation")
        centre = quad.mean(axis=0)
        def project(points):
            pixels = geometry.undistort_points(points, cal.lens_profile)
            ground = geometry.apply(geometry.as_matrix(cal.image_to_map), pixels)
            return np.array([geometry.parallax_correct(pt, camera, MARKER_HEIGHT_M) for pt in ground])
        xy = project([centre, centre + [1, 0]])
        radius = ROTATION_RADIUS_M / np.linalg.norm(xy[1] - xy[0])
        if not math.isfinite(radius) or radius <= 0:
            raise EstimateError("invalid LED observation scale")
        if any(i != marker and np.linalg.norm(q[0].mean(axis=0) - centre) <= 2.6 * radius
               for i, q in zip(ids, corners)):
            raise EstimateError("another marker overlaps LED observation")
        blob = led_identity.Blob(*centre, radius, *pose[:2])
        samples.append(led_identity.sample_frame(image, captured_at=stamp, calibration_revision=cal.revision,
                                                  blobs=[blob], color="blue"))
        poses.append(pose)
    if len(poses) < MIN_SAMPLES or any(math.dist(p[:2], poses[0][:2]) > .02 or
            abs(math.degrees(math.remainder(p[2] - poses[0][2], 2 * math.pi))) > MAX_YAW_SPREAD_DEG for p in poses):
        raise EstimateError("stationary LED marker observations required")
    verdict = led_identity.decide(samples, not_before=start, not_after=end, now=end)
    evidence = verdict["evidence"]
    angle = evidence.get("yaw_px")
    if (verdict["state"] != "matched" or angle is None or evidence.get("yaw_confidence") != 1
            or evidence.get("mode") == "steady"):
        raise EstimateError("no unambiguous blinking front/rear LED heading")
    direction = np.array([math.cos(angle), math.sin(angle)])
    rear, front = project([centre, centre + direction])
    heading = math.atan2(front[1] - rear[1], front[0] - rear[0])
    return {"candidate_offset_deg": round(math.degrees(math.remainder(poses[-1][2] - heading, 2 * math.pi)), 2),
            "evidence": "led", "use": "candidate-only", "samples": len(poses),
            "source_id": source, "map_id": record["map_id"], "calibration_revision": cal.revision,
            "robot_id": robot, "led_request_id": challenge["request_id"]}
