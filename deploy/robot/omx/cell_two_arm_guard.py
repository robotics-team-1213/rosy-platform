"""Two-arm task pair validation and pre-chunk swept-capsule / mid-zone guard (D-1073).

Every candidate policy chunk must clear:
1. Finite (n, 6) shape and table floor clearance (`min_z_m`),
2. Peer swept-capsule separation (`margin_m`) via `omx_adapter.swept_volume` +
   `omx_adapter.coordination`,
3. Exclusive `mid` zone lock whenever the task or trajectory enters `mid_y_band`.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import numbers
from pathlib import Path
import sys
import threading
import time
from typing import Any, Mapping, Sequence

import cell_coordinate
import cell_site_target
import grasp_planner

_ADAPTER_DIR = Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter"
if str(_ADAPTER_DIR) not in sys.path:
    sys.path.insert(0, str(_ADAPTER_DIR))
from omx_adapter import coordination, swept_volume  # noqa: E402

ARMS = ("a", "b")
ARM_NAMES = {"a": "arm_a", "b": "arm_b"}
CANONICAL_TASK_IDS = (
    "T1_CONCURRENT_ZONE_SPLIT",
    "T2_CONCURRENT_OUTBOUND_STAGING",
    "T3_SHARED_MID_ALTERNATING",
)
_MID_AREAS = frozenset({"belt", "yard"})
_BELT_ALIASES = frozenset({"belt", "not_places:belt"})


def normalize_site_name(raw_site: Any) -> str:
    if not isinstance(raw_site, str) or not raw_site.strip():
        raise ValueError(f"canonical site name must be a non-empty string, got {raw_site!r}")
    s = raw_site.strip()
    return "belt" if s in _BELT_ALIASES else s


def config_site_key(cfg: Mapping[str, Any], raw_site: Any, tier: Any = None) -> str | None:
    """Resolve raw or canonical site ID (e.g. 'not_places:belt', 'yard:*') to a dict key in cfg['sites']."""
    sites = cfg.get("sites")
    if not isinstance(sites, Mapping) or not sites or not isinstance(raw_site, str) or not raw_site.strip():
        return None
    raw = raw_site.strip()
    norm = normalize_site_name(raw)
    resolved = cell_site_target.resolve_cell_ab_site(norm, tier, allow_belt_temp=True, allow_pallet_src=False)
    candidates = [norm, raw]
    if isinstance(resolved, Mapping):
        for field in ("site_id", "slot_id", "sim_site", "base_site", "wire_ref", "area"):
            val = resolved.get(field)
            if isinstance(val, str) and val and val not in candidates:
                candidates.append(val)
    for key in candidates:
        if isinstance(sites.get(key), Mapping):
            return key
    return None


_FORBIDDEN_DESTS = frozenset({"belt", "temp_plate_a", "temp_plate_b"})


def _resolve_arm_endpoint(arm_name: str, raw_site: Any, tier: Any = None) -> dict[str, Any]:
    site = normalize_site_name(raw_site)
    resolved = cell_site_target.resolve_cell_ab_site(site, tier, allow_belt_temp=True, allow_pallet_src=False)
    if resolved is None:
        raise ValueError(f"{arm_name}: unknown canonical site {raw_site!r}")
    if resolved.get("is_legacy_pallet") and resolved.get("area") == "pallet":
        raise ValueError(f"{arm_name}: legacy pallet site {raw_site!r} is not part of canonical 37-site grid")
    return resolved


def validate_two_arm_task_pair(task_a: Mapping[str, Any], task_b: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an (arm_a, arm_b) canonical 37-site task pair and classify D-1073 task ID."""
    parsed: dict[str, dict[str, Any]] = {}
    for short, raw in (("a", task_a), ("b", task_b)):
        if not isinstance(raw, Mapping):
            raise ValueError(f"task_{short} must be a mapping")
        arm_name = ARM_NAMES[short]
        src_norm = normalize_site_name(raw.get("src"))
        dst_norm = normalize_site_name(raw.get("dst"))
        if dst_norm in _FORBIDDEN_DESTS:
            raise ValueError(f"{arm_name}: destination {dst_norm!r} cannot be a placement target")
        tier = raw.get("tier")
        src_rec = _resolve_arm_endpoint(arm_name, src_norm, tier)
        dst_rec = _resolve_arm_endpoint(arm_name, dst_norm, tier)
        refusal = cell_site_target.arm_refusal(src_norm, dst_norm, arm_name)
        if refusal is not None:
            raise ValueError(f"{arm_name}: site pair {src_norm}->{dst_norm} refused ({refusal})")
        if src_norm == dst_norm and (src_rec.get("site_id") is not None or src_norm == "belt"):
            raise ValueError(f"{arm_name}: identical source and destination {src_norm!r}")
        if src_rec.get("site_id") is not None and src_rec.get("site_id") == dst_rec.get("site_id"):
            raise ValueError(f"{arm_name}: identical source and destination site_id {src_rec['site_id']!r}")
        parsed[short] = {
            "src": src_norm,
            "dst": dst_norm,
            "src_rec": src_rec,
            "dst_rec": dst_rec,
            "need_mid": bool(raw.get("need_mid", False)),
        }

    # Prevent overlapping concrete destination or shared non-belt single-stack slots.
    a_recs = (parsed["a"]["src_rec"], parsed["a"]["dst_rec"])
    b_recs = (parsed["b"]["src_rec"], parsed["b"]["dst_rec"])
    for ra in a_recs:
        for rb in b_recs:
            if ra.get("slot_id") and ra.get("slot_id") == rb.get("slot_id"):
                raise ValueError(f"overlapping single-stack slot target {ra['slot_id']!r}")
            if ra.get("site_id") and ra.get("site_id") == rb.get("site_id"):
                raise ValueError(f"overlapping canonical site {ra['site_id']!r}")

    a_areas = {r["area"] for r in a_recs}
    b_areas = {r["area"] for r in b_recs}
    a_mid = bool(a_areas & _MID_AREAS) or parsed["a"]["need_mid"]
    b_mid = bool(b_areas & _MID_AREAS) or parsed["b"]["need_mid"]
    a_outbound = "stand" in a_areas
    b_staging = (b_areas <= {"yard", "temp_b", "temp_plate_b"}) and not ("belt" in b_areas and "belt" in a_areas)

    if a_outbound and b_staging and not ("belt" in a_areas and "belt" in b_areas):
        task_id = "T2_CONCURRENT_OUTBOUND_STAGING"
        need_mid = {"a": a_mid, "b": b_mid}
    elif a_mid and b_mid:
        task_id = "T3_SHARED_MID_ALTERNATING"
        need_mid = {"a": True, "b": True}
    else:
        task_id = "T1_CONCURRENT_ZONE_SPLIT"
        need_mid = {"a": a_mid, "b": b_mid}

    return {
        "task_id": task_id,
        "arm_a": {"src": parsed["a"]["src"], "dst": parsed["a"]["dst"]},
        "arm_b": {"src": parsed["b"]["src"], "dst": parsed["b"]["dst"]},
        "need_mid": need_mid,
    }


def _num(v: Any, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, numbers.Real) or not math.isfinite(float(v)):
        raise ValueError(f"{name} must be finite, got {v!r}")
    return float(v)


def _finite_pose6(pose: Sequence[float]) -> tuple[float, ...]:
    if not isinstance(pose, Sequence) or isinstance(pose, (str, bytes)) or len(pose) != 6:
        raise ValueError(f"pose must have length 6, got {pose!r}")
    out: list[float] = []
    for v in pose:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            raise ValueError("pose contains non-finite values")
        out.append(float(v))
    return tuple(out)


def _body_rad(pose_units: Sequence[float]) -> list[float]:
    return [float(grasp_planner.norm_to_rad(v)) for v in pose_units[:5]]


def _caps_min_z(raw_poses: Sequence[Sequence[tuple[Any, Any, float]]]) -> float:
    lows: list[float] = []
    for frame in raw_poses:
        for i, (p0, p1, r) in enumerate(frame):
            # Link 0 originates at the fixed table base plate; check only its distal end, and check both ends for moving links.
            lows.append((float(p1[2]) if i == 0 else min(float(p0[2]), float(p1[2]))) - float(r))
    return min(lows) if lows else 0.0


def _caps_touch_mid(
    raw_poses: Sequence[Sequence[tuple[Any, Any, float]]],
    rigids: Mapping[str, tuple[float, float, float]],
    band_m: float,
) -> bool:
    if not math.isfinite(float(band_m)):
        return True
    if band_m <= 0.0:
        return False
    ax, ay = float(rigids["a"][1]), float(rigids["a"][2])
    bx, by = float(rigids["b"][1]), float(rigids["b"][2])
    dx, dy = bx - ax, by - ay
    dist = math.hypot(dx, dy)
    if not math.isfinite(dist) or dist < 1e-6:
        return True
    mx, my = (ax + bx) * 0.5, (ay + by) * 0.5
    ux, uy = dx / dist, dy / dist
    for frame in raw_poses:
        for p0, p1, r in frame:
            rad = float(r)
            s0 = (float(p0[0]) - mx) * ux + (float(p0[1]) - my) * uy
            s1 = (float(p1[0]) - mx) * ux + (float(p1[1]) - my) * uy
            if not (math.isfinite(rad) and math.isfinite(s0) and math.isfinite(s1)):
                return True
            reach = float(band_m) + max(0.0, rad)
            if min(s0, s1) <= reach and max(s0, s1) >= -reach:
                return True
    return False


@dataclass
class _ArmGuardState:
    pose: tuple[float, ...] | None = None
    holding: bool = False
    executing: bool = False
    waiting: bool = False
    active_poses: list[Any] | None = None
    holding_mid: bool = False


class TwoArmChunkGuard:
    """Thread-safe pre-chunk swept-capsule, table floor, and mid-zone guard."""

    def __init__(
        self,
        kin_by_arm: Mapping[str, Any],
        rigids: Mapping[str, Any],
        tips: Mapping[str, float],
        *,
        margin_m: float = 0.02,
        min_z_m: float = -0.02,
        thin_step_m: float = 0.005,
        mid_y_band: float = 0.05,
        wait_timeout_s: float = 1.5,
        item: tuple[float, float] | None = cell_coordinate.ITEM,
    ) -> None:
        if set(kin_by_arm) != set(ARMS) or set(rigids) != set(ARMS) or set(tips) != set(ARMS):
            raise ValueError("kin_by_arm, rigids, and tips must define keys 'a' and 'b'")
        for arm in ARMS:
            rg = rigids[arm]
            if isinstance(rg, (str, bytes, Mapping)) or not hasattr(rg, "__len__") or len(rg) != 3:
                raise ValueError(f"rigids[{arm!r}] must have length 3")
            [_num(x, f"rigids[{arm!r}]") for x in rg]
        self._kin = dict(kin_by_arm)
        self._rigids = {k: tuple(float(x) for x in rigids[k]) for k in ARMS}
        self._tips = {k: _num(v, f"tips[{k!r}]") for k, v in tips.items()}
        self._margin_m = _num(margin_m, "margin_m")
        self._min_z_m = _num(min_z_m, "min_z_m")
        self._thin_step_m = _num(thin_step_m, "thin_step_m")
        self._mid_y_band = _num(mid_y_band, "mid_y_band")
        self._wait_timeout_s = _num(wait_timeout_s, "wait_timeout_s")
        if self._margin_m < 0.0 or self._mid_y_band < 0.0 or self._thin_step_m <= 0.0 or self._wait_timeout_s <= 0.0:
            raise ValueError("guard margin/mid_y_band must be >= 0 and thin_step_m/wait_timeout_s > 0")
        self._item = item
        self._cond = threading.Condition()
        self._arms = {arm: _ArmGuardState() for arm in ARMS}
        self._mid_owner: str | None = None
        self._stopped_reason: str | None = None

    @property
    def stopped_reason(self) -> str | None:
        with self._cond:
            return self._stopped_reason

    def _frame_capsules(self, arm: str, pose_units: Sequence[float], holding: bool) -> list[tuple[Any, Any, float]]:
        caps = swept_volume.capsules(
            self._kin[arm],
            _body_rad(pose_units),
            fingertip_m=self._tips[arm],
            item=self._item if holding else None,
        )
        return coordination.moved(caps, self._rigids[arm])

    def update_pose(self, arm: str, joints_units: Sequence[float], *, holding: bool = False) -> None:
        if arm not in ARMS:
            raise ValueError(f"invalid arm {arm!r}")
        pose = _finite_pose6(joints_units)
        with self._cond:
            self._arms[arm].pose = pose
            self._arms[arm].holding = bool(holding)
            self._cond.notify_all()

    def latch_stop(self, reason: str) -> None:
        with self._cond:
            if self._stopped_reason is None:
                self._stopped_reason = str(reason)
            self._cond.notify_all()

    def admit_chunk(
        self,
        arm: str,
        chunk_units: Sequence[Sequence[float]],
        *,
        holding: bool = False,
        need_mid: bool = False,
        wait_timeout_s: float | None = None,
    ) -> dict[str, Any]:
        if arm not in ARMS:
            raise ValueError(f"invalid arm {arm!r}")
        if not chunk_units:
            return {"admitted": False, "reason": "empty_chunk"}
        chunk = [_finite_pose6(row) for row in chunk_units]
        raw_poses = [self._frame_capsules(arm, row, holding) for row in chunk]

        floor_z = _caps_min_z(raw_poses)
        if not math.isfinite(floor_z) or floor_z < self._min_z_m:
            return {"admitted": False, "reason": "floor_violation", "min_z_m": round(floor_z, 5) if math.isfinite(floor_z) else None}

        my_poses = coordination.thinned(raw_poses, self._thin_step_m) or [raw_poses[0]]
        uses_mid = bool(need_mid) or _caps_touch_mid(raw_poses, self._rigids, self._mid_y_band)
        timeout = _num(self._wait_timeout_s if wait_timeout_s is None else wait_timeout_s, "wait_timeout_s")
        if timeout <= 0.0:
            raise ValueError("wait_timeout_s must be positive")
        t_start = time.monotonic()
        deadline = t_start + timeout
        peer = "b" if arm == "a" else "a"

        with self._cond:
            while True:
                if self._stopped_reason is not None:
                    return {"admitted": False, "reason": f"coupled_stop:{self._stopped_reason}"}
                pst = self._arms[peer]
                mst = self._arms[arm]
                if pst.pose is None and not pst.executing:
                    return {"admitted": False, "reason": "missing_peer_pose"}

                peer_poses = (
                    pst.active_poses
                    if (pst.executing and pst.active_poses is not None)
                    else [self._frame_capsules(peer, pst.pose, pst.holding)]
                )
                mid_blocked = uses_mid and self._mid_owner not in (None, arm)
                clr = float(coordination.clearance(my_poses, peer_poses))
                clr_ok = math.isfinite(clr)
                colliding = (not clr_ok) or clr < self._margin_m

                if not mid_blocked and not colliding:
                    mst.executing = True
                    mst.waiting = False
                    mst.active_poses = my_poses
                    mst.pose = chunk[0]
                    mst.holding = bool(holding)
                    if uses_mid:
                        self._mid_owner = arm
                        mst.holding_mid = True
                    self._cond.notify_all()
                    return {
                        "admitted": True,
                        "clearance_m": round(clr, 5),
                        "used_mid": uses_mid,
                        "waited_s": round(time.monotonic() - t_start, 4),
                    }

                can_unblock = pst.executing or (mid_blocked and self._mid_owner == peer)
                if not can_unblock:
                    return {
                        "admitted": False,
                        "reason": "stationary_collision",
                        "clearance_m": round(clr, 5) if clr_ok else None,
                    }
                if pst.waiting:
                    return {
                        "admitted": False,
                        "reason": "deadlock",
                        "clearance_m": round(clr, 5) if clr_ok else None,
                    }
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return {
                        "admitted": False,
                        "reason": "wait_timeout",
                        "clearance_m": round(clr, 5) if clr_ok else None,
                    }
                mst.waiting = True
                self._cond.wait(timeout=remaining)
                mst.waiting = False

    def release_chunk(
        self,
        arm: str,
        *,
        final_pose: Sequence[float] | None = None,
        holding: bool = False,
    ) -> None:
        if arm not in ARMS:
            raise ValueError(f"invalid arm {arm!r}")
        pose = _finite_pose6(final_pose) if final_pose is not None else None
        with self._cond:
            st = self._arms[arm]
            st.executing = False
            st.waiting = False
            st.active_poses = None
            st.holding = bool(holding)
            if pose is not None:
                st.pose = pose
            if self._mid_owner == arm:
                self._mid_owner = None
            st.holding_mid = False
            self._cond.notify_all()
