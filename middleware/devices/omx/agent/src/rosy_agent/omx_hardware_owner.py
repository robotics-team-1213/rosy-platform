"""One native OMX hardware owner per instance, no-goal (D-785, D-246, D-336).

``build_hardware_owner`` assembles, in one process: one ``ArmCommandOwner`` (inside the injected
ROS runtime, ``allowed_owners=("rule_based",)`` on a steady clock), one SQLite journal holding the
Action store and the local stop latch, and the D-336 ``ActionApi``/``UnixActionServer`` serving
StopLocal/GetStopState/RearmLocal, GetOwnerState/RecoverOwner, GetAction and GetOwnerIdentity to
the configured Fleet peer UID.

No goal path exists here: the Action runner is disabled and has no phase runner factory, so
SubmitAction is refused before any journal row; there is no HTTP/Pilot surface. The identity
reports ``simulation: false`` and ``goals_enabled: false`` so Fleet never mistakes this owner for
the simulation cell. Opening motion needs a measured profile and stop evidence (G3) and a
separate decision; it is not a flag on this composition.

The local stop latch is the owner's software fence. It does not remove motor power and is not
an emergency stop.

ROS is injected (``runtime_factory``) so this composition stays rclpy-free and host-testable;
``deploy/robot/omx/run_hardware_owner.py`` supplies the real runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import Any

from core_common.protocol.schemas import StopRequestSource
from omx_adapter.action_api import ActionApi, LocalStopApi, UnixActionServer
from omx_adapter.action_runner import ActionRunner
from omx_adapter.action_store import ActionStore
from omx_adapter.command_owner import ArmCommandConfig
from omx_adapter.control_seat_admission import ControlSeatAdmission
from omx_adapter.journal_identity import journal_identity
from omx_adapter.local_stop import LocalStopController
from omx_adapter.owner_recovery_api import OwnerRecoveryApi

ALLOWED_OWNERS = ("rule_based",)
HARDWARE_PROFILE = "omx-hardware-no-goal"
_SIM_TOKEN = re.compile(r"(?:^|[-_.])(?:sim|gazebo|gz|isaac)(?:[-_.]|$)", re.IGNORECASE)
_LOG = logging.getLogger(__name__)


def _measured_revision(revision: str) -> str:
    if (not isinstance(revision, str) or not revision.strip() or revision != revision.strip()
            or "<" in revision or ">" in revision or _SIM_TOKEN.search(revision)):
        raise ValueError("hardware owner needs a measured calibration revision, not a simulation "
                         "or placeholder value")
    return revision


@dataclass(frozen=True)
class HardwareOwnerSettings:
    workcell_id: str
    instance_id: str
    journal_path: Path
    socket_root: Path
    fleet_peer_uid: int
    calibration_revision: str

    def __post_init__(self) -> None:
        for name in ("workcell_id", "instance_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", value):
                raise ValueError(f"{name} must be a plain identifier")
        if type(self.fleet_peer_uid) is not int or self.fleet_peer_uid <= 0:
            raise ValueError("Fleet peer UID must be a positive non-root integer")
        _measured_revision(self.calibration_revision)


@dataclass
class HardwareOwner:
    settings: HardwareOwnerSettings
    runtime: Any
    store: ActionStore
    stop: LocalStopController
    runner: ActionRunner
    action_api: ActionApi
    uds_server: UnixActionServer


def build_hardware_owner(settings: HardwareOwnerSettings, owner_config: ArmCommandConfig, *,
                         runtime_factory: Callable[[ArmCommandConfig], Any],
                         refuse_second_owner: Callable[[], None],
                         fleet_fence_current: Callable[[int, int], bool]) -> HardwareOwner:
    refuse_second_owner()
    if not owner_config.enabled:
        raise ValueError("hardware owner requires an explicitly enabled, measured owner policy")
    if (owner_config.workcell_id, owner_config.instance_id, owner_config.calibration_revision) != (
            settings.workcell_id, settings.instance_id, settings.calibration_revision):
        raise ValueError("owner config identity differs from the hardware owner settings")
    if tuple(owner_config.allowed_owners) != ALLOWED_OWNERS:
        raise ValueError("hardware owner admits only the rule_based owner")
    runtime = runtime_factory(owner_config)
    if getattr(runtime, "owner_clock", None) != "steady":
        raise RuntimeError("hardware owner requires the steady owner clock")

    store = ActionStore(settings.journal_path)
    admission = ControlSeatAdmission(runtime.owner, store)
    runtime.owner.bind_control_admission(admission)
    runtime.control_admission = admission
    stop = LocalStopController(store.path, workcell_id=settings.workcell_id,
                               instance_id=settings.instance_id)

    def current_fence(epoch: int, generation: int) -> bool:
        if not stop.is_open(authority_epoch=epoch, dispatch_generation=generation):
            return False
        try:
            return fleet_fence_current(epoch, generation) is True
        except Exception:
            _LOG.exception("Fleet fence readback is unavailable")
            return False

    fleet_uid = settings.fleet_peer_uid
    runner = ActionRunner(
        store, _NoGoalDriver(), workcell_id=settings.workcell_id, instance_id=settings.instance_id,
        principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={fleet_uid},
        current_fence=current_fence, capability_current=lambda _grant: False,
        submission_fence=stop, phase_runner_factories={}, control_admission=admission,
        enabled=False)
    stop_api = LocalStopApi(stop, source_by_peer_uid={fleet_uid: StopRequestSource.FLEET},
                            cancel_active=lambda uid: runner.cancel_unresolved(peer_uid=uid),
                            fleet_fence_current=fleet_fence_current)
    recovery_api = OwnerRecoveryApi(runtime.owner, stop, store, allowed_peer_uids={fleet_uid},
                                    current_fence=current_fence)
    action_api = ActionApi(runner, stop_api=stop_api, recovery_api=recovery_api, identity={
        "workcell_id": settings.workcell_id, "instance_id": settings.instance_id,
        "simulation": False, "profile": HARDWARE_PROFILE, "goals_enabled": False,
        "journal_id": journal_identity(store.path)})
    uds_server = UnixActionServer(
        action_api, Path(settings.socket_root) / settings.instance_id / "control.sock")
    return HardwareOwner(settings, runtime, store, stop, runner, action_api, uds_server)


class _NoGoalDriver:
    """The no-goal owner has no driver path; the disabled runner never reaches it."""

    def submit(self, grant):
        raise PermissionError("the hardware owner has no goal path")

    def cancel(self, action):
        return None


__all__ = ["ALLOWED_OWNERS", "HARDWARE_PROFILE", "HardwareOwner", "HardwareOwnerSettings",
           "build_hardware_owner"]
