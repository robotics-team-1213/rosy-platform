"""D-1024 3: the supervisor's side of the runner's lease watchdog (chunk_runner_lease): grants in policy_lease_push form.

Written atomically to `<io>/policy-lease.json` every `period_s` with a ttl of 1 s (the receiver default; the cap is 2 s). The
first grant is not enough: no motion starts until the runner's live.json says it armed this episode's lease, so a runner
without the watchdog refuses the run instead of ignoring the lease. When this process dies or stops renewing, the runner holds
by itself within the ttl; a clean end writes the `released` marker.
shortcut: the renewing thread proves this process lives, not that its policy loop makes progress; observation age and the
runner's stall guards cover a stuck loop, a progress-gated renewal needs run_timed to report each chunk.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

from chunk_runner_lease import policy_playing

LEASE_FILE = "policy-lease.json"
UNACKED = "POLICY_LEASE_UNACKED"  # cell_task_act reads this as PHYSICAL_POLICY_LEASE_OWNER_UNAVAILABLE


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class LeaseFeed:
    def __init__(self, cell, *, episode_id, workcell_id, policy_digest, rig_revision, calibration_revision,
                 window_s=300.0, ttl_s=1.0, period_s=0.5, ack_timeout_s=3.0, monotonic=time.monotonic):
        self.cell, self.path, self.monotonic = cell, Path(cell.io) / LEASE_FILE, monotonic
        self.scope = {"lease_id": uuid.uuid4().hex, "episode_id": episode_id, "workcell_id": workcell_id,
                      "policy_digest": policy_digest, "rig_revision": rig_revision, "calibration_revision": calibration_revision}
        self.ttl_s, self.period_s, self.ack_timeout_s = ttl_s, period_s, ack_timeout_s
        self.end, self.seq = monotonic() + window_s, 0
        self._stop, self._thread = threading.Event(), None

    @classmethod
    def from_args(cls, args, config, cell):
        """None without --policy-lease; the grant is bound to the pinned checkpoint, the library and the cell calibration."""
        if not args.policy_lease:
            return None
        return cls(cell, episode_id=args.task_id or uuid.uuid4().hex, workcell_id=str(config.get("arm_id") or "arm"),
                   policy_digest=args.policy_revision, rig_revision=_sha(args.library),
                   calibration_revision=_sha(args.cell_calibration))

    def _write(self, body: dict) -> bool:
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(body), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False  # no renewal: the runner's ttl runs out and it holds

    def _grant(self) -> bool:
        remaining = self.end - self.monotonic()
        if remaining <= 0:
            return False
        self.seq += 1
        return self._write({**self.scope, "ttl_s": self.ttl_s, "seq": self.seq, "window_remaining_s": remaining})

    def _renew(self) -> None:
        while not self._stop.wait(self.period_s):
            if not self._grant():
                return

    def start(self) -> str | None:
        """None when the runner armed this episode's lease, else the refusal reason (nothing has moved)."""
        if not self._grant():
            return UNACKED
        self._thread = threading.Thread(target=self._renew, name="policy-lease", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + self.ack_timeout_s
        while time.monotonic() < deadline:
            lease = (self.cell.policy_state() or {}).get("policy_lease")
            if (isinstance(lease, dict) and lease.get("armed") is True and lease.get("closed") is False
                    and lease.get("episode_id") == self.scope["episode_id"] and lease.get("lease_id") == self.scope["lease_id"]
                    and isinstance(lease.get("seq"), int) and lease["seq"] >= 1):
                return None
            time.sleep(0.05)
        self.stop()
        return UNACKED

    def stop(self) -> None:
        """Renewals end now. The lease is released only once the runner has left its policy chunk; an abnormal end while one
        still plays is left to run out, which is the runner's human-hold."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        deadline, idle = time.monotonic() + 0.5, False
        while not idle and time.monotonic() < deadline:  # only a fresh, readable live.json that shows no policy chunk counts
            live = self.cell.policy_state()
            idle = (isinstance(live, dict) and "chunk" in live and not policy_playing(live["chunk"])
                    and type(live.get("t")) in (int, float) and abs(time.time() - live["t"]) <= 1.0)
            if not idle:
                time.sleep(0.05)
        if idle and self.seq:
            self._write({"released": True, "episode_id": self.scope["episode_id"]})
