#!/usr/bin/env python3
"""Multi-arm LAN HTTP inference server for per-arm 6-DoF ACT policies (D-1073).

Runs in the Learning GPU environment (`--device cuda` on `<ai-pc-host>`).
Imports `torch` and `lerobot` lazily inside `_load_lerobot_arm` only so
unit tests and hosts without those packages can verify routing, auth, revision
pinning, JPEG/shape validation, and fail-closed responses directly.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from hashlib import sha256
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
from pathlib import Path
import re
import socket
import threading
import time
from typing import Any, Callable, Sequence

try:
    from act_gpu_lock import gpu_training_status
except ImportError:
    from learning.training.omx.act_gpu_lock import gpu_training_status

SCHEMA = "rosy.omx-act-http.v1"
WEIGHTS = "model.safetensors"
CAMERA_ROLES = ("top", "side", "wrist")
JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
IMAGE_PREFIX = "observation.images."
GOAL_KEY = "observation.environment_state"
MAX_BODY_BYTES = 4 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def file_sha256(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def parse_arm_spec(spec: str) -> tuple[str, Path, str]:
    """Parse `arm_id=policy_dir:sha256` while preserving Windows drive colons."""
    if "=" not in spec:
        raise ValueError(f"invalid --arm spec {spec!r}; expected arm_id=dir:sha256")
    arm_id, rest = spec.split("=", 1)
    if ":" not in rest:
        raise ValueError(f"invalid --arm spec {spec!r}; missing :sha256")
    raw_dir, revision = rest.rsplit(":", 1)
    arm_id = arm_id.strip()
    revision = revision.strip()
    if not arm_id or not raw_dir.strip():
        raise ValueError(f"invalid --arm spec {spec!r}; empty arm_id or directory")
    if not _HEX64.match(revision):
        raise ValueError(f"invalid --arm revision {revision!r}; expected 64-char lowercase hex sha256")
    return arm_id, Path(raw_dir.strip()).expanduser().resolve(), revision


def read_policy_spec(policy_dir: Path) -> tuple[dict[str, tuple[int, int]], int, int | None, int, int]:
    """Validate ACT config.json shape and return (views, state_dim, goal_size, n_action_steps, chunk_size)."""
    cfg_path = policy_dir / "config.json"
    if not cfg_path.is_file():
        raise ValueError(f"missing {cfg_path}")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if cfg.get("type") != "act":
        raise ValueError(f"only ACT checkpoints are supported, got {cfg.get('type')!r}")
    in_feat = cfg.get("input_features") or {}
    out_feat = cfg.get("output_features") or {}
    state_shape = (in_feat.get("observation.state") or {}).get("shape")
    action_shape = (out_feat.get("action") or {}).get("shape")
    if state_shape != [6] or action_shape != [6]:
        raise ValueError(f"6-DoF ACT state/action required, got state={state_shape}, action={action_shape}")

    views: dict[str, tuple[int, int]] = {}
    for key, spec in in_feat.items():
        if not key.startswith(IMAGE_PREFIX):
            continue
        role = key[len(IMAGE_PREFIX):]
        if role not in CAMERA_ROLES:
            raise ValueError(f"unsupported D-1065 camera role {role!r}; allowed: {CAMERA_ROLES}")
        shape = (spec or {}).get("shape")
        if not (isinstance(shape, list) and len(shape) == 3 and shape[0] == 3 and not isinstance(shape[0], bool)
                and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in shape)):
            raise ValueError(f"camera {role!r} must have shape [3, H, W], got {shape!r}")
        views[role] = (int(shape[1]), int(shape[2]))
    if not views:
        raise ValueError("policy config.json declares no visual camera inputs")

    goal_shape = (in_feat.get(GOAL_KEY) or {}).get("shape") if GOAL_KEY in in_feat else None
    goal_size: int | None = None
    if goal_shape is not None:
        if not (isinstance(goal_shape, list) and len(goal_shape) == 1
                and isinstance(goal_shape[0], int) and not isinstance(goal_shape[0], bool) and goal_shape[0] > 0):
            raise ValueError(f"invalid goal shape {goal_shape!r}")
        goal_size = int(goal_shape[0])

    n_action_steps = cfg.get("n_action_steps")
    chunk_size = cfg.get("chunk_size")
    if (not isinstance(n_action_steps, int) or isinstance(n_action_steps, bool) or n_action_steps < 1
            or not isinstance(chunk_size, int) or isinstance(chunk_size, bool)
            or chunk_size < n_action_steps):
        raise ValueError(f"invalid n_action_steps={n_action_steps!r} / chunk_size={chunk_size!r}")
    return views, 6, goal_size, n_action_steps, chunk_size


def decode_jpeg_rgb(raw: bytes, expected_hw: tuple[int, int]) -> Any:
    """Decode JPEG bytes into uint8 RGB (H, W, 3) matching `expected_hw`."""
    if not raw:
        raise ValueError("empty JPEG payload")
    import numpy as np

    h, w = expected_hw
    try:
        import cv2
        arr = np.frombuffer(raw, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("cv2.imdecode returned None")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except ImportError:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as img:
            rgb = np.asarray(img.convert("RGB"), dtype=np.uint8)

    if rgb.ndim != 3 or rgb.shape != (h, w, 3) or rgb.dtype != np.uint8:
        raise ValueError(f"decoded frame shape/dtype {rgb.shape}/{rgb.dtype} != expected ({h}, {w}, 3)/uint8")
    return rgb


def _is_finite_floats(values: Any, length: int) -> list[float] | None:
    if not isinstance(values, (list, tuple)) or len(values) != length:
        return None
    out: list[float] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            return None
        out.append(float(v))
    return out


@dataclass(frozen=True)
class ArmEntry:
    arm_id: str
    policy_dir: Path
    revision: str
    views: dict[str, tuple[int, int]]
    n_action_steps: int
    chunk_size: int
    goal_size: int | None
    predict: Callable[[dict[str, Any]], list[list[float]]]


def _load_lerobot_arm(
    policy_dir: Path, views: dict[str, tuple[int, int]], n_action_steps: int, goal_size: int | None, device: str,
) -> Callable[[dict[str, Any]], list[list[float]]]:
    """Load ACTPolicy lazily so non-torch environments never import torch/lerobot."""
    import numpy as np
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    target_device = torch.device(device)
    policy = ACTPolicy.from_pretrained(str(policy_dir), local_files_only=True)
    policy.config.device = device
    policy.to(target_device).eval()
    pre, post = make_pre_post_processors(
        policy.config,
        pretrained_path=str(policy_dir),
        preprocessor_overrides={"device_processor": {"device": device}},
        postprocessor_overrides={"device_processor": {"device": "cpu"}},
    )

    def predict(obs: dict[str, Any]) -> list[list[float]]:
        batch: dict[str, Any] = {
            "observation.state": torch.tensor(obs["state"], dtype=torch.float32).unsqueeze(0),
        }
        if goal_size is not None:
            batch[GOAL_KEY] = torch.tensor(obs["goal"], dtype=torch.float32).unsqueeze(0)
        for role in views:
            rgb = obs["frames_rgb"][role]
            img = torch.from_numpy(np.ascontiguousarray(rgb)).permute(2, 0, 1).float().unsqueeze(0) / 255.0
            batch[f"{IMAGE_PREFIX}{role}"] = img

        with torch.inference_mode():
            chunk = policy.predict_action_chunk(pre(batch))
            arr = np.asarray(post(chunk).detach().cpu().numpy(), dtype=np.float64).reshape(-1, len(JOINT_NAMES))
        return [[float(x) for x in r] for r in arr[:n_action_steps]]

    return predict


class PolicyRegistry:
    """Thread-safe pinned multi-arm ACT inference registry."""

    def __init__(
        self,
        entries: Sequence[ArmEntry],
        *,
        gpu_lock_file: Path | None = None,
        jobs_dir: Path | None = None,
        reject_when_training_busy: bool = False,
        gpu_status_fn: Callable[[], tuple[bool, str | None]] | None = None,
    ):
        if not entries:
            raise ValueError("PolicyRegistry requires at least one arm entry")
        self._arms: dict[str, ArmEntry] = {}
        for entry in entries:
            if entry.arm_id in self._arms:
                raise ValueError(f"duplicate arm_id {entry.arm_id!r}")
            self._arms[entry.arm_id] = entry
        self.infer_lock = threading.Lock()
        self._reject_when_training_busy = bool(reject_when_training_busy)
        self._gpu_status_fn = (
            gpu_status_fn
            if gpu_status_fn is not None
            else ((lambda: gpu_training_status(gpu_lock_file, jobs_dir)) if (gpu_lock_file is not None or jobs_dir is not None) else None)
        )

    @classmethod
    def from_specs(
        cls,
        specs: Sequence[str],
        *,
        device: str = "cpu",
        loader: Callable[[Path, dict[str, tuple[int, int]], int, int | None, str], Any] | None = None,
        gpu_lock_file: Path | None = None,
        jobs_dir: Path | None = None,
        reject_when_training_busy: bool = False,
        gpu_status_fn: Callable[[], tuple[bool, str | None]] | None = None,
    ) -> "PolicyRegistry":
        load_fn = loader or _load_lerobot_arm
        entries: list[ArmEntry] = []
        for raw in specs:
            arm_id, pdir, revision = parse_arm_spec(raw)
            if not pdir.is_dir():
                raise ValueError(f"policy_dir {pdir} does not exist")
            weights = pdir / WEIGHTS
            if not weights.is_file():
                raise ValueError(f"missing {weights}")
            actual = file_sha256(weights)
            if actual != revision:
                raise ValueError(f"{arm_id}: {WEIGHTS} sha256 {actual} != pinned {revision}")
            views, _dim, goal_size, n_steps, chunk_sz = read_policy_spec(pdir)
            predict = load_fn(pdir, views, n_steps, goal_size, device)
            entries.append(ArmEntry(arm_id, pdir, revision, views, n_steps, chunk_sz, goal_size, predict))
        return cls(
            entries,
            gpu_lock_file=gpu_lock_file,
            jobs_dir=jobs_dir,
            reject_when_training_busy=reject_when_training_busy,
            gpu_status_fn=gpu_status_fn,
        )

    def _training_status(self) -> tuple[bool, str | None]:
        return (False, None) if self._gpu_status_fn is None else self._gpu_status_fn()

    def health_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "ok": True,
            "arms": {
                arm_id: {
                    "revision": e.revision,
                    "views": {role: [hw[0], hw[1]] for role, hw in e.views.items()},
                    "n_action_steps": e.n_action_steps,
                    "chunk_size": e.chunk_size,
                    "goal_size": e.goal_size,
                }
                for arm_id, e in self._arms.items()
            },
        }
        if self._gpu_status_fn is not None:
            busy, reason = self._training_status()
            payload["gpu_training_busy"] = bool(busy)
            payload["gpu_training_reason"] = reason
        return payload

    def infer(self, req: Any) -> tuple[int, dict[str, Any]]:
        if not isinstance(req, dict):
            return 400, {"ok": False, "error": "request body must be a JSON object"}
        req_id = req.get("request_id")
        if req_id is not None and (not isinstance(req_id, str) or not (1 <= len(req_id) <= 128) or not req_id.strip()):
            return 400, {"ok": False, "error": "request_id must be a non-empty string (<=128 chars)"}
        arm_id = req.get("arm_id")
        if not isinstance(arm_id, str) or arm_id not in self._arms:
            return 404, {"ok": False, "error": f"unknown arm_id {arm_id!r}"}
        entry = self._arms[arm_id]

        revision = req.get("revision")
        if revision != entry.revision:
            return 409, {"ok": False, "error": f"revision mismatch: expected {entry.revision}, got {revision!r}"}

        if self._reject_when_training_busy:
            busy, reason = self._training_status()
            if busy:
                return 503, {
                    "ok": False,
                    "error": "gpu_training_busy",
                    "reason": reason,
                    **({"request_id": req_id} if req_id is not None else {}),
                }

        state = _is_finite_floats(req.get("state"), 6)
        if state is None:
            return 400, {"ok": False, "error": "state must be 6 finite numbers"}

        raw_goal = req.get("goal")
        goal: list[float] | None = None
        if entry.goal_size is None:
            if raw_goal is not None:
                return 400, {"ok": False, "error": "policy expects no goal"}
        else:
            goal = _is_finite_floats(raw_goal, entry.goal_size)
            if goal is None:
                return 400, {"ok": False, "error": f"goal must be {entry.goal_size} finite numbers"}

        frames_b64 = req.get("frames")
        if not isinstance(frames_b64, dict) or set(frames_b64) != set(entry.views):
            return 400, {
                "ok": False,
                "error": f"frames must match exact views {sorted(entry.views)}",
            }
        decoded: dict[str, Any] = {}
        for role, hw in entry.views.items():
            b64 = frames_b64.get(role)
            if not isinstance(b64, str) or not b64:
                return 400, {"ok": False, "error": f"frame {role!r} must be a non-empty base64 string"}
            try:
                raw_bytes = base64.b64decode(b64, validate=True)
                decoded[role] = decode_jpeg_rgb(raw_bytes, hw)
            except Exception as exc:
                return 400, {"ok": False, "error": f"invalid JPEG frame {role!r}: {type(exc).__name__}"}

        t0 = time.perf_counter()
        try:
            with self.infer_lock:
                raw_chunk = entry.predict({
                    "arm_id": arm_id,
                    "state": state,
                    "frames_rgb": decoded,
                    "goal": goal,
                })
        except Exception as exc:
            return 500, {"ok": False, "error": f"inference failed: {type(exc).__name__}"}

        if not isinstance(raw_chunk, (list, tuple)) or not (1 <= len(raw_chunk) <= entry.chunk_size):
            return 500, {"ok": False, "error": "invalid predicted chunk length"}
        validated: list[list[float]] = []
        for row in raw_chunk:
            vec = _is_finite_floats(row, 6)
            if vec is None:
                return 500, {"ok": False, "error": "non-finite or malformed action row"}
            validated.append(vec)
        return 200, {
            "schema": SCHEMA,
            "ok": True,
            **({"request_id": req_id} if req_id is not None else {}),
            "arm_id": arm_id,
            "revision": entry.revision,
            "chunk": validated,
            "infer_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }


def make_server(
    bind: str,
    port: int,
    registry: PolicyRegistry,
    *,
    token: str | None = None,
    max_body_bytes: int = MAX_BODY_BYTES,
) -> ThreadingHTTPServer:
    """Create a multi-threaded HTTP server enforcing Bearer auth off-loopback and bounded bodies."""
    if token is not None and (not isinstance(token, str) or not token.strip()):
        raise ValueError("token must be a non-empty string when provided")
    if bind not in _LOOPBACK_HOSTS and token is None:
        raise ValueError(f"refusing unauthenticated bind on non-loopback host {bind!r}")
    expected_token = token.encode("utf-8") if token is not None else None

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 60.0

        def setup(self) -> None:
            super().setup()
            try:
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, status: int, body: dict[str, Any], *, close: bool = False) -> None:
            raw = json.dumps(body).encode("utf-8")
            if close:
                self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if close:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            close = "Content-Length" in self.headers or "Transfer-Encoding" in self.headers
            if self.path != "/health":
                self._send_json(404, {"ok": False, "error": "not found"}, close=close)
                return
            self._send_json(200, registry.health_payload(), close=close)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/infer":
                self._send_json(404, {"ok": False, "error": "not found"}, close=True)
                return
            if expected_token is not None:
                auth = self.headers.get("Authorization") or ""
                if not auth.startswith("Bearer "):
                    self._send_json(401, {"ok": False, "error": "missing bearer token"}, close=True)
                    return
                presented = auth[len("Bearer "):].encode("utf-8")
                if not hmac.compare_digest(presented, expected_token):
                    self._send_json(401, {"ok": False, "error": "invalid bearer token"}, close=True)
                    return

            if "Transfer-Encoding" in self.headers:
                self._send_json(400, {"ok": False, "error": "Transfer-Encoding not supported"}, close=True)
                return
            raw_lens = self.headers.get_all("Content-Length") or []
            if not raw_lens:
                self._send_json(411, {"ok": False, "error": "Content-Length required"}, close=True)
                return
            if len(raw_lens) > 1:
                self._send_json(400, {"ok": False, "error": "multiple Content-Length headers"}, close=True)
                return
            raw_len = raw_lens[0].strip(" \t")
            if not raw_len or not raw_len.isascii() or not raw_len.isdigit():
                self._send_json(400, {"ok": False, "error": "invalid Content-Length"}, close=True)
                return
            norm_len = raw_len.lstrip("0") or "0"
            if len(norm_len) > len(str(max_body_bytes)) or int(norm_len) > max_body_bytes:
                self._send_json(413, {"ok": False, "error": "request body exceeds max_body_bytes"}, close=True)
                return
            content_len = int(norm_len)

            raw_body = self.rfile.read(content_len)
            if len(raw_body) != content_len:
                self._send_json(400, {"ok": False, "error": "truncated request body"}, close=True)
                return
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "invalid JSON"}, close=True)
                return

            status, reply = registry.infer(payload)
            self._send_json(status, reply)

    class _HTTPServer(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True
        block_on_close = False

        def __init__(self, server_address, RequestHandlerClass):
            self._active_lock = threading.Lock()
            self._active_socks: set[socket.socket] = set()
            self._closed = False
            super().__init__(server_address, RequestHandlerClass)

        @staticmethod
        def _close_sock(sock: socket.socket) -> None:
            for fn in (lambda s=sock: s.shutdown(socket.SHUT_RDWR), lambda s=sock: s.close()):
                try:
                    fn()
                except OSError:
                    pass

        def process_request(self, request, client_address):
            with self._active_lock:
                closed = self._closed
                if not closed:
                    self._active_socks.add(request)
            if closed:
                self._close_sock(request)
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                with self._active_lock:
                    self._active_socks.discard(request)
                self._close_sock(request)
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                with self._active_lock:
                    self._active_socks.discard(request)

        def server_close(self) -> None:
            with self._active_lock:
                self._closed = True
                socks = list(self._active_socks)
                self._active_socks.clear()
            for sock in socks:
                self._close_sock(sock)
            super().server_close()

    return _HTTPServer((bind, port), Handler)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--allow-insecure-loopback", action="store_true")
    parser.add_argument("--arm", action="append", default=[], metavar="ARM_ID=DIR:SHA256")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--gpu-lock-file", type=Path)
    parser.add_argument("--jobs-dir", type=Path)
    parser.add_argument("--reject-when-training-busy", action="store_true")
    args = parser.parse_args(argv)

    cfg = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    bind = str(cfg.get("bind", args.bind))
    port = int(cfg.get("port", args.port))
    device = str(cfg.get("device", args.device))
    token_file = Path(cfg["token_file"]).expanduser() if "token_file" in cfg else args.token_file
    gpu_lock_file = Path(cfg["gpu_lock_file"]).expanduser() if "gpu_lock_file" in cfg else args.gpu_lock_file
    jobs_dir = Path(cfg["jobs_dir"]).expanduser() if "jobs_dir" in cfg else args.jobs_dir
    reject_busy = bool(cfg.get("reject_when_training_busy", args.reject_when_training_busy))
    arms = list(cfg.get("arms", [])) + list(args.arm)
    if not arms:
        raise SystemExit("at least one --arm spec (or config arms) is required")

    token: str | None = None
    if token_file is not None:
        token = token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise SystemExit(f"empty token file {token_file}")
    elif args.allow_insecure_loopback:
        if bind not in _LOOPBACK_HOSTS:
            raise SystemExit(f"--allow-insecure-loopback requires loopback bind host, got {bind!r}")
    else:
        raise SystemExit("provide --token-file (or --allow-insecure-loopback on localhost)")

    registry = PolicyRegistry.from_specs(
        arms,
        device=device,
        gpu_lock_file=gpu_lock_file,
        jobs_dir=jobs_dir,
        reject_when_training_busy=reject_busy,
    )
    server = make_server(bind, port, registry, token=token)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
