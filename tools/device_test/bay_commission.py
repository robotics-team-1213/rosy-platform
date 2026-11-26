"""Measure a stationary native bay line against an independently surveyed stop face."""
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import quote

from run_helpers import Abort
from tether import wrap


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _pose(pose):
    if not isinstance(pose, dict) or not all(_finite(pose.get(k)) for k in ("x", "y", "yaw")):
        raise Abort("a metric pose with x, y and yaw is required")
    return {k: pose[k] for k in ("x", "y", "yaw")}


def _stationary(state):
    evidence, velocity = state.get("evidence") or {}, state.get("velocity") or {}
    if (state.get("mode") != "IDLE" or state.get("pose_frame") != "map" or (state.get("localization") or {}).get("state") != "LOCALIZED"
            or not all((evidence.get(k) or {}).get("evidence") == "fresh" for k in ("velocity", "pose"))
            or not all(_finite(velocity.get(k)) and velocity[k] == 0 for k in ("linear", "angular"))
            or state.get("navigation") not in {"IDLE", "ARRIVED", "CANCELED", "FAILED"} or (state.get("line_follow") or {}).get("mode") != "OFF"):
        raise Abort("native stationarity unverified: mode=%s nav=%s localization=%s (%s) velocity=%s line=%s"
                    % (state.get("mode"), state.get("navigation"), (state.get("localization") or {}).get("state"),
                       (state.get("localization") or {}).get("reason"), velocity, (state.get("line_follow") or {}).get("mode")))
    return _pose(state.get("pose"))


def _agree(a, b, translation_m, heading_rad):
    return (math.hypot(a["x"]-b["x"], a["y"]-b["y"]) <= translation_m
            and abs(wrap(a["yaw"]-b["yaw"])) <= heading_rad)


def _binding(run, rid, grid):
    view = json.loads(run.r._site("/api/fleet/robots/"+quote(rid, safe="")+"/map-binding",
                                  token=run.r._site_token()))
    b = view.get("active") or {}
    if (view.get("matches") is not True or b.get("robot_id") != rid or b.get("robot_grid_id") != grid
            or not b.get("binding_id") or not b.get("approved_by")):
        raise Abort("no currently matching approved Fleet binding for this robot grid")
    return b


def measure(run, bay, report):
    from bay_dock import BAY_TYPE, MIN_OBS, OBS_POLL_S, OBS_WINDOW_S, check_bay_verdict, dock_pose, summarize_observations

    state = run.get("/robot/state")
    rid, grid, map_id = (state.get(k) for k in ("robot_id", "map_grid_id", "map_id"))
    report.update(robot_id=rid, map_grid_id=grid, map_id=map_id)
    report["stationary_check"] = {k:state.get(k) for k in ("mode", "navigation", "velocity", "localization",
                                                           "pose_frame", "map_generation", "line_follow", "evidence")}
    report["last_observation"] = run.get("/sensors/dock_observation")
    initial = _stationary(state)
    if not rid or not grid or not map_id or type(state.get("map_generation")) is not int:
        raise Abort("native robot identity, map and grid are required")
    observations = []
    stamps = set()
    end = run.r.now() + OBS_WINDOW_S
    while run.r.now() <= end and len(observations) < MIN_OBS:
        sample = run.get("/sensors/dock_observation")
        report["last_observation"] = sample
        stamp = sample.get("stamp")
        if (sample.get("source") == "CAMERA_LINE" and sample.get("evidence") == "fresh"
                and sample.get("visible") is True and sample.get("along_measured") is True
                and sample.get("lateral_measured", True) is True and _finite(stamp) and stamp not in stamps
                and all(_finite(sample.get(k)) for k in ("x", "y", "yaw"))):
            stamps.add(stamp)
            observations.append(sample)
        run.r.sleep(OBS_POLL_S)
    report["observations"] = observations
    summary = summarize_observations(observations)
    if not summary["ok"]:
        raise Abort(summary["reason"])
    current = run.get("/robot/state")
    pose = _stationary(current)
    if not _agree(initial, pose, .01, math.radians(2)) or any(current.get(k) != state[k] for k in ("robot_id", "map_id", "map_grid_id", "map_generation")):
        raise Abort("robot moved or native frame changed while sampling")
    binding = _binding(run, rid, grid)
    if not run.args.bay_verdict:
        raise Abort("need the independent survey and current robot/bay identification in --bay-verdict")
    verdict_path = Path(run.args.bay_verdict)
    v = check_bay_verdict(json.loads(verdict_path.read_text(encoding="utf-8")))
    if (v.get("robot_id") != rid or v["bay_id"] != bay or v.get("site_map_id") != binding["site_map_id"]
            or v.get("site_map_version") != binding["site_map_version"]
            or not _finite(v.get("observed_at")) or not 0 <= run.r.now()-v["observed_at"] <= 120):
        raise Abort("the current observation must identify this robot, bay, site frame and time")
    survey = v.get("survey") or {}
    if survey.get("method") != "field_measurement" or not survey.get("measured_by"):
        raise Abort("need an independently measured stop face with survey.method=field_measurement and measured_by")
    reference = _pose(survey.get("stop_face_site"))
    artifact = (verdict_path.parent / survey["artifact"]).read_bytes()
    digest = hashlib.sha256(artifact).hexdigest()
    if not artifact or survey.get("sha256") != digest:
        raise Abort("survey artifact digest mismatch")
    native = dock_pose(pose, summary["median"])
    fit = binding["fit"]
    origin = {"x":fit["tx"], "y":fit["ty"], "yaw":fit["yaw"]}
    projected = dock_pose(origin, native)
    report.update(projected_stop_face=projected, survey_stop_face=reference, binding_id=binding["binding_id"])
    # Accuracy gate for a permanent pose, independent of the observer's nominal ground projection.
    if (not _agree(projected, reference, .02, math.radians(5))
            or any(not _agree(summary["median"], sample, .02, math.radians(5)) for sample in observations)):
        raise Abort("line estimate disagrees with the independent stop face or its repeated measurements")
    if abs(wrap(summary["median"]["yaw"]-math.pi)) > math.radians(10):
        raise Abort("observation does not face the rear docking direction")
    metadata = {"commissioned_grid_id":grid, "binding_id":binding["binding_id"], "survey_sha256":digest,
                "site_map_id":binding["site_map_id"], "bay_id":bay}
    body = {"robot_id":rid, "map_id":map_id, "map_grid_id":grid, "map_generation":state["map_generation"], "dock_type":BAY_TYPE,
            "dock":{"id":run.args.dock_id, "type":BAY_TYPE["name"], "map_id":map_id, **native, "metadata":metadata}}
    report["candidate"] = body
    if run.args.apply_commission:
        last = run.get("/robot/state")
        if (not _agree(_stationary(last), pose, .01, math.radians(2))
                or any(last.get(k) != state[k] for k in ("robot_id","map_id","map_grid_id","map_generation"))
                or _binding(run, rid, grid)["binding_id"] != binding["binding_id"]):
            raise Abort("robot or approved site binding changed before registration")
        code, receipt = run.post("/docking/commission", body)
        if code != 200 or not isinstance(receipt, dict) or receipt.get("id") != body["dock"]["id"]:
            raise Abort(f"registration refused ({code}): {receipt}")
        report["registered"] = receipt


def commission_only(run):
    report = {"registered": None}
    try:
        bay = run.args.dock_id.removeprefix("bay_").upper()
        if bay not in ("C1", "C2", "C3") or run.args.dock_id != "bay_"+bay.lower():
            raise Abort("select bay_c1, bay_c2 or bay_c3")
        measure(run, bay, report)
    except (Abort, KeyError, ValueError, OSError, TypeError) as exc:
        report["reason"] = str(exc)
    path = run.ev / "commission.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{path}: {report.get('reason') or ('registered' if report['registered'] else 'dry-run ready')}")
    return int("reason" in report)
