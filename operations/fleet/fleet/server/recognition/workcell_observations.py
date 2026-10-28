"""Source-bound, latest-only workcell observations; no command or hardware access."""
from collections import deque
from copy import deepcopy
from hashlib import sha256
import hmac
import json
import math
import threading
import time

from core_common.protocol.workcell_observations import ArmObservation, WorkcellObservationManifest
from core_common.protocol.motor_health import age_motor_health


class WorkcellObservations:
    def __init__(self, manifest: WorkcellObservationManifest, tokens: dict[str, str], *,
                 wall=time.time, monotonic=time.monotonic):
        self._joints = {arm.source_id: frozenset(arm.joint_names)
                        for cell in manifest.workcells for arm in cell.arms}
        self._arm_ids = {arm.source_id: arm.arm_id for cell in manifest.workcells for arm in cell.arms}
        self._bindings = {
            arm.source_id: {'owner_id': arm.arm_id, 'sha256': sha256(json.dumps({
                key: getattr(arm, key) for key in ('source_id', 'arm_id', 'board_id', 'joint_topic', 'joint_names')
            }, sort_keys=True).encode()).hexdigest()}
            for cell in manifest.workcells for arm in cell.arms}
        if (set(tokens) != self._joints.keys()
                or any(type(token) is not str or not token for token in tokens.values())
                or len(set(tokens.values())) != len(tokens)):
            raise ValueError("each registered arm source requires a distinct nonempty token")
        for cell in manifest.workcells:
            for arm in cell.arms:
                if not hmac.compare_digest(sha256(tokens[arm.source_id].encode()).hexdigest(), arm.credential_sha256):
                    raise ValueError("arm credential does not match its registered fingerprint")
        self._credential_fingerprints = frozenset(source.credential_sha256 for cell in manifest.workcells
                                                  for source in [*cell.arms, *cell.cameras])
        self._tokens = dict(tokens)
        self._wall, self._monotonic = wall, monotonic
        self._lock = threading.Lock()
        self._samples = {}
        self._retired = {source: deque(maxlen=64) for source in self._joints}
        self._workcells = [{
            "workcell_id": cell.workcell_id, "label": cell.label,
            "arms": [{"source_id": arm.source_id, "arm_id": arm.arm_id, "label": arm.label,
                      "units": "encoder_rad", "binding_sha256": self._bindings[arm.source_id]['sha256']}
                     for arm in cell.arms],
            "cameras": [{"source_id": camera.source_id, "label": camera.label,
                         "role": camera.role, "arm_id": camera.arm_id} for camera in cell.cameras],
        } for cell in manifest.workcells]

    def credential_values(self) -> tuple[str, ...]:
        """Server-side startup isolation checks only; never include these in read responses."""
        return tuple(self._tokens.values())

    def arm_binding(self, source_id: str) -> dict:
        """Declared source configuration, excluding labels and credentials; no hardware attestation."""
        return dict(self._bindings[source_id])

    def camera_source_ids(self) -> tuple[str, ...]:
        return tuple(camera["source_id"] for cell in self._workcells for camera in cell["cameras"])

    def credential_fingerprints(self) -> frozenset[str]:
        return self._credential_fingerprints

    def uses_token(self, token: str) -> bool:
        return isinstance(token, str) and sha256(token.encode()).hexdigest() in self._credential_fingerprints

    def authorize(self, source_id: str, token: str) -> None:
        expected = self._tokens.get(source_id)
        valid = hmac.compare_digest(token.encode() if isinstance(token, str) else b"",
                                    expected.encode() if expected is not None else b"")
        if expected is None or not isinstance(token, str) or not valid:
            raise PermissionError("unknown source or invalid observation credential")

    def ingest(self, source_id: str, token: str, observation: ArmObservation) -> None:
        self.authorize(source_id, token)
        observation = ArmObservation.model_validate(observation.model_dump())
        if observation.positions is not None and observation.positions.keys() != self._joints[source_id]:
            raise ValueError("joint positions must match the registered arm exactly")
        health = observation.motor_health
        if health is not None:
            motors = health.motors
            owner = self._arm_ids[source_id]
            if (health.owner_id != owner or not motors or any(m.group != owner for m in motors)
                    or {m.joint for m in motors} != self._joints[source_id]
                    or len(motors) != len(self._joints[source_id]) or len({m.id for m in motors}) != len(motors)):
                raise ValueError('motor health must match the registered arm owner and joint coverage')
            omx = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']
            if self._joints[source_id] == set(omx) and any(m.id != 11 + omx.index(m.joint) for m in motors):
                raise ValueError('OMX motor health IDs must match registered joint identity')
        with self._lock:
            source_age = self._wall() - observation.captured_at
            received = self._monotonic()
            if not -0.25 <= source_age <= 2 or not math.isfinite(received):
                raise ValueError("observation source clock is expired or future")
            previous = self._samples.get(source_id)
            if previous:
                old, _ = previous
                if observation.captured_at <= old.captured_at:
                    raise ValueError("observation capture must advance across epochs")
                if observation.epoch == old.epoch:
                    if observation.sequence <= old.sequence:
                        raise ValueError("observation sequence must advance")
                elif observation.epoch in self._retired[source_id] or observation.sequence != 1:
                    raise ValueError("new epoch requires sequence one and must not be retired")
            elif observation.sequence != 1:
                raise ValueError("initial epoch requires sequence one")
            if previous and observation.epoch != previous[0].epoch:
                self._retired[source_id].append(previous[0].epoch)
            self._samples[source_id] = (observation, received)

    def snapshot(self) -> dict:
        with self._lock:
            wall, now = self._wall(), self._monotonic()
            workcells = deepcopy(self._workcells)
            for cell in workcells:
                for arm in cell["arms"]:
                    sample = self._samples.get(arm["source_id"])
                    if sample is None:
                        arm.update(fresh=False, epoch=None, sequence=0, captured_at=None,
                                   source_age_s=None, receipt_age_s=None, positions=None, motor_health=None)
                        continue
                    observation, received = sample
                    source_age, receipt_age = wall - observation.captured_at, now - received
                    health_elapsed = (max(0, source_age, receipt_age)
                        if math.isfinite(source_age) and math.isfinite(receipt_age)
                        and source_age >= -.25 and receipt_age >= 0 else -1)
                    fresh = observation.positions is not None and -0.25 <= source_age <= 2 and 0 <= receipt_age <= 2
                    arm.update(fresh=fresh, epoch=observation.epoch, sequence=observation.sequence,
                               captured_at=observation.captured_at, source_age_s=source_age,
                               receipt_age_s=receipt_age,
                               positions=dict(observation.positions) if fresh else None,
                               motor_health=(age_motor_health(observation.motor_health, health_elapsed)
                                   .model_dump() if observation.motor_health is not None else None))
            return {"read_only": True, "physical_acceptance": False, "workcells": workcells}
