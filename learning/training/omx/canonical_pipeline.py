"""Canonical OMX start-pose service: spec serving, SQLite job queue, concurrency/lock orchestration."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

_CONTRACTS_SRC = Path(__file__).resolve().parents[3] / "contracts" / "learning" / "src"
if str(_CONTRACTS_SRC) not in sys.path:
    sys.path.insert(0, str(_CONTRACTS_SRC))

from canonical_intake import handle_intake_request, scan_transferred_collections  # noqa: E402
from canonical_telemetry import HostTelemetry, external_gpu_locks, load_peer_token  # noqa: E402
from canonical_recording_todo import build_service_todo  # noqa: E402
from canonical_watch import (  # noqa: E402
    BusyConflict, PeerClient, read_bounded_json, scan_watch_dir, scrub_text, strip_paths, tail_log, validate_peer_url,
)
from experiment_io import identifier, write_json  # noqa: E402
from experiment_process import process_stamp  # noqa: E402
from rosy.contracts.learning.omx_canonical import AUTHORITY_STAMP, ARM_IDS, load_canonical_spec  # noqa: E402

CONFIG_SCHEMA = "rosy.omx.canonical-config/1"
REQUEST_SCHEMA = "rosy.omx.canonical-job-request/1"
JOB_KINDS = ("align_real", "collect_dart", "train_stage", "eval_ladder", "cell_live_check")
GPU_KINDS = frozenset({"collect_dart", "train_stage", "eval_ladder"})
CPU_SLOT_LIMIT = 2
_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")
_CAM_ROLES = ("top", "side", "wrist")
_L1_TASKS = ("stack-t1", "stack-t2", "stack-t3", "ship-h1")
_SOURCE_KINDS = frozenset({"real_dataset", "sim_dataset", "frames_dir", "chunk_library", "checkpoint"})
_validate_peer_url = validate_peer_url


def _abs_path(raw, label: str, *, allow_symlink_file: bool = False) -> Path:
    if not isinstance(raw, str) or not 1 <= len(raw) <= 512 or any(ord(c) < 32 for c in raw):
        raise ValueError(f"bounded string required: {label}")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(f"absolute path required: {label}")
    if allow_symlink_file:
        if not path.is_file():
            raise ValueError(f"configured python interpreter missing: {label}")
        return path
    if path.is_symlink():
        raise ValueError(f"non-symlink path required: {label}")
    return path.resolve()


def _check_int(value, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be int in {low}..{high}")
    return value


def _check_float(value, low: float, high: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be finite number")
    val = float(value)
    if not low <= val <= high:
        raise ValueError(f"{label} must be in {low}..{high}")
    return val


def _check_bool(value, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be bool")
    return value


def _named_mapping(raw, limit: int, label: str) -> dict:
    raw = raw or {}
    if not isinstance(raw, dict) or len(raw) > limit:
        raise ValueError(f"{label} must be mapping with <= {limit} entries")
    for key, val in raw.items():
        if not isinstance(key, str) or not _ID_RE.fullmatch(key) or not isinstance(val, dict):
            raise ValueError(f"invalid {label} key: {key!r}")
    return raw


class CanonicalService:
    """Host-isolated canonical OMX pipeline manager attached to experiment_center.Center."""

    def __init__(self, root: Path | None, config: dict | None, *, host_id: str | None = None, default_python: str | None = None):
        self.host_id = host_id
        self.lock = threading.RLock()
        self.children: dict[str, subprocess.Popen] = {}
        self.configured = self.writable = False
        self.spec, self.spec_sha256, self.spec_source = load_canonical_spec(None)
        self.root: Path | None = None
        self.db: Path | None = None
        self.python: dict[str, Path] = {}
        self.named_sources: dict[str, dict] = {}
        self.watch_roots: dict[str, dict] = {}
        self.recording_manifest_path: Path | None = None
        self.peers = PeerClient({})
        self.jobs_dir = Path.home() / "rosy-jobs"
        self.peer_token_file: Path | None = None
        self.collections_dir: Path | None = None
        self.telemetry = HostTelemetry(self._disk_probe_path)
        if config is None:
            return
        allowed = {"schema", "spec_path", "python", "named_sources", "watch_roots", "peers",
                   "jobs_dir", "peer_token_file", "collections_dir", "recording_manifest_path"}
        if not isinstance(config, dict) or config.get("schema") != CONFIG_SCHEMA or set(config) - allowed:
            raise ValueError(f"invalid canonical config (requires {CONFIG_SCHEMA})")
        if root is None:
            raise ValueError("canonical service root required when config is enabled")
        self.root = _abs_path(str(root), "canonical root")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "runs").mkdir(exist_ok=True)
        if config.get("spec_path") is not None:
            self.spec, self.spec_sha256, self.spec_source = load_canonical_spec(_abs_path(config["spec_path"], "spec_path"))

        raw_py = config.get("python") or {}
        if not isinstance(raw_py, dict) or set(raw_py) - {"sim", "train", "cell"}:
            raise ValueError("canonical python map only supports sim, train, cell")
        for key in ("sim", "train", "cell"):
            chosen = raw_py.get(key) or default_python
            if chosen is not None:
                self.python[key] = _abs_path(chosen, f"python.{key}", allow_symlink_file=True)

        for sid, entry in _named_mapping(config.get("named_sources"), 32, "named_sources").items():
            if entry.get("kind") not in _SOURCE_KINDS or entry.get("arm_id") not in (*ARM_IDS, None):
                raise ValueError(f"invalid named_source entry: {sid}")
            self.named_sources[sid] = {
                "id": sid, "kind": entry["kind"], "arm_id": entry.get("arm_id"),
                "label": str(entry.get("label") or sid)[:120],
                "path": _abs_path(entry.get("path"), f"named_sources.{sid}.path"),
            }
        for wid, entry in _named_mapping(config.get("watch_roots"), 8, "watch_roots").items():
            if entry.get("host_id") not in ("model", "ai", None):
                raise ValueError(f"invalid watch_root host_id: {wid}")
            self.watch_roots[wid] = {
                "id": wid, "label": str(entry.get("label") or wid)[:120], "host_id": entry.get("host_id"),
                "path": _abs_path(entry.get("path"), f"watch_roots.{wid}.path"),
            }
        parsed_peers = {}
        for pid, entry in _named_mapping(config.get("peers"), 4, "peers").items():
            ptf = entry.get("peer_token_file")
            parsed_peers[pid] = {
                "id": pid, "label": str(entry.get("label") or pid)[:120],
                "url": validate_peer_url(entry.get("url")),
                "peer_token_file": _abs_path(ptf, f"peers.{pid}.peer_token_file") if ptf else None,
            }
        self.peers = PeerClient(parsed_peers)
        if config.get("jobs_dir") is not None:
            self.jobs_dir = _abs_path(config["jobs_dir"], "jobs_dir")
        if config.get("peer_token_file") is not None:
            self.peer_token_file = _abs_path(config["peer_token_file"], "peer_token_file")
        if config.get("collections_dir") is not None:
            self.collections_dir = _abs_path(config["collections_dir"], "collections_dir")
        if config.get("recording_manifest_path") is not None:
            self.recording_manifest_path = _abs_path(config["recording_manifest_path"], "recording_manifest_path")

        self.db = self.root / "canonical.sqlite"
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs "
                "(id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, "
                "gpu_required INTEGER NOT NULL, document TEXT NOT NULL, request TEXT NOT NULL, process TEXT NOT NULL)"
            )
        self.configured, self.writable = True, bool(self.python)

    def _disk_probe_path(self) -> Path:
        for meta in self.watch_roots.values():
            p = meta.get("path")
            if isinstance(p, Path) and p.exists():
                return p
        return self.root if self.root is not None else Path.home()

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def spec_payload(self) -> dict:
        return {"schema": self.spec["schema"], "spec_sha256": self.spec_sha256,
                "source": self.spec_source, "spec": self.spec, **AUTHORITY_STAMP}

    def recording_todo(self) -> dict:
        return build_service_todo(self.recording_manifest_path, self.watch_roots)

    def verify_peer_bearer(self, header_value: str | None) -> bool:
        if self.peer_token_file is None or not isinstance(header_value, str) or not header_value.startswith("Bearer "):
            return False
        try:
            expected = load_peer_token(self.peer_token_file)
        except (OSError, ValueError, UnicodeError):
            return False
        return hmac.compare_digest(header_value[7:].strip(), expected)

    def _public_run(self, row: dict, *, include_log: bool = False) -> dict:
        out = {
            "id": row["id"], "request_id": row["request_id"], "kind": row["kind"],
            "arm_id": row["arm_id"], "gpu_required": row["gpu_required"],
            "status": row["status"], "created_at": row["created_at"],
            "params": strip_paths(row.get("params") or {}),
            "progress": strip_paths(row.get("progress")) if row.get("progress") else None,
            "result": strip_paths(row.get("result")) if row.get("result") else None,
            "error": scrub_text(row.get("error"), 240) if row.get("error") else None, **AUTHORITY_STAMP,
        }
        if include_log and self.root is not None:
            out["log_tail"] = tail_log(self.root / "runs" / row["id"])
        return out

    def _refresh(self, db) -> None:
        if self.root is None:
            return
        for rid, document, process in db.execute("SELECT id,document,process FROM runs").fetchall():
            row, receipt = json.loads(document), json.loads(process)
            if row["status"] not in ("launching", "running", "stopping"):
                continue
            rdir = self.root / "runs" / rid
            if (prog := read_bounded_json(rdir / "output" / "progress.json")) is not None:
                row["progress"] = prog
            if row["status"] == "launching":
                launcher = receipt.get("launcher")
                if launcher and process_stamp(launcher["pid"]) == launcher:
                    db.execute("UPDATE runs SET document=? WHERE id=?", (json.dumps(row), rid))
                    continue
                if Path("/proc").is_dir():
                    cands = [process_stamp(int(p.name), rdir / "request.json") for p in Path("/proc").iterdir() if p.name.isdigit()]
                    cands = [c for c in cands if c]
                    if len(cands) == 1:
                        receipt = cands[0]
                        row["status"] = "running"
                        db.execute("UPDATE runs SET process=? WHERE id=?", (json.dumps(receipt), rid))
            proof = process_stamp(receipt.get("pid", -1), rdir / "request.json") if receipt else None
            child = self.children.get(rid)
            code = child.poll() if child else None
            if proof and proof == receipt:
                if row["status"] == "stopping" and time.time() - row.get("cancel_at", time.time()) > 10:
                    try:
                        os.killpg(receipt["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            else:
                res_file, err_file = rdir / "output" / "result.json", rdir / "output" / "error.json"
                if row["status"] == "stopping":
                    row["status"] = "cancelled"
                elif err_file.exists():
                    row.update(status="failed", error=(read_bounded_json(err_file) or {}).get("error", "worker error"))
                elif res_file.exists() and code in (0, None):
                    res_doc = read_bounded_json(res_file, max_bytes=8 * 1048576)
                    if res_doc is None:
                        row.update(status="failed", error="unreadable worker result.json")
                    else:
                        row.update(status="succeeded", result=res_doc)
                elif code not in (0, None):
                    tail = tail_log(rdir, max_chars=240)
                    row.update(status="failed", error=f"worker exited {code}: {tail}" if tail else f"worker exited {code}")
                else:
                    row.update(status="interrupted", error="worker exited without result")
                self.children.pop(rid, None)
            db.execute("UPDATE runs SET document=? WHERE id=?", (json.dumps(row), rid))

    def snapshot(self, *, include_peers: bool = True) -> dict:
        if not self.configured:
            return {
                "configured": False, "writable": False, "host_id": self.host_id,
                "spec_sha256": self.spec_sha256, "spec": self.spec, "spec_source": self.spec_source,
                "named_sources": {}, "gpu_lock": {"busy": False, "holders": []},
                "runs": [], "watched": {}, "peers": self.peers.snapshot() if include_peers else {},
                "host_telemetry": self.telemetry.snapshot(), **AUTHORITY_STAMP,
            }
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._refresh(db)
            rows = [self._public_run(json.loads(r[0])) for r in db.execute("SELECT document FROM runs ORDER BY rowid DESC LIMIT 100")]
            gpu_rows = [json.loads(r[0]) for r in db.execute("SELECT document FROM runs WHERE gpu_required=1")]
        holders = [r["id"] for r in gpu_rows if r["status"] in ("launching", "running", "stopping")]
        holders.extend(external_gpu_locks(self.jobs_dir))
        merged_sources = {**scan_transferred_collections(self.collections_dir), **self.named_sources}
        return {
            "configured": True, "writable": self.writable, "host_id": self.host_id,
            "spec_sha256": self.spec_sha256, "spec": self.spec, "spec_source": self.spec_source,
            "named_sources": {k: {"id": v["id"], "kind": v["kind"], "arm_id": v["arm_id"], "label": v["label"]}
                              for k, v in merged_sources.items()},
            "gpu_lock": {"busy": bool(holders), "holders": holders}, "runs": rows,
            "watched": {wid: scan_watch_dir(m["path"], m) for wid, m in self.watch_roots.items()},
            "peers": self.peers.snapshot() if include_peers else {},
            "host_telemetry": self.telemetry.snapshot(), **AUTHORITY_STAMP,
        }

    def peer_summary(self) -> dict:
        snap = self.snapshot(include_peers=False)
        return {
            "host_id": self.host_id, "configured": snap["configured"], "writable": snap["writable"],
            "spec_sha256": snap["spec_sha256"], "gpu_lock": snap["gpu_lock"],
            "runs": snap["runs"][:25], "watched": snap["watched"],
            "host_telemetry": snap["host_telemetry"], **AUTHORITY_STAMP,
        }

    def get_run(self, rid: str) -> dict:
        if not self.configured:
            raise KeyError("canonical service not configured")
        rid = identifier(rid)
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._refresh(db)
            found = db.execute("SELECT document FROM runs WHERE id=?", (rid,)).fetchone()
            if not found:
                raise KeyError("unknown canonical run")
            return self._public_run(json.loads(found[0]), include_log=True)

    def get_watched(self, watch_id: str) -> dict:
        if not self.configured or watch_id not in self.watch_roots:
            raise KeyError("unknown watch root")
        return scan_watch_dir(self.watch_roots[watch_id]["path"], self.watch_roots[watch_id])

    def get_peer(self, peer_id: str) -> dict:
        if not self.configured:
            raise KeyError("unknown peer")
        return self.peers.get(peer_id)

    def bundle_manifest(self, rid: str) -> dict:
        self.get_run(rid)
        bdir = self.root / "runs" / identifier(rid) / "output" / "bundle"
        if bdir.is_symlink() or not bdir.is_dir():
            raise KeyError("bundle missing for run")
        base, files = bdir.resolve(), []
        for p in sorted(bdir.rglob("*")):
            if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(base):
                raise ValueError("unsafe file inside bundle directory")
            files.append({"path": p.relative_to(bdir).as_posix(), "bytes": p.stat().st_size,
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
        by_path = {f["path"]: f["sha256"] for f in files}
        return {"schema": "rosy.canonical-bundle-manifest.v1", "run_id": rid,
                "policy_revision": by_path.get("model.safetensors"), "onnx_sha256": by_path.get("model.onnx"), "files": files}

    def bundle_file(self, rid: str, relpath: str) -> bytes:
        self.get_run(rid)
        bdir = self.root / "runs" / identifier(rid) / "output" / "bundle"
        if bdir.is_symlink() or not bdir.is_dir():
            raise KeyError("bundle missing for run")
        if not relpath or relpath.startswith(("/", "\\")) or ".." in Path(relpath).parts or "\\" in relpath:
            raise ValueError("invalid bundle file relpath")
        target = bdir / relpath
        if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(bdir.resolve()):
            raise FileNotFoundError(relpath)
        return target.read_bytes()

    def refresh_peer(self, peer_id: str) -> dict:
        if not self.configured:
            raise KeyError("canonical service not configured")
        return self.peers.refresh(peer_id)

    def intake_collection(self, body: dict) -> dict:
        if not self.configured:
            raise ValueError("canonical service not configured")
        return handle_intake_request(self, body)

    def _resolve_ref(self, db, ref: str, *, expected_kinds: set[str], arm_id: str) -> dict:
        if not isinstance(ref, str) or not ref:
            raise ValueError("reference ID required")
        sources = {**scan_transferred_collections(self.collections_dir), **self.named_sources}
        if ref in sources:
            src = sources[ref]
            if src["kind"] not in expected_kinds or (src["arm_id"] and src["arm_id"] not in (arm_id, "arm_ab")):
                raise ValueError(f"source {ref} incompatible with kind/arm")
            return {"ref_type": "named_source", "path": str(src["path"])}
        rid = identifier(ref)
        found = db.execute("SELECT document FROM runs WHERE id=?", (rid,)).fetchone()
        if not found:
            raise ValueError(f"unknown referenced run or source: {ref}")
        row = json.loads(found[0])
        if row["status"] != "succeeded" or row["kind"] not in expected_kinds or row["arm_id"] != arm_id:
            raise ValueError("referenced run must be completed with matching kind and arm")
        out_dir = self.root / "runs" / rid / "output"
        sub = {"align_real": "aligned", "collect_dart": "dataset"}.get(row["kind"], "train/checkpoints/last/pretrained_model")
        return {"ref_type": "run", "run_id": rid, "path": str(out_dir / sub)}

    def _validate_and_resolve(self, db, body: dict) -> tuple[str, str, dict, dict]:
        if not isinstance(body, dict) or set(body) != {"request_id", "kind", "arm_id", "params"}:
            raise ValueError("canonical job request requires request_id, kind, arm_id, params")
        kind, arm_id, rp = body["kind"], body["arm_id"], body["params"]
        if kind not in JOB_KINDS or arm_id not in ARM_IDS or not isinstance(rp, dict):
            raise ValueError("unsupported canonical job kind, arm_id, or params")

        if kind == "align_real":
            if not {"source_id", "wrist_flip", "trim_dead_idle"} <= rp.keys() or set(rp) - {
                    "source_id", "wrist_flip", "trim_dead_idle", "legacy_map"}:
                raise ValueError("align_real params invalid")
            flip = _check_bool(rp["wrist_flip"], "wrist_flip")
            if flip and arm_id != "arm_b":
                raise ValueError("wrist_flip is valid for arm_b only")
            legacy = rp.get("legacy_map") or {}
            if not isinstance(legacy, dict) or len(legacy) > 8 or any(
                    not isinstance(k, str) or not _ID_RE.fullmatch(k) or v not in _CAM_ROLES for k, v in legacy.items()):
                raise ValueError("legacy_map values must be top|side|wrist")
            src = self._resolve_ref(db, rp["source_id"], expected_kinds={"real_dataset"}, arm_id=arm_id)
            pub = {"source_id": rp["source_id"], "wrist_flip": flip,
                   "trim_dead_idle": _check_bool(rp["trim_dead_idle"], "trim_dead_idle"), "legacy_map": dict(legacy)}
            return kind, arm_id, pub, {**pub, "source_path": src["path"]}

        if kind == "collect_dart":
            if set(rp) != {"episodes", "seed", "jitter_deg", "color_random", "pose_random"}:
                raise ValueError("collect_dart params invalid")
            pub = {"episodes": _check_int(rp["episodes"], 1, 1000, "episodes"), "seed": _check_int(rp["seed"], 0, 2147483647, "seed"),
                   "jitter_deg": _check_float(rp["jitter_deg"], 0.0, 5.0, "jitter_deg"),
                   "color_random": _check_bool(rp["color_random"], "color_random"), "pose_random": _check_bool(rp["pose_random"], "pose_random")}
            return kind, arm_id, pub, dict(pub)

        if kind == "train_stage":
            req = {"dataset_ref", "steps", "batch_size", "save_freq", "seed", "chunk_size", "n_action_steps", "use_vae", "kl_weight", "lr"}
            if not req <= rp.keys() or set(rp) - req - {"resume_run_id"}:
                raise ValueError("train_stage params invalid")
            cs, na = _check_int(rp["chunk_size"], 1, 100, "chunk_size"), _check_int(rp["n_action_steps"], 1, 100, "n_action_steps")
            if na > cs:
                raise ValueError("n_action_steps cannot exceed chunk_size")
            ds = self._resolve_ref(db, rp["dataset_ref"], expected_kinds={"real_dataset", "sim_dataset", "align_real", "collect_dart"}, arm_id=arm_id)
            pub = {
                "dataset_ref": rp["dataset_ref"], "steps": _check_int(rp["steps"], 1, 200000, "steps"),
                "batch_size": _check_int(rp["batch_size"], 1, 64, "batch_size"), "save_freq": _check_int(rp["save_freq"], 1, 200000, "save_freq"),
                "seed": _check_int(rp["seed"], 0, 2147483647, "seed"), "chunk_size": cs, "n_action_steps": na,
                "use_vae": _check_bool(rp["use_vae"], "use_vae"), "kl_weight": _check_float(rp["kl_weight"], 0.0, 1000.0, "kl_weight"),
                "lr": _check_float(rp["lr"], 1e-7, 1e-1, "lr"),
            }
            wrk = {**pub, "dataset_root": ds["path"]}
            if rp.get("resume_run_id"):
                prev = self._resolve_ref(db, rp["resume_run_id"], expected_kinds={"train_stage"}, arm_id=arm_id)
                pub["resume_run_id"] = rp["resume_run_id"]
                wrk["resume_train_dir"] = str((self.root / "runs" / prev["run_id"] / "output" / "train").resolve())
            return kind, arm_id, pub, wrk

        if kind == "eval_ladder":
            if set(rp) != {"checkpoint_ref", "task", "nominal_episodes", "delayed_episodes", "delay_frames", "n_action_steps", "seed_base"} or rp["task"] not in _L1_TASKS:
                raise ValueError("eval_ladder params invalid")
            ckpt = self._resolve_ref(db, rp["checkpoint_ref"], expected_kinds={"checkpoint", "train_stage"}, arm_id=arm_id)
            pub = {
                "checkpoint_ref": rp["checkpoint_ref"], "task": rp["task"],
                "nominal_episodes": _check_int(rp["nominal_episodes"], 10, 200, "nominal_episodes"),
                "delayed_episodes": _check_int(rp["delayed_episodes"], 10, 200, "delayed_episodes"),
                "delay_frames": _check_int(rp["delay_frames"], 1, 10, "delay_frames"),
                "n_action_steps": _check_int(rp["n_action_steps"], 1, 30, "n_action_steps"),
                "seed_base": _check_int(rp["seed_base"], 0, 1000000, "seed_base"),
            }
            return kind, arm_id, pub, {**pub, "checkpoint_dir": ckpt["path"]}

        if set(rp) != {"checkpoint_ref", "frames_source_id", "envelope_source_id"}:
            raise ValueError("cell_live_check params invalid")
        ckpt = self._resolve_ref(db, rp["checkpoint_ref"], expected_kinds={"checkpoint", "train_stage"}, arm_id=arm_id)
        frames = self._resolve_ref(db, rp["frames_source_id"], expected_kinds={"frames_dir"}, arm_id=arm_id)
        env = self._resolve_ref(db, rp["envelope_source_id"], expected_kinds={"chunk_library"}, arm_id=arm_id)
        pub = {"checkpoint_ref": rp["checkpoint_ref"], "frames_source_id": rp["frames_source_id"], "envelope_source_id": rp["envelope_source_id"]}
        return kind, arm_id, pub, {**pub, "checkpoint_dir": ckpt["path"], "frames_dir": frames["path"], "envelope_path": env["path"]}

    def start_job(self, body: dict, *, check_gpu: bool = True) -> dict:
        if not self.configured:
            raise ValueError("canonical service not configured")
        request_id = identifier(body.get("request_id"))
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._refresh(db)
            kind, arm_id, public_params, worker_params = self._validate_and_resolve(db, body)
            canon_req = json.dumps({"kind": kind, "arm_id": arm_id, "params": public_params}, sort_keys=True)
            if old := db.execute("SELECT document,request FROM runs WHERE request_id=?", (request_id,)).fetchone():
                if old[1] != canon_req:
                    raise ValueError("request_id already used with different inputs")
                return self._public_run(json.loads(old[0]))

            py_key = {"align_real": "train", "collect_dart": "sim", "train_stage": "train", "eval_ladder": "sim", "cell_live_check": "cell"}[kind]
            python = self.python.get(py_key) or next(iter(self.python.values()), None)
            if python is None:
                raise ValueError(f"learner python interpreter unavailable for {kind}")

            gpu_required = kind in GPU_KINDS
            active = [json.loads(r[0]) for r in db.execute("SELECT document FROM runs") if json.loads(r[0])["status"] in ("launching", "running", "stopping")]
            if gpu_required:
                if any(r["gpu_required"] for r in active):
                    raise BusyConflict("another GPU canonical job is already running")
                from experiment_cuda_train import check_job_locks
                from experiment_train import GpuBusy, gpu_lease

                try:
                    check_job_locks(self.jobs_dir)
                    if check_gpu and os.name == "posix":
                        with gpu_lease("cuda"):
                            pass
                except (ValueError, GpuBusy) as exc:
                    raise BusyConflict(str(exc)) from exc
            elif sum(1 for r in active if not r["gpu_required"]) >= CPU_SLOT_LIMIT:
                raise BusyConflict("both CPU canonical job slots are currently busy")

            rid = str(uuid.uuid4())
            rdir = self.root / "runs" / rid
            rdir.mkdir()
            write_json(rdir / "request.json", {
                "schema": REQUEST_SCHEMA, "run_id": rid, "kind": kind, "arm_id": arm_id,
                "spec": self.spec, "spec_sha256": self.spec_sha256,
                "jobs_dir": str(self.jobs_dir), "params": worker_params,
            })
            row = {
                "id": rid, "request_id": request_id, "kind": kind, "arm_id": arm_id,
                "gpu_required": gpu_required, "status": "launching", "created_at": time.time(), "params": public_params,
            }
            return self._spawn(db, row, request_id, canon_req, python, rdir)

    def _spawn(self, db, row: dict, request_id: str, canon_req: str, python: Path, rdir: Path) -> dict:
        rid = row["id"]
        db.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
            (rid, request_id, row["kind"], int(row["gpu_required"]), json.dumps(row), canon_req, json.dumps({"launcher": process_stamp(os.getpid())})),
        )
        db.commit()
        env = dict(os.environ, OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2",
                   HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                   TOKENIZERS_PARALLELISM="false", PYTHONUNBUFFERED="1")
        child = None
        try:
            with (rdir / "worker.log").open("wb") as log:
                child = subprocess.Popen(
                    [str(python), str(Path(__file__).with_name("canonical_workers.py")),
                     "--kind", row["kind"], "--request", str(rdir / "request.json"), "--out", str(rdir / "output")],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True,
                )
            receipt, deadline = None, time.monotonic() + 2.0
            while child.poll() is None:
                receipt = process_stamp(child.pid, rdir / "request.json")
                if receipt or time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            if not receipt:
                raise ValueError("canonical worker identity could not be established")
            row["status"] = "running"
            db.execute("UPDATE runs SET document=?,process=? WHERE id=?", (json.dumps(row), json.dumps(receipt), rid))
            db.commit()
            self.children[rid] = child
            if callable(getattr(child, "wait", None)):
                threading.Thread(target=self._reap, args=(rid, child), name=f"canon-reap-{rid[:8]}", daemon=True).start()
        except Exception:
            try:
                if child and child.poll() is None:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except (ProcessLookupError, OSError):
                        child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            child.kill()
                        try:
                            child.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            pass
            finally:
                row.update(status="failed", error="canonical worker launch failed")
                db.execute("UPDATE runs SET document=? WHERE id=?", (json.dumps(row), rid))
                db.commit()
            raise
        return self._public_run(row)

    def _reap(self, rid: str, child: subprocess.Popen) -> None:
        try:
            child.wait()
            if self.db and self.db.exists():
                with self.lock, self.connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    self._refresh(conn)
        except Exception:
            pass

    def cancel_job(self, rid: str) -> dict:
        if not self.configured:
            raise KeyError("canonical service not configured")
        rid = identifier(rid)
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._refresh(db)
            found = db.execute("SELECT document,process FROM runs WHERE id=?", (rid,)).fetchone()
            if not found:
                raise KeyError("unknown canonical run")
            row, receipt = map(json.loads, found)
            if row["status"] in ("running", "stopping"):
                if process_stamp(receipt.get("pid", -1), self.root / "runs" / rid / "request.json") != receipt:
                    raise ValueError("owned worker identity changed")
                try:
                    os.killpg(receipt["pid"], signal.SIGTERM)
                except ProcessLookupError:
                    pass
                row["status"] = "stopping"
                row.setdefault("cancel_at", time.time())
                db.execute("UPDATE runs SET document=? WHERE id=?", (json.dumps(row), rid))
            return self._public_run(row)
