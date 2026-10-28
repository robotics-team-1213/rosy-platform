"""G2-only readback evidence. No commands, acceptance queries or guard decisions."""
from collections import deque
import math
from pathlib import Path
import re
import threading
import time

LIMIT = 2**63 - 1


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > LIMIT:
        return None
    return value


def _integer(value):
    return value if type(value) is int and 0 <= value <= LIMIT else None


def _identifier(value):
    return value if type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) else None


def _digest(value):
    return value if type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) else None


def _write_record(path, record):
    from g2_ports import write_json
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)


class GripperReadbackTrace:
    def __init__(self, directory, *, max_records=128):
        if type(max_records) is not int or not 1 <= max_records <= 128:
            raise ValueError("gripper trace limit must be between 1 and 128")
        self.directory = Path(directory)
        self.max_records = max_records
        self._geometry = {}
        self._issued = self._written = self._failures = 0
        self._failure_code = None
        self._pending = deque(maxlen=max_records)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closing = threading.Event()
        self._writer = threading.Thread(target=self._write_pending, name="g2-gripper-evidence", daemon=True)
        self._writer.start()

    def _fail(self, code):
        # Never print/flush or call arbitrary exception repr on the control path.
        self._failure_code = code
        self._failures = min(LIMIT, self._failures + 1)

    def bind_recipe(self, accepted_receipt):
        """Called once before control from accept_recipe's actual returned items."""
        try:
            recipe = _digest(accepted_receipt["recipe_sha256"])
            items = accepted_receipt["items"]
            if recipe is None or type(items) is not dict or not 1 <= len(items) <= 16 or self._geometry:
                raise ValueError("unsupported diagnostic geometry binding")
            geometry = {}
            for key, item in items.items():
                identifier = _identifier(key)
                width = _number(item.get("grasp_width_m")) if type(item) is dict else None
                if identifier is None or width is None or not 0 < width <= 1:
                    raise ValueError("unsupported diagnostic width")
                geometry[(recipe, identifier)] = width
            self._geometry = geometry
        except Exception:
            self._fail("GEOMETRY_BINDING_FAILED")

    def read(self, owner, grant, canonical, *, context="workflow"):
        """Sample once and preserve the canonical returned object / raised exception."""
        state = owner.runtime.latest_joint_state
        try:
            began = time.monotonic()
        except Exception:
            began = None
            self._fail("STEADY_SAMPLE_FAILED")
        try:
            observation = canonical(owner, state, grant)
        except BaseException as error:
            try:
                name = type(error).__name__
                self._observe(owner, state, grant, None, context, began,
                              name if name in {"ValueError", "TypeError", "RuntimeError", "GripperReadbackError"} else "OTHER")
            except Exception:
                self._fail("SNAPSHOT_FAILED")
            raise
        try:
            self._observe(owner, state, grant, observation, context, began, None)
        except Exception:
            self._fail("SNAPSHOT_FAILED")
        return observation

    def _observe(self, owner, state, grant, observation, context, began, error_type):
        if self._closing.is_set():
            self._fail("CLOSED")
            return
        if not self._lock.acquire(blocking=False):
            self._fail("SNAPSHOT_BUSY")
            return
        try:
            if self._issued >= self.max_records:
                self._fail("RECORD_LIMIT")
                return
            self._issued += 1
            ordinal = self._issued
        finally:
            self._lock.release()
        transfer, profile = grant.cell_transfer, owner.profile
        recipe, item = _digest(transfer.recipe_sha256), _identifier(transfer.item_key)
        width = self._geometry.get((recipe, item))
        close = contact = lower = upper = None
        if width is not None:
            close = _number(profile.gripper_close_for_width(width))
            contact = _number(profile.gripper_contact_for_width(width))
            if close is not None and contact is not None:
                threshold = (contact - close) / 2
                lower, upper = _number(close + threshold), _number(contact + threshold)
        observed = None
        if observation is not None:
            observed = {"state": observation.state if observation.state in {"OPEN", "CLOSED", "UNKNOWN"} else None,
                "object_present": observation.object_present if type(observation.object_present) is bool else None,
                "object_id": _identifier(observation.object_id), "sequence": _integer(observation.sequence),
                "received_at": _number(observation.received_at),
                "owner_generation": _integer(observation.owner_generation)}
        record = {"schema": "rosy.g2-gripper-readback/1", "diagnostic_only": True,
            "snapshot": "SAME_JOINT_STATE_NONATOMIC_TIMING", "ordinal": ordinal,
            "action_id": _identifier(grant.action_id), "attempt_id": _identifier(grant.attempt_id),
            "context": context if context in {"workflow", "before_transfer", "before_release"} else "UNKNOWN",
            "recipe_sha256": recipe, "item_key": item, "item_id": _identifier(transfer.item),
            "geometry_binding": "ACCEPT_RECIPE_RECEIPT" if width is not None else "NOT_IN_ACCEPTED_RECEIPT",
            "accepted_grasp_width_m": width, "close_q_rad": close, "contact_q_rad": contact,
            "hold_lower_q_rad": lower, "hold_upper_q_rad": upper,
            "open_q_rad": _number(profile.gripper_open),
            "open_tolerance_rad": _number(profile.start_state_tolerance_rad),
            "max_age_s": _number(profile.max_joint_state_age_s),
            "q_rad": _number(state.positions.get(profile.gripper_joint)),
            "arm_q_rad": {name: _number(state.positions.get(name)) for name in
                          ("joint1", "joint2", "joint3", "joint4", "joint5")},
            "joint_sequence": _integer(state.sequence), "joint_received_at": _number(state.received_at),
            "owner_now": _number(owner.runtime.monotonic()), "read_started_steady": _number(began),
            "snapshot_steady": _number(time.monotonic()), "snapshot_wall": _number(time.time()),
            "observation": observed, "canonical_error_type": error_type}
        if not self._lock.acquire(blocking=False):
            self._fail("ENQUEUE_BUSY")
            return
        try:
            self._pending.append(record)
        finally:
            self._lock.release()
        self._wake.set()

    def _write_pending(self):
        while True:
            with self._lock:
                record = self._pending.popleft() if self._pending else None
            if record is not None:
                try:
                    _write_record(self.directory / (str(record["ordinal"]).zfill(3) + ".json"), record)
                    self._written = min(LIMIT, self._written + 1)
                except Exception:
                    self._fail("WRITE_FAILED")
                continue
            if self._closing.is_set():
                return
            self._wake.wait(.05)
            self._wake.clear()

    def status(self):
        return {"issued": self._issued, "written": self._written,
                "failures": self._failures, "failure_code": self._failure_code}

    def close(self, *, timeout=.5):
        self._closing.set()
        self._wake.set()
        self._writer.join(max(0., min(2., timeout)))
        return not self._writer.is_alive()
