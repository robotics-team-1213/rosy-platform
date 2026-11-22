"""Canonical intake, collection discovery, task-string normalization, and bench->sim unit alignment.

Self-contained under learning/ (zero deploy/robot/omx imports).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import uuid

from experiment_io import write_json

_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_GOAL_CANON_RE = re.compile(r"from \S+ to (?:ship-h[12]r[0-2]-l[0-2]|tray|stand)\.$")
_ARROW_PAIR_RE = re.compile(
    r"\b(ship-h[12]r[0-2]-l[0-2]|belt|tray|stand)\s*->\s*(ship-h[12]r[0-2]-l[0-2]|belt|tray|stand)\b", re.I
)
_HOLD_SPOT_RE = re.compile(r"ship(?:\s+hold)?\s*h([12])\b.*?\br([0-2])\b.*?\bl([0-2])\b", re.I)
_HYPHEN_SPOT_RE = re.compile(r"ship-h([12])r([0-2])-l([0-2])", re.I)
_INTAKE_FIELDS = frozenset({"collection", "manifest_sha256", "remote_path", "arm_id", "total_episodes", "rig_revision", "auto_align"})


def normalize_bench_task(raw: str) -> str:
    """Normalize ship_task_cards and apply_task_override strings into data_gate goal syntax."""
    text = " ".join(str(raw or "").split()).strip()
    if not text:
        return ""
    m_arrow = _ARROW_PAIR_RE.search(text)
    if m_arrow:
        orig, dest = m_arrow.group(1).lower(), m_arrow.group(2).lower()
        return f"Pick container from belt to {dest}." if orig == "belt" else f"Move container from {orig} to {dest}."
    if _GOAL_CANON_RE.search(text):
        return text
    spot = ""
    m = _HYPHEN_SPOT_RE.search(text) or _HOLD_SPOT_RE.search(text)
    if m:
        spot = f"ship-h{m.group(1)}r{m.group(2)}-l{m.group(3)}"
    if spot:
        m_rev = re.search(rf"{re.escape(spot)}\s+to\s+(belt|tray|stand)\b", text, re.I)
        if m_rev:
            return f"Move container from {spot} to {m_rev.group(1).lower()}."
        return f"Pick container from belt to {spot}."
    m_zone = re.search(r"\bto\s+(tray|stand)\b", text, re.I)
    if m_zone:
        return f"Pick container from belt to {m_zone.group(1).lower()}."
    return text


def detect_source_units(src: Path, arm_id: str, info: dict) -> str:
    """Resolve explicit units from record-config.json (copied alongside sealed dataset) or info.json."""
    cfg_path = src.parent / "record-config.json"
    try:
        if cfg_path.is_file() and not cfg_path.is_symlink():
            robot = (json.loads(cfg_path.read_text(encoding="utf-8-sig")) or {}).get("robot") or {}
            child = robot.get(arm_id) if isinstance(robot.get(arm_id), dict) else robot
            if isinstance(child.get("use_degrees"), bool):
                return "deg" if child["use_degrees"] else "norm_100"
    except (OSError, ValueError):
        pass
    u = str(info.get("units") or "").strip()
    return u if u in ("rad", "sim_rad", "norm_100", "deg") else ""


def detect_unit_mode(st, ac, *, robot_type: str = "", units: str = "") -> str:
    """Infer whether real trajectory arrays use norm [-100..100], degrees, or sim radians."""
    import numpy as np

    if units in ("rad", "norm_100", "deg"):
        return units
    if units == "sim_rad" or robot_type == "omx_sim_arm":
        return "rad"
    if len(st) == 0:
        return "norm_100" if robot_type in ("omx_follower", "bi_omx_follower") else "rad"
    max_j = float(max(np.abs(st[:, :5]).max(), np.abs(ac[:, :5]).max()))
    max_g = float(max(np.abs(st[:, 5]).max(), np.abs(ac[:, 5]).max()))
    if max_j > 105.0:
        return "deg"
    if max_j > 3.65 or max_g > 1.3:
        return "norm_100"
    return "rad"


def _convert_vec(arr, *, scale: float, jaw0: float, jaw1: float, g0: float, g1: float, clip_max: float = 1.3):
    import numpy as np

    out = arr.astype(np.float64, copy=True)
    if scale != 1.0:
        out[:, :5] = out[:, :5] * scale
    span_g = g1 - g0
    if abs(span_g) > 1e-6:
        out[:, 5] = jaw0 + (out[:, 5] - g0) * (jaw1 - jaw0) / span_g
    out[:, 5] = np.clip(out[:, 5], 0.0, clip_max)
    return out


def prepare_episode_arrays(st, ac, *, spec: dict, arm_id: str, robot_type: str = "",
                           src_fps: int = 30, target_fps: int = 15, unit_mode: str = "auto", units: str = ""):
    """Slice bimanual 12-DOF arrays if needed, align [-100..100]/deg/gripper to sim radians, and downsample 30->15fps."""
    import numpy as np

    st_arr = np.asarray(st, dtype=np.float64)
    ac_arr = np.asarray(ac, dtype=np.float64)
    if st_arr.ndim != 2 or ac_arr.ndim != 2 or len(st_arr) != len(ac_arr):
        raise ValueError("matching 2D observation.state and action arrays required")
    if st_arr.shape[1] == 12 and ac_arr.shape[1] == 12:
        if arm_id not in ("arm_a", "arm_b"):
            raise ValueError(f"12-DOF bimanual slicing requires arm_a or arm_b, got {arm_id}")
        sl = slice(0, 6) if arm_id == "arm_a" else slice(6, 12)
        st_arr, ac_arr = st_arr[:, sl], ac_arr[:, sl]
    if st_arr.shape[1] != 6 or ac_arr.shape[1] != 6:
        raise ValueError(f"expected 6-DOF per arm, got {st_arr.shape[1]} and {ac_arr.shape[1]}")

    mode = unit_mode if unit_mode in ("rad", "norm_100", "deg") else detect_unit_mode(
        st_arr, ac_arr, robot_type=robot_type, units=units
    )
    if mode != "rad":
        scale = math.pi / 100.0 if mode == "norm_100" else math.pi / 180.0
        jaw0 = float(spec["sim_jaw_closed"])
        jaw1 = float(spec["sim_jaw_open"])
        g0 = float(spec["idle_park"][arm_id]["gripper_units"])
        g1 = float(spec["canonical_start"][arm_id]["gripper_units"])
        st_arr = _convert_vec(st_arr, scale=scale, jaw0=jaw0, jaw1=jaw1, g0=g0, g1=g1)
        ac_arr = _convert_vec(ac_arr, scale=scale, jaw0=jaw0, jaw1=jaw1, g0=g0, g1=g1)

    stride = 2 if (int(src_fps) == 30 and int(target_fps) == 15) else 1
    out_fps = 15 if stride == 2 else int(src_fps)
    return st_arr[::stride], ac_arr[::stride], stride, out_fps


def select_arm_features(features: dict, arm_id: str, legacy_map: dict | None = None) -> tuple[dict, dict]:
    """Filter other-arm camera keys and default per-arm wrist mapping before data_gate.camera_map."""
    legacy = dict(legacy_map or {})
    other_prefixes = tuple(f"observation.images.{a}_" for a in ("arm_a", "arm_b") if a != arm_id)
    filtered = {k: v for k, v in features.items() if not (k.startswith(other_prefixes) and not k.endswith("_depth"))}
    wrist_key = f"{arm_id}_wrist"
    if f"observation.images.{wrist_key}" in filtered and "observation.images.wrist" not in filtered:
        legacy.setdefault(wrist_key, "wrist")
    top_key = f"{arm_id}_top"
    if f"observation.images.{top_key}" in filtered and "observation.images.top" not in filtered and "observation.images.rs" not in filtered:
        legacy.setdefault(top_key, "top")
    return filtered, legacy


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_manifest(col_dir: Path) -> tuple[dict, str]:
    mf_path = col_dir / "manifest.json"
    if (col_dir / "DO_NOT_TRAIN.txt").exists() or (col_dir / "dataset" / "DO_NOT_TRAIN.txt").exists():
        raise ValueError(f"DO_NOT_TRAIN collection refused: {col_dir.name}")
    if not mf_path.is_file() or mf_path.is_symlink():
        raise ValueError(f"sealed manifest.json missing: {col_dir.name}")
    root_res = col_dir.resolve()
    seen = set()
    for p in col_dir.rglob("*"):
        if p.is_symlink() or not p.resolve().is_relative_to(root_res):
            raise ValueError(f"symlink or escaping path refused in {col_dir.name}")
        if p.is_file() and p != mf_path:
            seen.add(p.relative_to(col_dir).as_posix())
    raw = mf_path.read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    if manifest.get("schema") != "rosy.omx-collection-session.v1" or manifest.get("state") != "CLOSED" or manifest.get("mode") != "hardware":
        raise ValueError(f"closed hardware manifest required: {col_dir.name}")
    if manifest.get("source_mode") not in ("leader_native", "scripted_teacher"):
        raise ValueError(f"unsupported source_mode in {col_dir.name}")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or seen != set(files):
        raise ValueError(f"manifest files mismatch on disk: {col_dir.name}")
    for rel, expected in files.items():
        if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise ValueError(f"invalid manifest relpath: {rel!r}")
        if _sha256_file(col_dir / rel) != expected:
            raise ValueError(f"manifest file sha256 mismatch: {rel}")
    ds_dir = col_dir / "dataset"
    info_path = ds_dir / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.is_file() else {}
    if int(manifest.get("total_episodes") or 0) < 1 or int(info.get("total_episodes") or 0) < 1 or not list(ds_dir.glob("data/**/*.parquet")):
        raise ValueError(f"empty collection (total_episodes < 1) refused: {col_dir.name}")
    return manifest, hashlib.sha256(raw).hexdigest()


def scan_transferred_collections(collections_dir: Path | None) -> dict[str, dict]:
    """Discover sealed, non-DO_NOT_TRAIN hardware collections transferred from the cell PC."""
    if collections_dir is None or not collections_dir.is_dir() or collections_dir.is_symlink():
        return {}
    found: dict[str, dict] = {}
    root = collections_dir.resolve()
    for entry in sorted(collections_dir.iterdir()):
        name = entry.name
        if name.startswith(".") or not _ID_RE.fullmatch(name) or entry.is_symlink() or not entry.is_dir():
            continue
        if not entry.resolve().is_relative_to(root):
            continue
        try:
            manifest, mf_sha = _validate_manifest(entry)
        except (OSError, ValueError):
            continue
        arm_id = str(manifest.get("arm_id") or ("arm_ab" if manifest.get("robot_type") == "bi_omx_follower" else ""))
        if arm_id not in ("arm_a", "arm_b", "arm_ab", ""):
            continue
        found[name] = {
            "id": name,
            "kind": "real_dataset",
            "arm_id": arm_id or None,
            "label": f"Collected {name}",
            "path": (entry / "dataset").resolve(),
            "collection_path": entry.resolve(),
            "manifest": manifest,
            "manifest_sha256": mf_sha,
        }
    return found


def handle_intake_request(service, body: dict) -> dict:
    """Admit one transferred sealed collection and enqueue idempotent align_real jobs."""
    if service.collections_dir is None:
        raise ValueError("canonical collections_dir is not configured")
    if not isinstance(body, dict) or not isinstance(body.get("collection"), str) or (set(body) - _INTAKE_FIELDS):
        raise ValueError("intake requires valid collection request fields")
    name = body["collection"].strip()
    if not _ID_RE.fullmatch(name):
        raise ValueError("invalid collection identifier")

    col_dir = service.collections_dir / name
    if not col_dir.is_dir() or col_dir.is_symlink() or not col_dir.resolve().is_relative_to(service.collections_dir.resolve()):
        raise ValueError(f"transferred collection not found: {name}")
    manifest, mf_sha = _validate_manifest(col_dir)
    if "manifest_sha256" in body and body["manifest_sha256"]:
        req_sha = str(body["manifest_sha256"]).strip()
        if not _HEX64_RE.fullmatch(req_sha) or req_sha != mf_sha:
            raise ValueError("manifest_sha256 mismatch")

    mf_arm = str(manifest.get("arm_id") or ("arm_ab" if manifest.get("robot_type") == "bi_omx_follower" else "")).strip()
    if "arm_id" in body and body["arm_id"] not in (None, ""):
        req_arm = str(body["arm_id"]).strip()
        if req_arm != mf_arm:
            raise ValueError("request arm_id disagrees with sealed manifest arm_id")

    if manifest.get("robot_type") == "bi_omx_follower" or mf_arm == "arm_ab":
        target_arms = ["arm_a", "arm_b"]
    elif mf_arm in ("arm_a", "arm_b"):
        target_arms = [mf_arm]
    else:
        target_arms = []

    raw_align = body.get("auto_align", True)
    if type(raw_align) is not bool:
        raise ValueError("auto_align must be bool")
    jobs = []
    if raw_align and target_arms:
        for arm in target_arms:
            req_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"canonical-intake:{name}:{mf_sha}:{arm}"))
            jobs.append(service.start_job({
                "request_id": req_id,
                "kind": "align_real",
                "arm_id": arm,
                "params": {"source_id": name, "wrist_flip": (arm == "arm_b"), "trim_dead_idle": True},
            }))

    receipt_dir = service.root / "intakes"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "collection": name,
        "manifest_sha256": mf_sha,
        "total_episodes": int(manifest["total_episodes"]),
        "arms": target_arms,
        "job_ids": [j["id"] for j in jobs],
    }
    write_json(receipt_dir / f"{name}.json", receipt)
    return {
        "ok": True,
        **receipt,
        "jobs": jobs,
        "job_id": jobs[0]["id"] if jobs else "",
    }
