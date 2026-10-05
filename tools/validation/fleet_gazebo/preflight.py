"""D-426 Task 1 — run isolation, reservations, and readiness (ROS-free).

Every check here is a pure function over paths and manifests so the failure
modes run on any host (Windows CI included). The runner (``run.py``) composes
them; the Gazebo launch only consumes the files this module writes — it never
invents reservations of its own. Rules this module enforces (plan §공통 실행 규칙):

- a run root is single-use: an existing manifest (live or stale) refuses reuse
- nothing inside a run root may symlink outside it
- world/map/profile inputs must exist and are pinned by sha256
- per-robot CORE overlays must carry the same hub URL and pairing token as the
  fleet robots manifest
- READY requires every transport probe explicitly True; unknown is not ready
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path

import yaml

MANIFEST_NAME = "run.json"
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{5,63}$")
#: run_fleet_sim.sh randomizes domains 20..119 and real robots take 40+N (D-4);
#: validation runs take a disjoint deterministic slice.
DOMAIN_RANGE = (120, 199)
API_PORT_RANGE = (31000, 31999)
CONSOLE_PORT_RANGE = (32000, 32099)

#: Transport facts preflight must see before READY (plan Task 1 item 5).
REQUIRED_PROBES = ("clock", "scan", "odom", "tf", "nav2", "core_http", "ws_welcome")


class PreflightError(RuntimeError):
    """A conformance run must not start (or must stay NOT_READY)."""


def _stable_int(run_id: str, salt: str, lo: int, hi: int) -> int:
    digest = hashlib.sha256(f"{salt}:{run_id}".encode("utf-8")).hexdigest()
    return lo + int(digest[:8], 16) % (hi - lo + 1)


@dataclass(frozen=True)
class Reservations:
    """Ports, ROS domain, namespaces and Gazebo partition bound to one run_id."""

    run_id: str
    robots: int
    started_at: float
    namespaces: tuple[str, ...]
    api_ports: tuple[int, ...]
    console_port: int
    ros_domain_id: int
    gz_partition: str
    hub_url: str

    @classmethod
    def derive(cls, run_id: str, robots: int, *, started_at: float) -> "Reservations":
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise PreflightError(
                f"run_id '{run_id}' must match {RUN_ID_PATTERN.pattern}")
        if not 1 <= int(robots) <= 8:
            raise PreflightError("robots must be in 1..8 for a validation run")
        console_port = _stable_int(run_id, "console", *CONSOLE_PORT_RANGE)
        namespaces = tuple(f"rosy_{i:02d}" for i in range(1, int(robots) + 1))
        # api ports sit deterministically inside the slice; per-robot offsets are
        # checked for overlap by port_conflicts (two runs may still collide by hash).
        api_base = _stable_int(run_id, "api", API_PORT_RANGE[0],
                               API_PORT_RANGE[1] - int(robots))
        return cls(
            run_id=run_id,
            robots=int(robots),
            started_at=float(started_at),
            namespaces=namespaces,
            api_ports=tuple(api_base + i for i in range(int(robots))),
            console_port=console_port,
            ros_domain_id=_stable_int(run_id, "domain", *DOMAIN_RANGE),
            gz_partition=f"d426-{run_id}",
            hub_url=f"http://127.0.0.1:{console_port}",
        )

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "robots": self.robots,
            "namespaces": list(self.namespaces),
            "api_ports": list(self.api_ports),
            "console_port": self.console_port,
            "ros_domain_id": self.ros_domain_id,
            "gz_partition": self.gz_partition,
            "hub_url": self.hub_url,
        }


def port_conflicts(a: Reservations, b: Reservations) -> bool:
    """True when two runs would share any port or ROS domain."""
    if a.ros_domain_id == b.ros_domain_id:
        return True
    if a.console_port == b.console_port:
        return True
    return bool(set(a.api_ports) & set(b.api_ports))


def check_reservations(output_root: Path, reservations: Reservations) -> None:
    """Refuse recorded overlaps and occupied listeners before creating a run.

    This is a bounded planning snapshot, not a lifetime port reservation. Stale
    manifests remain reserved until the operator chooses a different output root.
    """
    manifests = list(itertools.islice(output_root.glob(f"*/{MANIFEST_NAME}"), 257))
    if len(manifests) > 256:
        raise PreflightError("reservation catalogue exceeds 256 manifests")
    for path in manifests:
        try:
            if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 65536:
                raise ValueError("untrusted manifest")
            data = json.loads(path.read_text(encoding="utf-8"))["reservations"]
            if not isinstance(data, dict) or type(data.get("robots")) is not int:
                raise ValueError("invalid robot count")
            old = Reservations.derive(data["run_id"], data["robots"], started_at=0.0)
            if data != old.as_dict():
                raise ValueError("reservations differ from the deterministic runner profile")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PreflightError(f"invalid reservation manifest: {path}") from exc
        if port_conflicts(reservations, old):
            raise PreflightError(f"reservation conflict with {path.parent.name}")
    for port in (*reservations.api_ports, reservations.console_port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise PreflightError(f"reserved port {port} is unavailable") from exc


def validate_run_root(root: Path) -> None:
    """A run root must be a fresh directory, never a symlink, never a reuse."""
    if root.is_symlink():
        raise PreflightError(f"run root must not be a symlink: {root}")
    if (root / MANIFEST_NAME).exists():
        raise PreflightError(
            f"run root already holds a manifest; start a new run_id instead of "
            f"reusing {root} (live or stale manifests are both refused)")
    if root.exists() and not root.is_dir():
        raise PreflightError(f"run root is not a directory: {root}")


def check_no_symlink_escape(root: Path) -> None:
    """No artifact inside the run root may point outside it."""
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink():
            target = path.resolve()
            if not str(target).startswith(str(resolved_root)):
                raise PreflightError(
                    f"symlink escape inside run root: {path} -> {target}")


def require_file_hashes(files: dict[str, Path]) -> dict[str, str]:
    """sha256 for every named input; a missing input refuses the run."""
    hashes: dict[str, str] = {}
    for name, path in files.items():
        if not path.is_file():
            raise PreflightError(f"{name} input is missing: {path}")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def write_manifest(root: Path, reservations: Reservations, *, versions: dict,
                   hashes: dict, argv: list[str]) -> Path:
    """Create the run root and bind it to run_id·started_at·versions·hashes."""
    validate_run_root(root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "run_id": reservations.run_id,
        "started_at": reservations.started_at,
        "pid": os.getpid(),
        "reservations": reservations.as_dict(),
        "versions": dict(versions),
        "hashes": dict(hashes),
        "argv": list(argv),
    }
    path = root / MANIFEST_NAME
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(manifest, indent=2, sort_keys=True))
    except FileExistsError as exc:
        raise PreflightError("run manifest was claimed concurrently; use a new run_id") from exc
    return path


def check_overlays(root: Path, namespaces, hub_url: str, fleet_manifest: dict) -> None:
    """Every robot's overlay must match the fleet manifest's pairing facts."""
    by_robot = {row["robot_id"]: row for row in fleet_manifest.get("robots", [])}
    for ns in namespaces:
        overlay_path = root / f"core_{ns}.yaml"
        if not overlay_path.is_file():
            raise PreflightError(f"missing CORE overlay for {ns}: {overlay_path}")
        overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
        fleet = overlay.get("fleet") or {}
        if fleet.get("hub_url") != hub_url:
            raise PreflightError(f"{ns}: overlay hub_url does not match the run hub")
        row = by_robot.get(ns)
        if row is None:
            raise PreflightError(f"{ns}: robot missing from the fleet manifest")
        if fleet.get("pairing_token") != row.get("fleet_pairing_token"):
            raise PreflightError(
                f"{ns}: overlay pairing_token does not match the manifest")


def readiness(probes: dict) -> tuple[bool, list[str]]:
    """READY only when every required transport probe is explicitly True."""
    unknown = []
    for name in REQUIRED_PROBES:
        if probes.get(name) is not True:
            unknown.append(f"{name}: {probes.get(name, 'missing')!r} is not confirmed")
    return (not unknown), unknown
