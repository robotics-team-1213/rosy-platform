"""Keep a named-stop claim until CORE proves the exact Nav2 run has stopped."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlencode
from uuid import uuid4

import httpx

from core_common.protocol.evidence import STALE_POSE_S
from core_common.protocol.native.operation import NativeOperation
from fleet.server.channel.execution.outcomes.evidence import safe_proof
from rosy.world.state.projections.map_pose_samples import parse_utc


# Nothing from before this instant is required: used where CORE keeps no terminal timestamp.
_BEFORE_ALL = datetime.min.replace(tzinfo=timezone.utc)
STOPPED_NAVIGATION = frozenset({"IDLE", "ARRIVED", "CANCELED", "FAILED"})


def measured_stop_proof(state, robot_id, after, now, *, idle_only=False):
    """The closed-trip measured standstill predicate, shared with uncertain-motion recovery."""
    if not isinstance(state, dict):
        return None
    sample = (state.get("evidence") or {}).get("velocity") or {}
    stamp = parse_utc(sample.get("sampled_at"))
    vel = state.get("velocity") or {}
    # CORE snapshots omit goal; use mode, navigation, line_follow and fresh measured velocity.
    if (sample.get("evidence") != "fresh" or stamp is None or stamp <= after
            or not 0 <= now - stamp < STALE_POSE_S
            or state.get("robot_id") != robot_id or state.get("goal") is not None
            or (state.get("line_follow") or {}).get("mode") != "OFF"
            or state.get("navigation") not in STOPPED_NAVIGATION
            or state.get("mode") not in {"IDLE", "NAVIGATION"}
            or idle_only and (state["mode"] != "IDLE" or state["navigation"] != "IDLE")
            or any(type(vel.get(k)) not in (float, int) or not math.isfinite(vel[k]) for k in ("linear", "angular"))
            or abs(vel["linear"]) > 0.01 or abs(vel["angular"]) > 0.02):
        return None
    return {"sampled_at": sample["sampled_at"], "navigation": state["navigation"],
            "goal": None, "velocity": {"linear": 0.0, "angular": 0.0}}


def confirmed_estop(state):
    """The live hardware-estop custody-release check; an HTTP stop ACK alone is insufficient."""
    if not isinstance(state, dict):
        return False
    safety, line = state.get("safety"), state.get("line_follow")
    return (isinstance(safety, dict) and isinstance(line, dict)
            and safety.get("estop") is True and state.get("mode") == "EMERGENCY"
            and line.get("mode") == "OFF" and NamedStopMotion._zero_sample(state, ("EMERGENCY",)) is not None)


@dataclass
class NamedStopMotion:
    robot_id: str
    boot_id: str
    correlation_id: str
    run_id: str | None = None
    stopped_epoch: tuple | None = None
    terminal_at: datetime | None = None
    zero_at: datetime | None = None
    reservation_id: str = field(default_factory=lambda: uuid4().hex)

    repark_correlation_id: str | None = None
    repark_run_id: str | None = None
    precision_required: bool = False
    nav_succeeded: bool = False
    repark_completion: dict | None = None
    new_boot_sample: tuple | None = None  # (boot_id, sample time): standstill seen under that one new boot
    missing: str = ""  # what the last readback still lacked, shown to the operator

    def operation(self, payload):
        operation = NativeOperation.model_validate(payload).model_dump(mode="json")
        if (operation["kind"], operation["boot_id"], operation["correlation_id"]) != (
                "navigate", self.boot_id, self.correlation_id):
            raise ValueError("named stop operation identity changed")
        if self.run_id is not None and operation["run_id"] != self.run_id:
            raise ValueError("named stop run changed")
        return operation

    async def stopped(self, client, *, aligned=None):
        self.missing = "two fresh zero-velocity samples after the run stopped"
        if self.repark_correlation_id is not None:
            return await self._repark_stopped(client)
        path = "/api/v1/navigation/state"
        if self.run_id is None:
            # A lost acceptance reply does not lose the attempt identity.
            latest = await client._get(path)
            self.run_id = self.operation(latest.get("operation"))["run_id"]
        path += f"?run_id={self.run_id}"
        view = await client._get(path)
        operation = self.operation(view.get("operation"))
        self.nav_succeeded = operation["result"] == "SUCCEEDED"
        if not safe_proof(view, operation):
            self.missing = "terminal Nav2 receipt with a quiescence proof"
            self.stopped_epoch = self.terminal_at = self.zero_at = None
            return False
        proof = view["quiescence"]
        epoch = proof["owner_generation"], proof["transport_generation"]
        if self.stopped_epoch != epoch:
            self.stopped_epoch = epoch
            self.terminal_at = _timestamp(proof["observed_at"])
            self.zero_at = None

        state = await client.state()
        if not self._measured_zero(state, ("IDLE", "NAVIGATION", "EMERGENCY")):
            return False
        if aligned is not None and not _map_pose_after(state, self.zero_at):
            return False
        after = await client._get(path)
        if not safe_proof(after, self.operation(after.get("operation"))):
            return False
        proof = after["quiescence"]
        return ((proof["owner_generation"], proof["transport_generation"]) == epoch
                and (aligned is None or aligned(state) is True))

    async def _repark_stopped(self, client):
        path = "/api/v1/motion/repark/run?" + urlencode({"correlation_id": self.repark_correlation_id})
        view = await client._get(path)
        proof = self._repark_proof(view)
        if proof is None:
            operation = view.get("operation") or {}
            self.missing = ("idle zero write of the successful re-park"
                            if operation.get("result") == "SUCCEEDED" and not view.get("idle_zero_write")
                            else "terminal re-park receipt with an idle owner")
            self.stopped_epoch = self.terminal_at = self.zero_at = None
            return False
        if self.stopped_epoch != proof:
            self.stopped_epoch = proof
            self.terminal_at = proof[-1]
            self.zero_at = None
        state = await client.state()
        # An e-stop interrupted run has no idle zero write (CORE arms it only from IDLE); CORE holds EMERGENCY at zero.
        bare = proof[-1] is _BEFORE_ALL
        if not self._measured_zero(state, ("IDLE", "EMERGENCY") if bare else ("IDLE",)):
            return False
        after = await client._get(path)
        confirmed = self._repark_proof(after)
        if confirmed != proof:
            self.stopped_epoch = self.terminal_at = self.zero_at = None
            return False
        self.repark_completion = {
            "navigation": {"boot_id": self.boot_id, "run_id": self.run_id,
                           "correlation_id": self.correlation_id},
            "operation": after["operation"], "owner": after["owner"], "idle_zero_write": after.get("idle_zero_write"),
            "velocity_samples": [self.zero_at.isoformat(), state["evidence"]["velocity"]["sampled_at"]],
        }
        return True

    async def new_boot_stopped(self, client):
        """A run of a previous boot cannot still execute. Needs two increasing zero samples under ONE new boot_id."""
        boot = self._other_boot_idle(await client._get("/api/v1/navigation/state"))
        if boot is None:
            return False
        sample_at = self._zero_sample(await client.state(), ("IDLE", "EMERGENCY"))
        if sample_at is None:
            self.new_boot_sample = None
            return False
        first = self.new_boot_sample
        if first is None or first[0] != boot or sample_at - first[1] > timedelta(seconds=STALE_POSE_S):  # too far apart to pair
            self.new_boot_sample = (boot, sample_at)
            return False
        if sample_at <= self.new_boot_sample[1]:
            return False
        return self._other_boot_idle(await client._get("/api/v1/navigation/state")) == boot

    def _other_boot_idle(self, view):
        """The robot's current boot_id when it is not the claim's and nothing owns a run, else None."""
        owner = view.get("owner") or {}
        if (not owner.get("boot_id") or owner["boot_id"] == self.boot_id
                or "owner_run_id" not in owner or owner["owner_run_id"] is not None):
            self.new_boot_sample = None
            return None
        return owner["boot_id"]

    def _repark_proof(self, view):
        operation = NativeOperation.model_validate(view.get("operation")).model_dump(mode="json")
        if (view.get("lookup") != "FOUND" or operation["kind"] != "repark"
                or operation["boot_id"] != self.boot_id or operation["correlation_id"] != self.repark_correlation_id
                or (self.repark_run_id is not None and operation["run_id"] != self.repark_run_id)):
            return None
        self.repark_run_id = operation["run_id"]
        owner = view.get("owner") or {}
        zero = view.get("idle_zero_write") or {}
        stamp = _timestamp(zero.get("observed_at"))
        generation, mode_epoch = owner.get("owner_generation"), zero.get("mode_epoch")
        bare = not zero and operation["result"] not in (None, "SUCCEEDED")
        if bare:
            stamp, mode_epoch = _BEFORE_ALL, 0
        if (operation["phase"] != "TERMINAL" or owner.get("boot_id") != self.boot_id
                or "owner_run_id" not in owner or owner["owner_run_id"] is not None
                or (not bare and zero.get("run_id") != self.repark_run_id) or stamp is None
                or type(generation) is not int or generation < 0 or type(mode_epoch) is not int or mode_epoch < 0):
            return None
        return self.repark_run_id, generation, mode_epoch, operation["result"], stamp

    @staticmethod
    def _zero_sample(state, allowed_modes):
        """The sample time of a fresh measured standstill in an allowed mode, else None."""
        velocity = state.get("velocity") or {}
        evidence = (state.get("evidence") or {}).get("velocity") or {}
        if (evidence.get("evidence") != "fresh" or state.get("mode") not in allowed_modes
                or (state.get("line_follow") or {}).get("mode") != "OFF"
                or any(type(velocity.get(axis)) not in (int, float) or velocity[axis] != 0.0
                       for axis in ("linear", "angular"))):
            return None
        return _timestamp(evidence.get("sampled_at"))

    def _measured_zero(self, state, allowed_modes):
        sample_at = self._zero_sample(state, allowed_modes)
        if self.terminal_at is None or sample_at is None or sample_at <= self.terminal_at:
            self.zero_at = None
            return False
        # The robot's twist is measured over an encoder interval ending at the header stamp.
        if self.zero_at is None:
            self.zero_at = sample_at
            return False
        return sample_at > self.zero_at


async def current_repark_alignment(client, receipt, aligned):
    operation = receipt["operation"]
    if operation["result"] != "SUCCEEDED":
        return False
    first, last = (_timestamp(value) for value in receipt["velocity_samples"])
    zero = receipt["idle_zero_write"]
    observed = _timestamp(zero["observed_at"])
    if not all((first, last, observed)) or not observed < first < last:
        return False
    tracker = NamedStopMotion("", operation["boot_id"], "", terminal_at=observed, zero_at=last,
                              repark_correlation_id=operation["correlation_id"], repark_run_id=operation["run_id"])
    path = "/api/v1/motion/repark/run?" + urlencode({"correlation_id": tracker.repark_correlation_id})

    def current(view):
        return (tracker._repark_proof(view) is not None and view["operation"] == operation
                and view["owner"] == receipt["owner"] and view["idle_zero_write"] == zero)

    if not current(await client._get(path)):
        return False
    state = await client.state()
    if not tracker._measured_zero(state, ("IDLE",)):
        return False
    if not _map_pose_after(state, last):
        return False
    return current(await client._get(path)) and aligned(state) is True


def _map_pose_after(state, earliest):
    pose = (state.get("evidence") or {}).get("pose") or {}
    # CORE backdates a map pose's received_at to the source TF time.
    pose_at = _timestamp(pose.get("received_at"))
    return (state.get("pose_frame") == "map"
            and (state.get("localization") or {}).get("pose_frame") == "map"
            and pose.get("evidence") == "fresh" and pose_at is not None and pose_at > earliest)


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return None
    return parsed if parsed.utcoffset() is not None else None


def _is_unreachable(exc: Exception) -> bool:
    return isinstance(exc, (OSError, TimeoutError, httpx.TransportError)) or type(exc).__name__ == "HubError"


async def verify_release_proof(claim: NamedStopMotion, client, physical_isolation=None, *,
                               cancel_error: Exception | None = None, stop_responded: bool = False,
                               refuse=RuntimeError) -> str:
    """Fail-closed gate for operator named-stop custody release."""
    if physical_isolation is None:
        if cancel_error is not None:
            raise refuse("NAMED_STOP_CANCEL_FAILED",
                         f"could not confirm stop cancel before custody release: {cancel_error}")
        if client is None:
            raise refuse("NAMED_STOP_PROOF_REQUIRED",
                         "no live CORE client to prove standstill; provide physical_isolation if isolated")
        for _ in range(2):
            try:
                if await claim.stopped(client):
                    return "core_stop_proof"
            except Exception:
                break
            if claim.zero_at is None:
                break
        for _ in range(2):
            try:
                if await claim.new_boot_stopped(client):
                    return "core_new_boot_stop_proof"
            except Exception:
                break
            if claim.new_boot_sample is None:
                break
        raise refuse("NAMED_STOP_PROOF_REQUIRED",
                     claim.missing or "CORE has not proved the robot stopped; provide physical_isolation if isolated")

    method = physical_isolation.method
    if method in ("power_off", "removed_from_site"):
        if stop_responded:
            raise refuse("PHYSICAL_ISOLATION_CONTRADICTED",
                         f"{method} contradicted: CORE responded to stop cancel")
        if client is not None:
            for _ in range(2):
                try:
                    await client.state()
                except Exception as exc:
                    if not _is_unreachable(exc):
                        raise refuse("PHYSICAL_ISOLATION_CONTRADICTED",
                                     f"{method} contradicted: CORE responded ({exc!r})") from exc
                else:
                    raise refuse("PHYSICAL_ISOLATION_CONTRADICTED",
                                 f"{method} contradicted: CORE answered live state")
        return f"physical_isolation:{method}"

    if method == "hardware_estop_latched":
        if client is None:
            raise refuse("PHYSICAL_ISOLATION_CONTRADICTED",
                         "hardware_estop_latched requires live CORE client confirming estop")
        try:
            state = await client.state()
        except Exception as exc:
            raise refuse("PHYSICAL_ISOLATION_CONTRADICTED",
                         f"hardware_estop_latched requires live CORE state confirming estop ({exc!r})") from exc
        if not isinstance(state, dict):
            raise refuse("PHYSICAL_ISOLATION_CONTRADICTED", "hardware_estop_latched contradicted by live CORE state")
        if not confirmed_estop(state):
            raise refuse("PHYSICAL_ISOLATION_CONTRADICTED",
                         "hardware_estop_latched contradicted by live CORE state")
        return "physical_isolation:hardware_estop_latched"

    raise refuse("PHYSICAL_ISOLATION_CONTRADICTED", f"unsupported physical isolation method {method!r}")
