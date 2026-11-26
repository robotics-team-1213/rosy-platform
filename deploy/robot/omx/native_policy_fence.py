"""Owner-local D-1024 grant fence. Only a transport-authenticated CORE peer supplies grants.

The fence records authority and terminal revocation. Neither a grant nor its expiry
is a motor command or proof of HOLD. A writer must separately enforce the fence
at each hardware write, cancel queued commands and confirm torque-on HOLD.
"""
import re
import secrets
import sqlite3
import threading
import time


PINS = ("workcell_id", "policy_digest", "rig_revision", "calibration_revision", "scope")
FIELDS = {*PINS, "lease_id", "episode_id", "ttl_s", "seq", "window_remaining_s"}


class PolicyWriteRefused(PermissionError):
    """No new register command may start. Preserve torque and hand over to the owner's HOLD path."""


class PolicyWriterMixin:
    """Fence-gated register writes for NativeJointMotion; a plain recorder session keeps _policy_fence None."""
    _policy_fence = None

    @classmethod
    def for_policy(cls, follower, *, fence, clock=time.monotonic):
        """Register guard for an exclusive native policy writer; never enroll a recorder session."""
        if not isinstance(fence, NativePolicyFence):
            raise ValueError("an owner-local native policy fence is required")
        motion = cls(follower, None, teacher=True, clock=clock)
        motion._policy_fence = fence
        return motion

    def _policy_hold(self, reason):
        """Hold the fence for a policy writer; False (no-op) on a plain recorder session."""
        if self._policy_fence is None:
            return False
        self._policy_fence.hold(reason)
        return True

    def write_goal(self, goals):
        if self._policy_fence is None:
            return self.follower.sync_write("Goal_Position", goals, normalize=False)
        return self._policy_fence.write_current(self.follower.sync_write, "Goal_Position", goals, normalize=False)

    def _enable_policy_torque(self, read_retry):
        # Vendor enable_torque loops over joints. Send one bounded group register command for the six-axis owner.
        expected = dict.fromkeys(self.active, 1)
        self._policy_fence.write_current(self.follower.sync_write, "Torque_Enable", expected, normalize=False)
        torque = self.follower.sync_read("Torque_Enable", motors=list(self.active), normalize=False, num_retry=read_retry)
        if not isinstance(torque, dict) or torque != expected or any(type(v) is not int for v in torque.values()):
            self._policy_fence.hold("seed_torque_unconfirmed")
            raise PolicyWriteRefused("seed torque readback did not confirm all joints")


class NativePolicyFence:
    def __init__(self, pins, journal, *, clock=time.monotonic_ns):
        if set(pins) != set(PINS) or not all(isinstance(v, str) and v.strip() == v and v for v in pins.values()):
            raise ValueError("incomplete policy scope")
        if (not re.fullmatch(r"[a-f0-9]{64}", pins["policy_digest"])
                or not re.fullmatch(r"cell-task:[A-Za-z0-9._@-]{1,128}:arm_b", pins["scope"])):
            raise ValueError("expected B task scope and policy digest")
        self.pins = dict(pins)
        self.owner_session_id = secrets.token_hex(32)
        self._clock = clock
        self._journal = journal
        with sqlite3.connect(journal) as db:
            db.execute("CREATE TABLE IF NOT EXISTS episodes (episode_id TEXT PRIMARY KEY, lease_id TEXT NOT NULL UNIQUE)")
        self._cond = threading.Condition()
        self._writer = threading.Lock()
        self._expires = self._window_end = self._seq = 0
        self._last_now = None
        self._ids = None
        self._reason = None
        self._watch = threading.Thread(target=self._watchdog, name="native-policy-expiry", daemon=True)
        self._watch.start()

    def _trip(self, reason):
        if self._reason is None:
            self._reason = reason
        self._cond.notify_all()

    def hold(self, reason):
        with self._cond:
            self._trip(reason)

    def close(self):
        self.hold("owner_session_closed")
        self._watch.join()

    def _now(self):
        try:
            now = self._clock()
            if type(now) is not int or now < 0 or (self._last_now is not None and now < self._last_now):
                raise ValueError("invalid owner clock")
        except Exception:
            self._trip("owner_clock_fault")
            return 0
        self._last_now = now
        return now

    def _expire(self, now):
        if self._expires and now >= self._expires:
            self._trip("policy_lease_expired")

    def _watchdog(self):
        with self._cond:
            while self._reason is None:
                now = self._now()
                self._expire(now)
                if self._reason is None:
                    wait = (self._expires - now) / 1e9 if self._expires else None
                    self._cond.wait(wait)

    def status(self):
        with self._cond:
            self._expire(self._now())
            return {"lease_current": bool(self._expires and self._reason is None),
                    "hold_reason": self._reason, "lease_expires_at_ns": self._expires}

    def require_current(self):
        if not self.status()["lease_current"]:
            raise PolicyWriteRefused("no current native policy lease")

    def write_current(self, operation, *args, **kwargs):
        """Order one synchronous register transaction against expiry and explicit revocation.

        A caller must separately bound and supervise the physical bus transaction itself.
        """
        # Serialize writers; never hold the watchdog condition across potentially blocking device I/O.
        # A transaction already admitted may still be on the wire when authority is revoked.
        with self._writer:
            self.require_current()
            return operation(*args, **kwargs)

    def receive(self, owner_session_id, not_after_monotonic_ns, grant):
        """Consume a CORE-authenticated grant with a deadline in this host's monotonic clock."""
        with self._cond:
            now = self._now()
            self._expire(now)
            if self._reason is not None:
                raise PermissionError(self._reason)
            try:
                if (owner_session_id != self.owner_session_id or not isinstance(grant, dict)
                        or set(grant) != FIELDS or any(grant[k] != v for k, v in self.pins.items())):
                    raise ValueError("grant scope mismatch")
                ttl, window, seq = grant["ttl_s"], grant["window_remaining_s"], grant["seq"]
                if (type(seq) is not int or seq != self._seq + 1 or type(ttl) not in (float, int)
                        or type(window) not in (float, int) or not 0 < ttl <= 2 or not 0 < window <= 1800
                        or type(not_after_monotonic_ns) is not int or not now < not_after_monotonic_ns
                        or not_after_monotonic_ns > now + int(min(ttl, window) * 1e9)):
                    raise ValueError("grant deadline or sequence invalid")
                ids = (grant["episode_id"], grant["lease_id"])
                if any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", i) for i in ids):
                    raise ValueError("invalid episode or lease id")
                if self._ids is None:
                    with sqlite3.connect(self._journal, timeout=0.1) as db:
                        db.execute("PRAGMA synchronous=FULL")
                        db.execute("INSERT INTO episodes VALUES (?,?)", ids)
                    # The gateway charged transport delay to the issued TTL. Anchor the window to that same instant.
                    self._window_end = not_after_monotonic_ns + int(max(0, window - min(ttl, window)) * 1e9)
                elif ids != self._ids:
                    raise ValueError("episode or lease changed")
                deadline = min(self._window_end, not_after_monotonic_ns)
                now = self._now()
                if self._reason is not None or now >= min(deadline, self._expires or deadline):
                    raise ValueError("grant expired before commit")
                self._ids, self._seq, self._expires = ids, seq, deadline
                self._cond.notify_all()
                return deadline
            except (ValueError, OverflowError, sqlite3.Error) as err:
                self._trip("policy_grant_refused")
                raise PermissionError(self._reason) from err
