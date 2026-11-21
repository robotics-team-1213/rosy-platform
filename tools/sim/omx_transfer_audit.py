"""Bind OMX CAD194 render and training evidence before a supervised S2R trial."""
from hashlib import sha256
import json
import math
from pathlib import Path

from PIL import Image
from omx_ladder import read_ppo_snapshot, judge_isaac_stage

CAMERAS = {"top": "top", "side": "side", "a_wrist": "arm_a_wrist", "b_wrist": "arm_b_wrist"}
RENDERS = {*CAMERAS, "overview"}
SENSOR_CLOCK = "v4l2_monotonic_start_of_exposure"
JOINT_WINDOW_S = .150
FOLLOWER_MOTORS = list(range(11, 17))


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def verify_file(path, expected):
    if digest(path) != expected:
        raise ValueError(f"Evidence fingerprint does not match: {path.name}")


def check_render(directory, capture_path, handoff):
    capture = load(capture_path)
    comparison = load(directory / "comparison.json")
    geometry = load(directory / "geometry-check.json")
    isaac = comparison["isaac"]
    request = handoff["stage_2_isaac"]
    cfg = request["two_arm_config"]
    if (request.get("two_arm_scenario") != "omx-map-container-stacking-rl"
            or not request.get("ready") or cfg["case"] != "r08-v24-cad194"
            or cfg["layout_sha256"] != geometry["layout_sha256"]
            or geometry["preset"] != "v24-20261114-cad194"
            or comparison["source_sha"] != geometry["source_sha"]
            or isaac["usd_sha256"] != geometry["usd_sha256"]
            or comparison["camera_sha256"] != geometry["camera_snapshot_sha256"]
            or isaac["isaac_sdk"] != "6.2.0.0"
            or set(isaac["views"]) != RENDERS or set(geometry["mujoco_frame_sha256"]) != RENDERS):
        raise ValueError("Render and MuJoCo handoff must describe the same CAD194 layout")
    verify_file(directory / "omx-ab-cell.usd", geometry["usd_sha256"])
    verify_file(directory / "camera-comparison.png", comparison["camera_comparison_sha256"])
    for name, view in isaac["views"].items():
        if view["camera"] != f"/World/Cameras/{name}" or view["resolution"] != [640, 480]:
            raise ValueError(f"Unexpected Isaac camera: {name}")
        verify_file(directory / f"isaac-{name}.png", view["png_sha256"])
        verify_file(directory / f"mujoco-source-{name}.png", geometry["mujoco_frame_sha256"][name])
        for engine in ("isaac", "mujoco-source"):
            with Image.open(directory / f"{engine}-{name}.png") as pixels:
                if pixels.size != (640, 480):
                    raise ValueError(f"Unexpected {engine} camera dimensions: {name}")
                pixels.verify()
    if len({view["png_sha256"] for view in isaac["views"].values()}) != len(RENDERS):
        raise ValueError("Duplicate Isaac camera frames")
    frames = []
    for name, role in CAMERAS.items():
        frame = capture["frames"][role]
        if frame.get("sha256") != comparison["real_frames"].get(name):
            raise ValueError(f"Real capture and render comparison differ: {name}")
        verify_file(capture_path.parent / f"{role}.jpg", frame["sha256"])
        frames.append(frame)
    joint_samples = capture.get("joint_samples")
    return cfg, geometry, capture_timing(frames, joint_samples)


def number_is_invalid(value):
    return type(value) not in (int, float) or not math.isfinite(value) or value <= 0


def stationary_joint_window(samples, boot, first_exposure, last_exposure):
    if not isinstance(samples, dict) or set(samples) != {"arm_a", "arm_b"}:
        raise ValueError("Joint evidence requires both A and B readbacks")
    windows = []
    for arm, pair in samples.items():
        if not isinstance(pair, dict) or set(pair) != {"before", "after"}:
            raise ValueError(f"Joint evidence requires before and after scans: {arm}")
        before, after = pair["before"], pair["after"]
        bounds = []
        positions = []
        for sample in (before, after):
            if not isinstance(sample, dict) or sample.get("boot_id") != boot:
                raise ValueError(f"Joint reads must share the camera boot: {arm}")
            start, end = sample.get("begin_monotonic_s"), sample.get("end_monotonic_s")
            if any(number_is_invalid(t) for t in (start, end)) or start >= end:
                raise ValueError(f"Invalid joint scan time: {arm}")
            bounds.extend((start, end))
            motors = sample.get("motors")
            if (not isinstance(motors, list) or not all(isinstance(m, dict) for m in motors)
                    or [m.get("id") for m in motors] != FOLLOWER_MOTORS
                    or any(type(m.get("position_raw")) is not int or type(m.get("velocity_raw")) is not int
                           or abs(m["velocity_raw"]) > 2 or m.get("torque_enabled") != 0
                           or m.get("hardware_error") != 0 for m in motors)):
                raise ValueError(f"Expected six passive joint readbacks at rest: {arm}")
            positions.append([m["position_raw"] for m in motors])
        start, before_end, after_start, end = bounds
        if not before_end <= first_exposure <= last_exposure <= after_start or end - start > JOINT_WINDOW_S:
            raise ValueError(f"Joint scans outside the camera capture window: {arm}")
        if any(abs(x - y) > 1 for x, y in zip(*positions)):
            raise ValueError(f"Joint position changed across the camera capture: {arm}")
        windows.append(end - start)
    return {"status": "stationary_bracket_verified", "max_window_ms": round(max(windows) * 1000, 3)}


def capture_timing(frames, joint_samples=None):
    if any("exposure_monotonic_s" in frame or frame.get("clock_semantics") == SENSOR_CLOCK
           for frame in frames):
        boot = frames[0].get("boot_id")
        if (not isinstance(boot, str) or not boot.strip()
                or any(frame.get("boot_id") != boot or frame.get("clock_semantics") != SENSOR_CLOCK
                       or type(frame.get("source_seq")) is not int or frame["source_seq"] < 0
                       for frame in frames)):
            raise ValueError("Real camera exposures must share the V4L2 clock and boot")
        stamp_key, span_key = "exposure_monotonic_s", "sensor_exposure_span_ms"
        timing = {"clock_semantics": SENSOR_CLOCK}
    else:
        stamp_key, span_key = "source_stamp", "host_source_stamp_span_ms"
        timing = {}
    stamps = [frame.get(stamp_key) for frame in frames]
    if any(number_is_invalid(stamp) for stamp in stamps):
        raise ValueError(f"Invalid real camera timestamp: {stamp_key}")
    first, last = min(stamps), max(stamps)
    timing[span_key] = round((last - first) * 1000, 3)
    if joint_samples is not None:
        if timing.get("clock_semantics") != SENSOR_CLOCK:
            raise ValueError("Joint evidence requires V4L2 sensor exposure timestamps")
        timing["joint_observation"] = stationary_joint_window(joint_samples, boot, first, last)
    return timing


def check_ppo(snapshot, cfg, source_sha):
    verified = read_ppo_snapshot(snapshot, cfg, source_sha)
    index = load(snapshot / "snapshot.json")
    if index.get("snapshot") != "FINAL" or index.get("run_id") != verified["run_id"]:
        raise ValueError("PPO artifact index belongs to a different run")
    items = {item["name"]: item["sha256"] for item in index["files"]}
    for name in ("stacking-report.json", "stacking-policy.pt"):
        verify_file(snapshot / name, items[name])
    checkpoint = verified["verified_ppo_report"]["checkpoint"]
    if checkpoint["sha256"] != items["stacking-policy.pt"]:
        raise ValueError("PPO checkpoint differs from its report")
    result = judge_isaac_stage(verified)
    return dict(status=result["status"], run_id=result["run_id"],
                checkpoint_sha256=checkpoint["sha256"], **result["result"])


def check_reset_evidence(start_path, joint_receipt, mujoco, isaac, capture, timing, geometry):
    from omx_paired_reset import check_readbacks, prepare_start, read_start
    import yaml

    profile = Path(__file__).resolve().parents[2] / "deploy/robot/omx/sim/cell_profile.yaml"
    limits = yaml.safe_load(profile.read_text(encoding="utf-8"))
    accepted = prepare_start(capture, joint_receipt, timing, geometry, geometry["layout_sha256"], limits)
    state = read_start(start_path, geometry["layout_sha256"], limits)
    if any(state[key] != value for key, value in accepted.items()):
        raise ValueError("paired reset source does not match the camera or joint calibration receipt")
    sdk_readback = load(isaac)
    if sdk_readback.get("sdk_version") != "6.2.0.0":
        raise ValueError("paired reset requires Isaac Sim 6.2 runtime readback")
    return dict(check_readbacks(state, load(mujoco), sdk_readback), input_sha256=state["input_sha256"],
                scope="simulation joint readbacks at reset; spatial and first-pick agreement still unverified")


def audit(render, capture, handoff, isaac_snapshot=None, *, paired_reset=None):
    cfg, geometry, timing = check_render(render, capture, load(handoff))
    ppo = (check_ppo(isaac_snapshot, cfg, geometry["source_sha"])
           if isaac_snapshot else {"status": "not_run"})
    required = ["approved camera calibration", "calibrated A/B pose alignment"]
    if "joint_observation" not in timing:
        required.append("exposure-bound A/B joint evidence")
    if paired_reset:
        timing["paired_reset"] = check_reset_evidence(*paired_reset, capture, timing, geometry)
    return {
        "schema": "rosy.omx-cad194-transfer-audit/1",
        "source_sha": geometry["source_sha"],
        "layout": cfg,
        "r2s": {
            "status": "preview_verified",
            "material_profile": geometry.get("material_profile"),
            "camera_snapshot_sha256": geometry["camera_snapshot_sha256"],
            **timing,
            "pose_alignment": "unverified",
            "required": required,
        },
        "mujoco": {"status": "handoff_verified", "targets": cfg["layers"] * 3},
        "isaac_physx": ppo,
        "s2r": {
            "status": "blocked",
            "owner": "cell_task_live_executor",
            "physical_acceptance": "pending",
            "required": ["verified real-to-sim alignment", "successful independent PhysX evaluation",
                         "supervised owner trial with calibrated release height and stop evidence"],
        },
    }
