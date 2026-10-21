"""Source-bound, latest-only workcell observations; no command or hardware access."""
from collections import deque
from copy import deepcopy
from hashlib import sha256
import hmac
import math
import threading
import time

from core_common.protocol.workcell_observations import ArmObservation, WorkcellObservationManifest


class WorkcellObservations:
    def __init__(self, manifest: WorkcellObservationManifest, tokens: dict[str, str], *,
                 wall=time.time, monotonic=time.monotonic):
        self._joints = {arm.source_id: frozenset(arm.joint_names)
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
                      "units": "encoder_rad"} for arm in cell.arms],
            "cameras": [{"source_id": camera.source_id, "label": camera.label,
                         "role": camera.role, "arm_id": camera.arm_id} for camera in cell.cameras],
        } for cell in manifest.workcells]

    def credential_values(self) -> tuple[str, ...]:
        """Server-side startup isolation checks only; never include these in read responses."""
        return tuple(self._tokens.values())

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
        if observation.positions.keys() != self._joints[source_id]:
            raise ValueError("joint positions must match the registered arm exactly")
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
                                   source_age_s=None, receipt_age_s=None, positions=None)
                        continue
                    observation, received = sample
                    source_age, receipt_age = wall - observation.captured_at, now - received
                    fresh = -0.25 <= source_age <= 2 and 0 <= receipt_age <= 2
                    arm.update(fresh=fresh, epoch=observation.epoch, sequence=observation.sequence,
                               captured_at=observation.captured_at, source_age_s=source_age,
                               receipt_age_s=receipt_age,
                               positions=dict(observation.positions) if fresh else None)
            return {"read_only": True, "physical_acceptance": False, "workcells": workcells}
