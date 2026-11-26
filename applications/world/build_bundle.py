#!/usr/bin/env python3
"""Build a static, offline Rosy World bundle from archived inputs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from sys import float_info

HERE = Path(__file__).resolve().parent
SHARED = HERE.parents[1] / "shared" / "web"
SUMS = "SHA256SUMS.txt"
ARCHIVED_SITE_MAP = "site-map/world_261026_v7_active.json"
SITE_CAD_SOURCE = "site-map/261026_World.STL"
SITE_CAD_FILE = "site-cad.stl.gz"
BIRDVIEW_SOURCE = "site-map/2026-11-01-world261026-top-down-plain.jpg"
BIRDVIEW_FILE = "site-birdview.jpg"
BIRDVIEW_SHA256 = "51d01ee86df13ce5c2f302b926f0fe9f6d4c5be0445158b159f67a75f9708a18"
EQUIPMENT_FILES = {
    "site": "site-equipment.json.gz",
    "cell": "cell-equipment.json.gz",
    "registration": "site-registration.json",
}
# Match the source pin in tools/calibration/extract_world_paint.py.
SITE_CAD_SHA256 = "dd91457a4a8d17d7fbb4fbfdb12dff9c2ae98e92e74760231c9ec08aa377f3cc"
INPUT_FILES = {
    ARCHIVED_SITE_MAP: "site-map.json",
    "site-map/world_261026_v7_map.png": "site-map.png",
    "isaac/geometry-check.json": "geometry.json",
    "isaac/calibration/check.json": "calibration.json",
    "isaac/isaac-overview.png": "cell-render.png",
    "isaac/calibration/frames/top.jpg": "cell-photo.jpg",
}
WEB_FILES = (
    "index.html", "styles.css", "app.js", "live-feeds.js", "scene.js", "scene-geometry.js",
    "play.js", "factory-live.js", "factory-live-ui.js", "factory-actors.js", "world-monitor.js", "studio-look.js",
    "active-site-map.js", "map-rules.js",
    "omx-arm.js", "manifest.webmanifest",
)
FACTORY_STAGES = (
    "c2_departure", "s1_yield", "s3_stop", "cell_claim",
    "arm_s_to_belt", "belt_transit", "ab_stack",
)
FACTORY_EXTENDED_STAGES = FACTORY_STAGES + ("ab_rehandle", "outbound_dispatch")
# Direct UI references plus the modules, CSS resources and notices they require.
COMMON_FILES = (
    "tokens.css", "theme.js", "components.css", "component-controls.css",
    "template.css", "app-shell.css", "brand/mark.svg", "ui.js", "ui-wiring.js",
    "confirmation.js", "live-dialog-geometry.js", "core_ui_logic.js", "vendor/three.module.min.js",
    "vendor/three.core.min.js", "vendor/three.LICENSE",
    "meshes/pinky-tray.stl",
    *(f"meshes/omx-link{i}.stl" for i in range(8)),
)


def read_within(root: Path, name: str) -> bytes:
    source = (root / name).resolve()
    if not source.is_relative_to(root.resolve()):
        raise ValueError(f"{name} points outside {root}")
    return source.read_bytes()


def verified_inputs(inputs: Path, with_site_cad: bool = False) -> tuple[dict[str, bytes], dict[str, str]]:
    sums: dict[str, str] = {}
    for number, line in enumerate(read_within(inputs, SUMS).decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split(None, 1)
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
            raise ValueError(f"{inputs / SUMS}:{number}: expected '<sha256>  <path>'")
        digest, name = fields
        name = name.lstrip("*").strip().replace("\\", "/")
        if not name or name in sums:
            raise ValueError(f"{inputs / SUMS}:{number}: empty or duplicate path {name!r}")
        sums[name] = digest.lower()

    required = dict(INPUT_FILES)
    if BIRDVIEW_SOURCE in sums:
        required[BIRDVIEW_SOURCE] = BIRDVIEW_FILE
    for filename in EQUIPMENT_FILES.values():
        source = f"equipment/{filename}"
        if source in sums:
            required[source] = filename
    if with_site_cad:
        required[SITE_CAD_SOURCE] = SITE_CAD_FILE

    files = {}
    for name, destination in required.items():
        if name not in sums:
            raise ValueError(f"{name} is missing from {inputs / SUMS}")
        content = read_within(inputs, name)
        if hashlib.sha256(content).hexdigest() != sums[name]:
            raise ValueError(f"SHA-256 mismatch for {name}. Re-copy the verified handoff.")
        if name == BIRDVIEW_SOURCE and sums[name] != BIRDVIEW_SHA256:
            raise ValueError(f"{name} does not match the archived ceiling capture SHA-256.")
        if name == SITE_CAD_SOURCE:
            if sums[name] != SITE_CAD_SHA256:
                raise ValueError(f"{name} does not match the pinned source SHA-256. Use the archived CAD.")
            compressed = io.BytesIO()
            with gzip.GzipFile(fileobj=compressed, mode="wb", compresslevel=3, mtime=0) as stream:
                stream.write(content)
            content = compressed.getvalue()
        files[destination] = content
    return files, {name: sums[name] for name in required}


def nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON number {value}")


def validate_site_map(content: bytes) -> None:
    envelope = json.loads(content.decode("utf-8"), parse_constant=reject_constant)
    if not isinstance(envelope, dict) or not isinstance(envelope.get("map"), dict):
        raise ValueError("expected the Fleet active-map response with a map object")
    version = envelope.get("version")
    if type(version) is not int or not 0 < version < 2**53:
        raise ValueError("version must be a positive safe integer")
    site_map = envelope["map"]
    if site_map.get("schema") != "rosy.site_map/1" or not nonempty_string(site_map.get("map_id")):
        raise ValueError("map must use schema rosy.site_map/1 and have a nonempty map_id")
    locations = site_map.get("places")
    if locations is None:
        locations = site_map.get("nodes")
    if not isinstance(locations, list) or not isinstance(site_map.get("edges"), list):
        raise ValueError("map must contain places (or nodes) and edges arrays")


def validate_recording(content: bytes) -> None:
    data = json.loads(content.decode("utf-8"), parse_constant=reject_constant)
    if not isinstance(data, dict) or data.get("schema") != "rosy.world.recording.v1":
        raise ValueError("schema must be rosy.world.recording.v1")
    if not nonempty_string(data.get("source")):
        raise ValueError("source must be a nonempty string")
    version = data.get("map_version")
    if type(version) is not int or not 0 < version < 2**53:
        raise ValueError("map_version must be a positive safe integer")
    captured = data.get("captured_at")
    if not isinstance(captured, str) or "T" not in captured:
        raise ValueError("captured_at must be an ISO 8601 timestamp with time zone")
    if datetime.fromisoformat(captured.replace("Z", "+00:00")).utcoffset() is None:
        raise ValueError("captured_at must include a time zone")

    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("samples must be a nonempty list")
    previous = -1
    frame_id = None
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"samples[{index}] must be an object")
        offset = sample.get("offset_ms")
        if type(offset) is not int or not previous < offset < 2**53:
            raise ValueError(f"samples[{index}].offset_ms must be a strictly increasing nonnegative safe integer")
        previous = offset
        frame = sample.get("frame_id")
        if not nonempty_string(frame) or frame != frame.strip() or frame_id not in (None, frame):
            raise ValueError(f"samples[{index}].frame_id must be nonempty and consistent across samples")
        frame_id = frame
        positions = sample.get("positions")
        if not isinstance(positions, list):
            raise ValueError(f"samples[{index}].positions must be a list")
        ids = set()
        for position in positions:
            entity = position.get("id") if isinstance(position, dict) else None
            if not nonempty_string(entity) or entity != entity.strip() or entity in ids:
                raise ValueError(f"samples[{index}] contains a missing, invalid or duplicate position ID")
            ids.add(entity)
            for axis in ("x_m", "y_m"):
                value = position.get(axis)
                if type(value) not in (int, float) or not -float_info.max <= value <= float_info.max:
                    raise ValueError(f"samples[{index}] position {entity!r}. {axis} must be finite")


def validate_factory_timeline(content: bytes) -> dict:
    data = json.loads(content.decode("utf-8"), parse_constant=reject_constant)
    if not isinstance(data, dict) or data.get("schema") != "rosy.world.factory-timeline.v1":
        raise ValueError("schema must be rosy.world.factory-timeline.v1")
    if data.get("source_mode") not in ("verified_replay", "live") or not nonempty_string(data.get("run_id")):
        raise ValueError("invalid factory timeline source_mode or run_id")
    for digest_key in ("receipts_sha256", "site_map_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(data.get(digest_key, ""))):
            raise ValueError(f"{digest_key} must be 64 lowercase hex chars")
    duration = data.get("duration_s")
    if type(duration) not in (int, float) or not 0 < duration <= float_info.max:
        raise ValueError("duration_s must be positive and finite")
    stages = data.get("stages")
    stage_ids = tuple(s.get("id") for s in stages if isinstance(s, dict)) if isinstance(stages, list) else ()
    if stage_ids not in (FACTORY_STAGES, FACTORY_EXTENDED_STAGES):
        raise ValueError("stages must match the 7 canonical or 9 extended factory stages in order")
    keyframes = data.get("keyframes")
    if not isinstance(keyframes, list) or not keyframes:
        raise ValueError("keyframes must be a nonempty list")
    previous = -1.0
    for idx, frame in enumerate(keyframes):
        if not isinstance(frame, dict):
            raise ValueError(f"keyframes[{idx}] must be an object")
        ts = frame.get("time_s")
        if type(ts) not in (int, float) or ts < previous or not -float_info.max <= ts <= float_info.max:
            raise ValueError(f"keyframes[{idx}].time_s must be finite and nondecreasing")
        previous = float(ts)
        pinky = frame.get("pinky") or {}
        cargo = frame.get("cargo") or {}
        if (not isinstance(pinky.get("pose_m"), list) or len(pinky["pose_m"]) != 3
                or not all(type(v) in (int, float) and -float_info.max <= v <= float_info.max for v in pinky["pose_m"])
                or type(pinky.get("yaw_rad")) not in (int, float)
                or not isinstance(cargo.get("pose_m"), list) or len(cargo["pose_m"]) != 3
                or not all(type(v) in (int, float) and -float_info.max <= v <= float_info.max for v in cargo["pose_m"])):
            raise ValueError(f"keyframes[{idx}] has invalid pinky or cargo coordinates")
    return data


def check_destination(out: Path) -> None:
    if out.exists() or out.is_symlink():
        raise ValueError(f"output already exists: {out}. Choose a fresh folder.")


def add_field_photo(data, manifest, sidecar, key):
    original = key == "field_original"
    mode = "none" if original else "map"
    meta = json.loads(sidecar.read_bytes(), parse_constant=reject_constant)
    content = sidecar.with_suffix(".jpg").read_bytes()
    if (not isinstance(meta, dict) or meta.get("schema") != "rosy.world.field-photo.v1"
            or meta.get("source_id") != "ceiling_north" or meta.get("rectified") != mode
            or hashlib.sha256(content).hexdigest() != meta.get("sha256")
            or not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9")):
        raise ValueError("expected a Rosy Cam JPEG and matching metadata")
    width, height = meta["size"]
    if (type(width) is not int or type(height) is not int or not 0 < width <= 4096 or not 0 < height <= 4096
            or datetime.fromisoformat(meta["captured_at"]).tzinfo is None):
        raise ValueError("invalid Rosy Cam image dimensions or timestamp")
    if not original:
        x0, y0, x1, y1, resolution = meta["plane"]
        if (not -10 <= x0 < x1 <= 10 or not -10 <= y0 < y1 <= 10 or not 0 < resolution <= 2000
                or abs(width - (x1 - x0) * resolution) > 1 or abs(height - (y1 - y0) * resolution) > 1
                or not nonempty_string(meta.get("calibration_revision"))):
            raise ValueError("invalid Rosy Cam map-plane calibration")
    name = key.replace("_", "-") + ".jpg"
    data[name] = content
    manifest[key] = {**meta, "bundle_path": f"data/{name}"}


def build(
    inputs: Path, out: Path, recording: Path | None, site_map: Path | None = None,
    *, with_site_cad: bool = False, field_photo: Path | None = None, field_original: Path | None = None,
    birdview: Path | None = None, recording_map: Path | None = None, factory_timeline: Path | None = None,
) -> Path:
    inputs = inputs.expanduser().resolve()
    out = out.expanduser()
    check_destination(out)
    out = out.resolve()
    if out.is_relative_to(inputs) or any((parent / ".git").exists() for parent in out.parents):
        raise ValueError("choose an output outside the read-only handoff and all Git checkouts")

    data, input_sums = verified_inputs(inputs, with_site_cad)
    manifest = {
        "inputs": {name: {"bundle_path": f"data/{INPUT_FILES[name]}", "sha256": input_sums[name]}
                   for name in INPUT_FILES},
    }
    if BIRDVIEW_SOURCE in input_sums:
        manifest["site_birdview"] = {
            "bundle_path": f"data/{BIRDVIEW_FILE}",
            "source_sha256": input_sums[BIRDVIEW_SOURCE],
        }
    equipment = {
        kind: {"bundle_path": f"data/{filename}", "source_sha256": input_sums[f"equipment/{filename}"]}
        for kind, filename in EQUIPMENT_FILES.items() if f"equipment/{filename}" in input_sums
    }
    if equipment:
        manifest["equipment"] = equipment
    if with_site_cad:
        manifest["site_cad"] = {
            "bundle_path": f"data/{SITE_CAD_FILE}",
            "source_sha256": SITE_CAD_SHA256,
        }
    if site_map is not None:
        try:
            content = site_map.expanduser().read_bytes()
            validate_site_map(content)
        except (OSError, ValueError) as error:
            raise ValueError(f"invalid site map {site_map}: {error}") from error
        data["site-map.json"] = content
        manifest["inputs"][ARCHIVED_SITE_MAP]["bundle_path"] = None
        manifest["site_map_override"] = {
            "bundle_path": "data/site-map.json",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    if field_photo is not None:
        add_field_photo(data, manifest, field_photo, "field_photo")
    if field_original is not None:
        add_field_photo(data, manifest, field_original, "field_original")
    if birdview is not None:
        add_field_photo(data, manifest, birdview, "site_birdview")
    if recording is not None:
        recording = recording.expanduser().resolve()
        try:
            content = recording.read_bytes()
            validate_recording(content)
        except (OSError, ValueError) as error:
            raise ValueError(f"invalid recording {recording}: {error}") from error
        data["recording.json"] = content
    if recording_map is not None:
        if recording is None:
            raise ValueError("--recording-map requires --recording")
        map_bytes = recording_map.read_bytes()
        validate_site_map(map_bytes)
        rec, envelope = json.loads(content), json.loads(map_bytes)
        if rec["map_version"] != envelope["version"] or rec["samples"][0]["frame_id"] != envelope["map"]["map_id"]:
            raise ValueError("recording and its map must share the same version and frame")
        data["recording-map.json"] = map_bytes
        manifest["recording_map"] = {"bundle_path": "data/recording-map.json",
                                     "sha256": hashlib.sha256(map_bytes).hexdigest()}
    if factory_timeline is not None:
        tl_path = factory_timeline.expanduser().resolve()
        try:
            tl_bytes = tl_path.read_bytes()
            tl_meta = validate_factory_timeline(tl_bytes)
        except (OSError, ValueError) as error:
            raise ValueError(f"invalid factory timeline {tl_path}: {error}") from error
        data["factory-timeline.json"] = tl_bytes
        manifest["factory_timeline"] = {
            "bundle_path": "data/factory-timeline.json",
            "sha256": hashlib.sha256(tl_bytes).hexdigest(),
            "run_id": tl_meta["run_id"],
            "duration_s": tl_meta["duration_s"],
        }

    files = {name: read_within(HERE / "web", name) for name in WEB_FILES}
    files.update({f"common/{name}": read_within(SHARED, name) for name in COMMON_FILES})
    files.update({f"data/{name}": content for name, content in data.items()})
    for name in (
        "README.md", "serve.py", "world_state.py", "compose.yaml", "Dockerfile",
        "install-windows.ps1", "open-app.ps1", "observe_isaac.py", "observe_pinky.py",
        "bridge_real_fleet.py", "world_mdns.py", "world_mdns_probe.py",
    ):
        files[name] = (HERE / name).read_bytes()
    sim_dir = HERE.parents[1] / "tools" / "sim"
    for name in ("world_env_adapter.py", "world_swarm.py", "world_training_hooks.py", "world_train_parallel.py", "virtual_core_fleet.py", "world_r2s_calibrate.py"):
        files[name] = (sim_dir / name).read_bytes()
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    files[SUMS] = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                          for name, data in sorted(files.items())).encode("utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rosy-world-", dir=out.parent))
    try:
        for name, content in files.items():
            destination = staging / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        if (staging / "data" / "geometry.json").is_file() and (staging / "data" / "site-registration.json").is_file():
            try:
                import sys as _sys

                _sim_str = str(sim_dir)
                if _sim_str not in _sys.path:
                    _sys.path.insert(0, _sim_str)
                import world_r2s_calibrate

                world_r2s_calibrate.write_r2s_calibration(staging, update_sums=True)
            except (ImportError, OSError, ValueError):
                pass
        check_destination(out)
        staging.rename(out)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True, help="read-only archived handoff folder")
    parser.add_argument("--out", type=Path, required=True, help="fresh bundle directory")
    parser.add_argument("--recording", type=Path, help="optional captured recording JSON")
    parser.add_argument("--recording-map", type=Path, help="map snapshot bound to the recording instead of the main map")
    parser.add_argument("--site-map", type=Path, help="optional saved Fleet active-map response JSON")
    parser.add_argument("--with-site-cad", action="store_true", help="include the verified archived site CAD")
    parser.add_argument("--field-photo", type=Path, help="Rosy Cam map-plane JSON sidecar beside its JPEG")
    parser.add_argument("--field-original", type=Path, help="original Rosy Cam JSON sidecar beside its JPEG")
    parser.add_argument("--birdview", type=Path, help="new Rosy Cam map-plane sidecar for the archived bird's-eye view")
    parser.add_argument("--factory-timeline", type=Path, help="verified 7-stage factory replay timeline JSON")
    args = parser.parse_args()
    try:
        out = build(args.inputs, args.out, args.recording, args.site_map, with_site_cad=args.with_site_cad,
                    field_photo=args.field_photo, field_original=args.field_original, birdview=args.birdview,
                    recording_map=args.recording_map, factory_timeline=args.factory_timeline)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"bundle: {out}")
    print(f'serve: python "{out / "serve.py"}"')
    print("open: http://127.0.0.1:8140/")


if __name__ == "__main__":
    main()
