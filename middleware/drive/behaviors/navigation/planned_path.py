"""Reserve a planner result and consume it with the same Nav2 owner and goal."""

from copy import deepcopy
from dataclasses import dataclass
import math
from uuid import UUID, uuid4


@dataclass(frozen=True)
class PlannedPath:
    plan_id: UUID
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class PlannedPathScope:
    owner_id: str
    correlation_id: str
    binding: tuple


@dataclass(frozen=True)
class _PreparedPath:
    public: PlannedPath
    target: tuple
    scope: PlannedPathScope
    owner: dict
    executor: object
    transport: tuple
    expiry: float
    path: object


def _target(spec) -> tuple:
    return spec.frame, spec.x, spec.y, spec.yaw


def prepare_path(self, spec, *, scope: PlannedPathScope, timeout_s: float) -> PlannedPath:
    """Run planning off the ROS executor thread, with no motion mode change."""
    from .manager import NavigationError

    if spec.via or spec.frame != "map" or not all(math.isfinite(v) for v in _target(spec)[1:]):
        raise NavigationError("VALIDATION_ERROR", "an exact finite map goal is required")
    self.require_ready()
    executor = self._require_executor()
    compute = getattr(executor, "compute_navigation_path", None)
    transport = getattr(executor, "native_transport_snapshot", None)
    if compute is None or transport is None or getattr(executor, "send_native_path", None) is None:
        raise NavigationError("CAPABILITY_NOT_SUPPORTED", "Nav2 path planning is unavailable")
    if not self._plan_worker.acquire(blocking=False):
        raise NavigationError("NAVIGATION_ACTIVE", "a navigation plan is already computing")
    try:
        with self._lock:
            before = transport()
            if before[1:] != (False, False) or self._safety.estop:
                raise NavigationError("NAVIGATION_ACTIVE", "Nav2 transport has no idle proof")
            token = self.reserve_goal(for_handoff=True)
            self._prepared_path = None
        try:
            target = _target(spec)
            path = deepcopy(compute(spec, timeout_s=timeout_s))
            points = tuple((p.pose.position.x, p.pose.position.y) for p in path.poses)
            with self._lock:
                if (self._admitting != token or self.executor is not executor or transport() != before
                        or self._safety.estop or _target(spec) != target):
                    raise NavigationError("OWNER_GENERATION_CHANGED", "navigation changed while planning")
                self.release_goal_reservation(token)
                public = PlannedPath(uuid4(), points)
                self._prepared_path = _PreparedPath(public, target, scope, self.native.owner(), executor,
                                                   before, self.lease_clock() + 5.0, path)
                return public
        finally:
            self.release_goal_reservation(token)
    finally:
        self._plan_worker.release()


def reserve_planned_goal(self, plan_id: UUID, spec, *, scope: PlannedPathScope, verify=None,
                         expected_boot_id=None, expected_owner_generation=None) -> UUID:
    """Consume an exact plan into the regular motion reservation."""
    from .manager import NavigationError

    with self._lock:
        try:
            self.native.expect(expected_boot_id, expected_owner_generation)
        except ValueError as exc:
            raise NavigationError(str(exc), str(exc)) from exc
        plan = self._prepared_path
        if (plan is None or plan.public.plan_id != plan_id or plan.target != _target(spec) or spec.via
                or plan.scope != scope or plan.owner != self.native.owner() or not _backend_current(self, plan)
                or self.lease_clock() >= plan.expiry):
            raise NavigationError("NAVIGATION_PLAN_CHANGED", "the prepared navigation path is no longer valid")
        _require_controller(plan)
        if verify is not None:
            verify(plan.public)
        token = self.reserve_goal(for_handoff=True, expected_boot_id=expected_boot_id,
                                  expected_owner_generation=expected_owner_generation)
        self._prepared_path = None
        self._reserved_path = (token, plan)
        return token


def path_for_reservation(self, token, spec, owner_id, correlation_id):
    from .manager import NavigationError

    if self._reserved_path is None or self._reserved_path[0] != token:
        return None
    plan = self._reserved_path[1]
    if (plan.target != _target(spec) or spec.via or not _backend_current(self, plan)
            or (plan.scope.owner_id, plan.scope.correlation_id) != (owner_id, correlation_id)
            or self.lease_clock() >= plan.expiry):
        raise NavigationError("NAVIGATION_PLAN_CHANGED", "the reserved navigation path is no longer valid")
    _require_controller(plan)
    return plan.path


def _backend_current(self, plan: _PreparedPath) -> bool:
    return self.executor is plan.executor and plan.executor.native_transport_snapshot() == plan.transport


def _require_controller(plan):
    from .manager import NavigationError

    ready = getattr(plan.executor, "path_controller_ready", None)
    if ready is None or not ready():
        raise NavigationError("NAVIGATION_PLANNER_UNAVAILABLE", "Nav2 path controller unavailable")
