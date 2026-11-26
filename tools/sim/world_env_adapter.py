"""Single-contract environment adapters and parity verification for ROSY World.

Only the simulation/physical environment backend differs across deployments:
the site map, registration, Pinky Pro + J-v3 cargo tray URDF geometry, and
OMX-AI fleet identities stay invariant and fail closed under parity checks.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Protocol
import urllib.error
import urllib.request

BACKENDS = ("real", "isaac", "gazebo", "mujoco")
ENV_DESCRIPTOR_SCHEMA = "rosy.world.env-descriptor.v1"
FACTORY_STATE_SCHEMA = "rosy.world.factory-state.v1"
PARITY_SCHEMA = "rosy.world.parity.v1"
WORLD_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CANONICAL_FLEET_ROBOTS = {
    "pinkys": ["rosy_42", "rosy_45", "rosy_46"],
    "arms": ["arm_s", "arm_a", "arm_b"],
}
LIVE_FRESH_MS = 3000


def _reject_constant(token: str) -> Any:
    raise ValueError(f"non-finite JSON constant not allowed: {token}")


def load_pinky_tray_fingerprint(geometry_yaml_path: Path) -> dict[str, float]:
    """Parse the URDF-derived cargo_tray section from geometry.yaml without PyYAML."""
    lines = geometry_yaml_path.read_text(encoding="utf-8").splitlines()
    in_section = False
    tray: dict[str, float] = {}
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw.startswith(" ") and stripped.endswith(":"):
            in_section = stripped == "cargo_tray:"
            continue
        if in_section and raw.startswith("  ") and ":" in stripped:
            key, _, val = stripped.partition(":")
            tray[key.strip()] = float(val.strip())
    required = ("rear_x_m", "half_width_m", "pocket_x_m", "pocket_y_m", "pocket_z_m", "rotation_radius_m")
    missing = [k for k in required if k not in tray]
    if missing:
        raise ValueError(f"{geometry_yaml_path}: missing cargo_tray keys {missing}")
    return tray


def build_parity_fingerprint(
    *,
    site_map_sha256: str,
    registration_sha256: str | None = None,
    fleet_robots: dict[str, list[str]] | None = None,
    has_cargo_tray: bool = True,
    cargo_tray: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build canonical map + fleet + J-v3 tray parity fingerprint."""
    return {
        "schema": PARITY_SCHEMA,
        "site_map_sha256": str(site_map_sha256 or "").lower(),
        "registration_sha256": str(registration_sha256).lower() if registration_sha256 else None,
        "fleet_robots": fleet_robots or {k: list(v) for k, v in CANONICAL_FLEET_ROBOTS.items()},
        "has_cargo_tray": bool(has_cargo_tray),
        "cargo_tray": dict(cargo_tray) if cargo_tray else None,
    }


def verify_parity(reference: dict[str, Any], candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Fail-closed check guaranteeing ONLY the environment adapter differs from real."""
    reasons: list[str] = []
    if not isinstance(candidate, dict):
        return {
            "ok": False, "map_match": False, "robot_match": False,
            "tray_match": False, "reasons": ["missing_parity_metadata"],
        }

    ref_map = str(reference.get("site_map_sha256") or "").lower()
    cand_map = str(candidate.get("site_map_sha256") or "").lower()
    map_match = bool(SHA256_RE.fullmatch(ref_map) and cand_map == ref_map)
    if not map_match:
        reasons.append("site_map_sha256_mismatch")

    ref_reg = reference.get("registration_sha256")
    cand_reg = candidate.get("registration_sha256")
    if ref_reg and cand_reg and str(cand_reg).lower() != str(ref_reg).lower():
        map_match = False
        reasons.append("registration_sha256_mismatch")

    ref_robots = reference.get("fleet_robots") or CANONICAL_FLEET_ROBOTS
    cand_robots = candidate.get("fleet_robots")
    robot_match = (
        isinstance(cand_robots, dict)
        and cand_robots.get("pinkys") == ref_robots.get("pinkys")
        and cand_robots.get("arms") == ref_robots.get("arms")
    )
    if not robot_match:
        reasons.append("fleet_robots_mismatch")

    has_tray = candidate.get("has_cargo_tray") is True
    tray_match = has_tray
    ref_tray = reference.get("cargo_tray")
    cand_tray = candidate.get("cargo_tray")
    if not has_tray:
        reasons.append("missing_pinky_cargo_tray")
    elif isinstance(ref_tray, dict) and isinstance(cand_tray, dict):
        for key in ("pocket_x_m", "pocket_z_m", "rear_x_m"):
            rv, cv = ref_tray.get(key), cand_tray.get(key)
            if not (isinstance(rv, (int, float)) and isinstance(cv, (int, float)) and math.isfinite(cv)):
                tray_match = False
                reasons.append(f"invalid_tray_{key}")
            elif abs(float(rv) - float(cv)) > 1e-4:
                tray_match = False
                reasons.append(f"tray_{key}_mismatch")

    return {
        "ok": map_match and robot_match and tray_match and not reasons,
        "map_match": map_match,
        "robot_match": robot_match,
        "tray_match": tray_match,
        "reasons": reasons,
    }


def validate_world_id(world_id: str) -> str:
    """Validate a single-path-component world identifier (no traversal)."""
    if not isinstance(world_id, str) or ".." in world_id or not WORLD_ID_RE.fullmatch(world_id):
        raise ValueError(f"invalid world_id: {world_id!r}")
    return world_id


def read_snapshot_json(path: Path) -> dict[str, Any]:
    """Read a JSON snapshot strictly rejecting NaN/Infinity."""
    data = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")
    return data


def write_world_snapshot(worlds_dir: Path, world_id: str, state: dict[str, Any]) -> Path:
    """Atomically write `worlds_dir/<world_id>.json` without NaN/partial writes."""
    wid = validate_world_id(world_id)
    root = worlds_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / f"{wid}.json").resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"world snapshot path escapes directory: {target}")
    raw = (json.dumps(state, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=f".{wid}.", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(temp_path, target)
                temp_path = None
                return target
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return target


class WorldEnvAdapter(Protocol):
    backend: str
    world_id: str

    def descriptor(self) -> dict[str, Any]: ...
    def poll_state(self, now_ms: int | None = None) -> dict[str, Any] | None: ...
    def close(self) -> None: ...


class _BaseFileAdapter:
    backend: str = "mujoco"
    # No unbacked control claims: only an explicit capabilities=(...) argument advertises commands.
    default_capabilities: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        world_id: str,
        snapshot_path: Path,
        parity: dict[str, Any],
        run_id: str,
        physics_profile: str = "default",
        ros_domain_id: int | None = None,
        capabilities: tuple[str, ...] | None = None,
    ) -> None:
        self.world_id = validate_world_id(world_id)
        self.snapshot_path = Path(snapshot_path)
        self.parity = dict(parity)
        self.run_id = run_id
        self.physics_profile = physics_profile
        self.ros_domain_id = ros_domain_id
        self.capabilities = self.default_capabilities if capabilities is None else tuple(capabilities)

    def descriptor(self) -> dict[str, Any]:
        return {
            "schema": ENV_DESCRIPTOR_SCHEMA,
            "world_id": self.world_id,
            "backend": self.backend,
            "run_id": self.run_id,
            "ros_domain_id": self.ros_domain_id,
            "physics_profile": self.physics_profile,
            "parity": self.parity,
            "capabilities": list(self.capabilities),
        }

    def poll_state(self, now_ms: int | None = None) -> dict[str, Any] | None:
        if not self.snapshot_path.is_file():
            return None
        try:
            data = read_snapshot_json(self.snapshot_path)
        except (OSError, ValueError):
            return None
        obs = data.get("observed_at_ms")
        now = time.time_ns() // 1_000_000 if now_ms is None else now_ms
        if not isinstance(obs, int) or abs(now - obs) > LIVE_FRESH_MS:
            return None
        data["world_id"] = self.world_id
        data["adapter"] = self.backend
        data.setdefault("env", self.descriptor())
        data.setdefault("parity", self.parity)
        return data

    def close(self) -> None:
        return None


class RealAdapter(_BaseFileAdapter):
    """Strict read-only physical Fleet/CORE adapter. Zero control, zero fake replay fallback."""
    backend = "real"
    default_capabilities: tuple[str, ...] = ()

    def __init__(self, **kwargs: Any) -> None:
        kwargs["capabilities"] = ()
        kwargs.setdefault("physics_profile", "hardware")
        super().__init__(**kwargs)

    def poll_state(self, now_ms: int | None = None) -> dict[str, Any] | None:
        state = super().poll_state(now_ms=now_ms)
        if state is None:
            return None
        if state.get("stream_mode") not in ("live", None):
            return None
        state["stream_mode"] = "live"
        return state


class IsaacAdapter(_BaseFileAdapter):
    backend = "isaac"


class GazeboAdapter(_BaseFileAdapter):
    backend = "gazebo"


class MuJoCoAdapter(_BaseFileAdapter):
    backend = "mujoco"


_ADAPTER_CLASSES: dict[str, type[_BaseFileAdapter]] = {
    "real": RealAdapter,
    "isaac": IsaacAdapter,
    "gazebo": GazeboAdapter,
    "mujoco": MuJoCoAdapter,
}


def create_adapter(backend: str, **kwargs: Any) -> WorldEnvAdapter:
    """Instantiate an environment adapter while keeping map & robot contracts invariant."""
    cls = _ADAPTER_CLASSES.get(backend)
    if cls is None:
        raise ValueError(f"unsupported environment backend {backend!r}; expected {BACKENDS}")
    return cls(**kwargs)


def _ingest_headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def push_world_snapshot(
    world_url: str,
    world_id: str,
    state: dict[str, Any],
    *,
    token: str | None = None,
    timeout_s: float = 1.5,
) -> dict[str, Any]:
    """Push one canonical factory-state snapshot to a remote/local Rosy World HTTP server."""
    wid = validate_world_id(world_id)
    endpoint = f"{world_url.rstrip('/')}/api/worlds/{wid}"
    raw = json.dumps(state, allow_nan=False, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(endpoint, data=raw, headers=_ingest_headers(token), method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"), parse_constant=_reject_constant)


def delete_world_snapshot(
    world_url: str,
    world_id: str,
    *,
    token: str | None = None,
    timeout_s: float = 1.5,
) -> dict[str, Any]:
    """Delete a published world snapshot from a Rosy World HTTP server."""
    wid = validate_world_id(world_id)
    endpoint = f"{world_url.rstrip('/')}/api/worlds/{wid}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(endpoint, headers=headers, method="DELETE")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"), parse_constant=_reject_constant)


def _resolve_world_url(mdns_host: str, port: int) -> str:
    here = Path(__file__).resolve().parent
    candidates = (here, *((here.parents[1] / "applications" / "world",) if len(here.parents) > 1 else ()))
    import sys

    for cand in candidates:
        if (cand / "world_mdns.py").is_file() and str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
    import world_mdns

    return world_mdns.discover_world_endpoint(mdns_host, default_port=port)


class WorldPublisher:
    """Dual-transport snapshot publisher supporting local atomic files and HTTP push (static or mDNS)."""

    def __init__(
        self,
        *,
        world_id: str,
        worlds_dir: Path | None = None,
        world_url: str | None = None,
        world_mdns_host: str | None = None,
        world_mdns_port: int = 8140,
        token: str | None = None,
        timeout_s: float = 1.5,
        best_effort: bool = True,
    ) -> None:
        self.world_id = validate_world_id(world_id)
        self.worlds_dir = Path(worlds_dir) if worlds_dir is not None else None
        self.world_url = world_url.rstrip("/") if world_url else None
        self.world_mdns_host = world_mdns_host.strip() if world_mdns_host else None
        self.world_mdns_port = int(world_mdns_port)
        self.token = token or None
        self.timeout_s = float(timeout_s)
        self.best_effort = bool(best_effort)
        self._last_warn_s = -1e9

    def _warn(self, msg: object) -> None:
        now = time.monotonic()
        if (now - self._last_warn_s) >= 10.0:
            self._last_warn_s = now
            print(f"WorldPublisher [{self.world_id}]: {msg}", file=sys.stderr, flush=True)

    def _target_url(self) -> str | None:
        if self.world_url is not None:
            return self.world_url
        if self.world_mdns_host:
            self.world_url = _resolve_world_url(self.world_mdns_host, self.world_mdns_port).rstrip("/")
            return self.world_url
        return None

    def publish(self, state: dict[str, Any]) -> bool:
        ok = True
        if self.worlds_dir is not None:
            try:
                write_world_snapshot(self.worlds_dir, self.world_id, state)
            except (OSError, ValueError):
                if not self.best_effort:
                    raise
                ok = False
        try:
            url = self._target_url()
        except (OSError, urllib.error.URLError, ValueError):
            if not self.best_effort:
                raise
            return False
        if url is not None:
            try:
                push_world_snapshot(
                    url, self.world_id, state, token=self.token, timeout_s=self.timeout_s,
                )
            except (OSError, urllib.error.URLError, ValueError) as exc:
                if self.world_mdns_host:
                    self.world_url = None
                if not self.best_effort:
                    raise
                self._warn(exc)
                ok = False
        return ok

    def cleanup(self) -> None:
        if self.worlds_dir is not None:
            target = self.worlds_dir.resolve() / f"{self.world_id}.json"
            try:
                target.unlink(missing_ok=True)
            except OSError:
                if not self.best_effort:
                    raise
        try:
            url = self._target_url()
        except (OSError, urllib.error.URLError, ValueError):
            if not self.best_effort:
                raise
            return
        if url is not None:
            try:
                delete_world_snapshot(url, self.world_id, token=self.token, timeout_s=self.timeout_s)
            except (OSError, urllib.error.URLError, ValueError):
                if not self.best_effort:
                    raise


class TrainingWorldHook:
    """Rate-limited callback hook emitting canonical live telemetry from sim/RL loops."""

    def __init__(
        self,
        *,
        world_id: str,
        backend: str,
        run_id: str,
        site_map_sha256: str,
        worlds_dir: Path | None = None,
        world_url: str | None = None,
        world_mdns_host: str | None = None,
        world_mdns_port: int = 8140,
        token: str | None = None,
        min_interval_s: float = 0.2,
        physics_profile: str = "default",
        ros_domain_id: int | None = None,
        cargo_tray: dict[str, float] | None = None,
        registration_sha256: str | None = None,
        best_effort: bool = True,
    ) -> None:
        if backend not in BACKENDS:
            raise ValueError(f"unsupported backend {backend!r}")
        self.world_id = validate_world_id(world_id)
        self.backend = backend
        self.run_id = run_id
        self.physics_profile = physics_profile
        self.ros_domain_id = ros_domain_id
        self.min_interval_s = max(0.0, float(min_interval_s))
        self._last_publish_s = -1e9
        self.parity = build_parity_fingerprint(
            site_map_sha256=site_map_sha256,
            registration_sha256=registration_sha256,
            has_cargo_tray=True,
            cargo_tray=cargo_tray,
        )
        self.descriptor = {
            "schema": ENV_DESCRIPTOR_SCHEMA,
            "world_id": self.world_id,
            "backend": self.backend,
            "run_id": self.run_id,
            "ros_domain_id": self.ros_domain_id,
            "physics_profile": self.physics_profile,
            "parity": self.parity,
            "capabilities": [],
        }
        self.publisher = WorldPublisher(
            world_id=self.world_id,
            worlds_dir=worlds_dir,
            world_url=world_url,
            world_mdns_host=world_mdns_host,
            world_mdns_port=world_mdns_port,
            token=token,
            best_effort=best_effort,
        )

    def publish_step(
        self,
        *,
        sim_time_s: float,
        stage: str,
        phase: str,
        pinky: dict[str, Any],
        pinkys: list[dict[str, Any]] | None = None,
        arms: dict[str, list[float]] | None = None,
        arms_observed: dict[str, bool] | None = None,
        cargo: dict[str, Any] | None = None,
        cell_ab: dict[str, Any] | None = None,
        episode: int | None = None,
        step: int | None = None,
        reward: float | None = None,
        loss: float | None = None,
        success_rate: float | None = None,
        sim_fps: float | None = None,
        force: bool = False,
    ) -> bool:
        now = time.monotonic()
        if not force and (now - self._last_publish_s) < self.min_interval_s:
            return False
        self._last_publish_s = now
        training = {
            k: v for k, v in (
                ("episode", episode),
                ("step", step),
                ("reward", reward),
                ("loss", loss),
                ("success_rate", success_rate),
                ("sim_fps", sim_fps),
                ("physics_profile", self.physics_profile),
            ) if v is not None
        }
        active_pinkys = list(pinkys) if pinkys is not None else [
            {"id": pinky.get("id", "rosy_45"), "pose_m": pinky["pose_m"], "yaw_rad": pinky["yaw_rad"], "observed": True},
        ]
        # Canonical fleet list keeps rosy_42/45/46 explicit even when a single robot RL env drives one Pinky.
        present_ids = {item.get("id") for item in active_pinkys if isinstance(item, dict)}
        defaults = {
            "rosy_42": [-0.414, 0.47, 0.0],
            "rosy_45": [-0.1914, 0.47, 0.0],
            "rosy_46": [0.032, 0.47, 0.0],
        }
        for rid in CANONICAL_FLEET_ROBOTS["pinkys"]:
            if rid not in present_ids:
                active_pinkys.append({"id": rid, "pose_m": defaults[rid], "yaw_rad": -1.5708, "observed": False, "has_cargo": False})
        default_arms = {arm_id: [0.0, -1.0, 0.7, 0.3, 0.0, 0.0] for arm_id in CANONICAL_FLEET_ROBOTS["arms"]}
        if isinstance(arms, dict):
            default_arms.update({k: list(v) for k, v in arms.items()})
        payload: dict[str, Any] = {
            "schema": FACTORY_STATE_SCHEMA,
            "stream_mode": "live",
            "world_id": self.world_id,
            "adapter": self.backend,
            "simulator": self.backend,
            "run_id": self.run_id,
            "sim_time_s": round(float(sim_time_s), 3),
            "observed_at_ms": time.time_ns() // 1_000_000,
            "has_cargo_tray": True,
            "site_map_sha256": self.parity["site_map_sha256"],
            "fleet_robots": CANONICAL_FLEET_ROBOTS,
            "env": self.descriptor,
            "parity": self.parity,
            "training": training or None,
            "stage": stage,
            "phase": phase,
            "pinky": pinky,
            "pinkys": active_pinkys,
            "arms": default_arms,
            "arms_observed": {arm: bool((arms_observed or {}).get(arm)) for arm in CANONICAL_FLEET_ROBOTS["arms"]},
            "cargo": cargo or {"zone": "s3", "pose_m": list(pinky["pose_m"]), "yaw_rad": pinky.get("yaw_rad", 0.0), "observed": False},
            "cell_ab": cell_ab or {"active_arm": None, "active_step": None, "stacked": []},
        }
        return self.publisher.publish(payload)

    def close(self, *, cleanup: bool = False) -> None:
        if cleanup:
            self.publisher.cleanup()

    def __enter__(self) -> "TrainingWorldHook":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close(cleanup=False)
