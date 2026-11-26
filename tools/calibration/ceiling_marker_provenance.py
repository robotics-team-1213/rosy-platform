"""Validate ceiling camera identity, calibration provenance and raw frame geometry."""

import math
import os
import re
from pathlib import Path

from ceiling_marker_yaw import EstimateError


def check_cargo_record(record: dict, *, source: str, revision: str | None) -> None:
    if (not revision or record.get("source_id") != source or record.get("calibration_revision") != revision
            or not record.get("map_id") or not record.get("approved_by")):
        raise EstimateError("need the source's approved calibration record at the capture revision")


def check_candidate_identity(*, source: str, robot: str, marker: int,
                             site_camera_config: str | Path | None = None,
                             live_markers: dict | None = None) -> str:
    if live_markers is not None:
        expected, provenance = live_markers.get(robot), "fleet_source_config"
    elif site_camera_config is not None:
        import yaml

        try:
            config = yaml.safe_load(Path(site_camera_config).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise EstimateError("cannot read the supplied site camera configuration") from exc
        rows = config.get("sources") if isinstance(config, dict) else None
        sources = [row for row in rows if isinstance(row, dict) and row.get("source_id") == source] \
            if isinstance(rows, list) else []
        markers = sources[0].get("robot_markers") if len(sources) == 1 else None
        if not isinstance(markers, dict):
            raise EstimateError("site camera configuration has no explicit source marker binding")
        expected, provenance = markers.get(robot), "operator_supplied_site_config"
    else:
        match = re.fullmatch(r"rosy_(4[0-9])", robot)
        expected, provenance = int(match[1]) if match else None, "d562_robot_number"
    if type(expected) is not int or expected != marker:
        raise EstimateError("robot and marker do not match the source marker binding")
    return provenance


def check_candidate_source(fleet, token, context, *, source, robot, marker, revision,
                           site_camera_config, request, approved_record) -> tuple[dict, dict]:
    record = approved_record(fleet, token, context, source)
    check_cargo_record(record, source=source, revision=revision)
    tracking = request(fleet, "/api/fleet/tracking", token, context).get("sources", [])
    row = next((row for row in tracking if row.get("source_id") == source), {})
    if (row.get("status") != "OK" or row.get("calibration_revision") != revision
            or row.get("map_id") != record["map_id"]):
        raise EstimateError("live tracking source is not using the approved capture revision")
    health = row.get("calibration_health") or {}
    health_state = health.get("state", "unknown")
    if (health.get("calibration_revision") not in (None, revision) or health.get("blocking")
            or health_state in ("drifting", "mismatch", "insufficient_coverage")):
        raise EstimateError("live source reports incompatible calibration health")

    source_token = os.environ.get("ROSY_VISION_SOURCE_TOKEN")
    live_markers = None
    if source_token:
        config = request(fleet, "/api/fleet/detections/config", source_token, context)
        live_markers = config.get("robot_markers")
        if (config.get("source_id") != source or config.get("map_id") != record["map_id"]
                or (config.get("calibration") or {}).get("calibration_revision") != revision
                or not isinstance(live_markers, dict)):
            raise EstimateError("Vision source configuration is incompatible with the approved record")
    identity = check_candidate_identity(source=source, robot=robot, marker=marker,
                                        site_camera_config=site_camera_config, live_markers=live_markers)
    return record, {"marker_binding_provenance": identity, "capture_provenance": "live_raw_preview_headers",
                    "calibration_health": health_state}


def live_frame_stamp(headers, record, *, expected_rotation: int | None = None) -> float | None:
    """Validate geometry of sensor-raw pixels. The rotation header does not rotate the JPEG."""
    from rosy_vision.protocol import VALID_ROTATIONS
    from rosy_vision.track.calibration import same_lens

    if headers.get("X-Frame-Rectified") != "false":
        raise EstimateError("candidate heading needs raw, unrectified frames")
    try:
        age_ms = float(headers.get("X-Frame-Age-Ms", "nan"))
        stamp = float(headers.get("X-Frame-Captured-At", "nan"))
        rotation = int(headers["X-Frame-Rotation-Deg"])
        size = (int(headers["X-Frame-Width"]), int(headers["X-Frame-Height"]))
        lens = dict(field.split("=", 1) for field in headers["X-Source-Lens"].split(";"))
        approved_size = (record["image"]["width"], record["image"]["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EstimateError("missing source metadata for the approved frame geometry") from exc
    if (rotation not in VALID_ROTATIONS or rotation != record.get("rotation_deg", rotation)
            or (expected_rotation is not None and rotation != expected_rotation)
            or size != approved_size or not same_lens(lens, record.get("lens"))):
        raise EstimateError("live capture does not match the approved frame geometry")
    return stamp if math.isfinite(stamp) and 0 <= age_ms <= 1000 else None
