"""Bind OMX CAD194 render and training evidence before a supervised S2R trial."""
from hashlib import sha256
import json
import math

from PIL import Image
from omx_ladder import read_ppo_snapshot, judge_isaac_stage

CAMERAS = {"top": "top", "side": "side", "a_wrist": "arm_a_wrist", "b_wrist": "arm_b_wrist"}
RENDERS = {*CAMERAS, "overview"}
SENSOR_CLOCK = "v4l2_monotonic_start_of_exposure"


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
    return cfg, geometry, capture_timing(frames)


def number_is_invalid(value):
    return type(value) not in (int, float) or not math.isfinite(value) or value <= 0


def capture_timing(frames):
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
    timing[span_key] = round((max(stamps) - min(stamps)) * 1000, 3)
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


def audit(render, capture, handoff, isaac_snapshot=None):
    cfg, geometry, timing = check_render(render, capture, load(handoff))
    ppo = (check_ppo(isaac_snapshot, cfg, geometry["source_sha"])
           if isaac_snapshot else {"status": "not_run"})
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
            "required": ["approved camera calibration", "exposure-bound A/B joint evidence"],
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
