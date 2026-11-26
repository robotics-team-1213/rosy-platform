"""D-1024 3 / D-793 2: the chunk runner's own execution-lease watchdog for a physical learned policy.

The grant has the exact form of `policy_lease_push.PushLeaseReceiver` (`lease_id, episode_id, workcell_id, policy_digest,
rig_revision, calibration_revision, ttl_s, seq, window_remaining_s`, ttl <= 2 s, seq strictly increasing, window <= 30 min).
The supervisor (cell_policy_drive) writes it atomically to `<io>/policy-lease.json` about twice per ttl; the runner turns each
new seq into a lease on its own monotonic clock, and no lease passes the episode deadline the first grant fixed.
Nothing arms until a first grant is seen, so runs without a lease behave as before. Once armed, a missing renewal, a replayed
or changed grant, a clock fault or an unreadable file closes the watch for good (no re-arm), and while a `policy` chunk plays
the runner loop turns that into its normal `human-hold` (torque kept, person needed). A clean end is a `released` marker.
Receipt is stamped by the runner's clock at the poll, not at the writer, so a delayed grant can only be later, never earlier.
Known limits: a lease that ran out between two policy chunks holds when the next one starts (one tick of motion at most); a
closed watch stays closed until the runner restarts, so later Fleet ACT tasks refuse with
PHYSICAL_POLICY_LEASE_OWNER_UNAVAILABLE until a person has released the hold and the session restarted.
"""
import json
import math
import os

LEASE_FILE = "policy-lease.json"
MAX_LEASE_S = 2.0  # D-793 2, as policy_lease_push.MAX_LEASE_S
MAX_WINDOW_S = 30 * 60
GRANT_KEYS = frozenset({"lease_id", "episode_id", "workcell_id", "policy_digest", "rig_revision", "calibration_revision",
                        "ttl_s", "seq", "window_remaining_s"})
_PINNED = ("lease_id", "episode_id", "workcell_id", "policy_digest", "rig_revision", "calibration_revision")


def _number(value, low, high) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low < value <= high


def policy_playing(chunk) -> bool:
    """True while a chunk label (also a chained one, `a -> policy`) names the policy chunk."""
    return "policy" in str(chunk or "").replace("->", " ").split()


class PolicyLeaseWatch:
    def __init__(self, path, clock):
        self.path, self.clock = path, clock
        self.armed = self.closed = False
        self.reason, self.seq, self.episode_id = "", 0, None
        self._pin = self._deadline = self._expires = self._last_now = self._seen = None
        try:
            os.unlink(path)  # a grant left by an earlier session never arms this one
        except OSError:
            pass

    def status(self) -> dict:
        return {"armed": self.armed, "closed": self.closed, "seq": self.seq, "episode_id": self.episode_id,
                "lease_id": (self._pin or {}).get("lease_id"),
                **({"reason": self.reason} if self.reason else {})}

    def _close(self, reason: str) -> None:
        if not self.closed:
            self.closed, self.reason = True, reason

    def _grant(self, grant, now: float) -> None:
        if not isinstance(grant, dict) or set(grant) != GRANT_KEYS:
            raise ValueError("lease_grant_malformed")
        if not (_number(grant["ttl_s"], 0, MAX_LEASE_S) and _number(grant["window_remaining_s"], 0, MAX_WINDOW_S)
                and type(grant["seq"]) is int):
            raise ValueError("lease_grant_range")
        digest = grant["policy_digest"]
        if (not all(isinstance(grant[k], str) and grant[k] for k in _PINNED) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("lease_grant_scope")
        pin = {k: grant[k] for k in _PINNED}
        if self._pin is not None and pin != self._pin:
            raise PermissionError("lease_scope_changed")
        if grant["seq"] <= self.seq:
            raise PermissionError("lease_replay")
        deadline = now + grant["window_remaining_s"]
        if self._deadline is not None:  # a delayed grant computes a later deadline; the earlier one stands
            deadline = min(self._deadline, deadline)
        self._pin, self._deadline, self.seq = pin, deadline, grant["seq"]
        self._expires, self.armed, self.episode_id = min(now + grant["ttl_s"], deadline), True, pin["episode_id"]

    def _read(self, now: float) -> None:
        try:
            stat = os.stat(self.path)
            key = (stat.st_mtime_ns, stat.st_size, stat.st_ino)  # the writer replaces the file: a new inode per grant
            if key == self._seen:
                return
            with open(self.path, encoding="utf-8") as stream:
                grant = json.load(stream)
        except FileNotFoundError:
            return  # no renewal: the ttl runs out
        except (OSError, ValueError, RecursionError):
            if self.armed:
                self._close("lease_unreadable")
            return
        self._seen = key
        if isinstance(grant, dict) and grant.get("released") is True:
            if self.armed and grant.get("episode_id") == self.episode_id:
                self.armed, self._pin, self._deadline, self._expires, self.seq = False, None, None, None, 0
            return
        try:
            self._grant(grant, now)
        except (ValueError, PermissionError) as error:
            if self.armed or isinstance(error, PermissionError):
                self._close(str(error))

    def poll(self, policy_running: bool):
        """The hold reason while a policy chunk plays on a closed watch, else None."""
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or (self._last_now is not None and now < self._last_now):
            self._close("lease_clock_fault")
        else:
            self._last_now = now
            if not self.closed:
                self._read(now)
            if self.armed and not self.closed and now >= self._expires:
                self._close("lease_expired")
        return self.reason if self.closed and policy_running else None
