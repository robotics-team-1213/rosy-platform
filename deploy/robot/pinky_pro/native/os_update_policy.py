"""Read-only OS admission using the native updater's common operator policy."""
from __future__ import annotations

from pathlib import Path
import uuid

from auto_update_host import Host, SAMPLE_GAP_S, UpdateError, _finite
from auto_update_records import UpdaterRecords
import rosy_claim
from os_update_state import read_state


class _Policy(UpdaterRecords):
    def __init__(self, root: Path, host: Host):
        self.root, self.host = root, host

    def _judge_inputs(self, data: object) -> list[str]:
        problems = super()._judge_inputs(data)
        if isinstance(data, dict):
            percent = data.get("battery_percent")
            if not (_finite(percent) and 60 <= percent <= 100):
                problems.append("OS update requires a known battery level between 60 and 100 percent")
            if type(data.get("battery_charging")) is not bool:
                problems.append("battery charging state is unknown")
        return problems

    def _controls(self, transaction_id: str) -> list[str]:
        reasons = []
        try:
            config = self._config()
            kind, detail = self._hold()
        except UpdateError as exc:
            return [str(exc)]
        if not config["enabled"]:
            reasons.append("automatic updates disabled")
        if kind in {"active", "invalid"}:
            reasons.append(detail)
        current = self.host.current_release()
        if current is None:
            reasons.append("current native release is unknown")
        reasons += self._sealed(current) + self._network_problems()
        claim = rosy_claim.check(self.root, now=self.host.now())
        if claim is None or claim.get("holder") != "os-update:" + transaction_id:
            reasons.append("OS transaction does not hold the live claim")
        return reasons

    def _gates(self, transaction_id: str) -> list[str]:
        reasons = self._controls(transaction_id)
        pending = read_state(self.root)["pending"]
        if pending is not None and (
            pending["transaction_id"] != transaction_id
            or pending["source_boot_id"] != self.host.boot_id()
            or pending["phase"] not in {"PREPARED", "INSTALLING", "INSTALLED", "VERIFIED", "ARMED"}
        ):
            reasons.append("pending OS transaction differs or is no longer on its source boot")
        return reasons


class _TrialPolicy(_Policy):
    def _gates(self, transaction_id: str) -> list[str]:
        from os_bootloader import _snapshot
        from os_motion_guard import require_inhibited
        reasons = self._controls(transaction_id)
        facts, state, default = _snapshot(self.root)
        pending = state["pending"]
        if (pending is None or pending["transaction_id"] != transaction_id or pending["phase"] != "TRIAL"
                or facts["tryboot"] != 1 or facts["boot_id"] != self.host.boot_id()
                or pending["trial_boot_id"] != facts["boot_id"] or facts["slot"] != pending["target_slot"]
                or default != pending["source_slot"]):
            reasons.append("trial policy requires the bound, uncommitted target boot")
        require_inhibited(self.root)
        return reasons


def _authorize(policy: _Policy, transaction_id: str) -> dict:
    if not isinstance(transaction_id, str) or str(uuid.UUID(transaction_id)) != transaction_id:
        raise ValueError("OS_UPDATE_POLICY: invalid transaction UUID")
    boot_id = policy.host.boot_id()
    reasons = policy._gates(transaction_id)
    if not reasons:
        problems, first = policy._sample()
        reasons += problems
        if not problems:
            policy.host.sleep(SAMPLE_GAP_S)
            problems, second = policy._sample()
            reasons += problems
            if not problems and not (first is not None and second is not None and second > first):
                reasons.append("status-inputs was not rewritten by CORE")
            # Operator controls and the claim can change during the sample interval.
            reasons += policy._gates(transaction_id)
            if policy.host.boot_id() != boot_id:
                reasons.append("boot changed while observing CORE")
    if reasons:
        raise ValueError("OS_UPDATE_POLICY: " + "; ".join(reasons))
    return dict(boot_id=boot_id, first_written_at=first.isoformat(), second_written_at=second.isoformat())


def authorize(root: Path, transaction_id: str, *, host: Host | None = None) -> None:
    """Source admission never mutates policy/history/journal or waives CORE samples."""
    _authorize(_Policy(root, host if host is not None else Host(root)), transaction_id)


def authorize_trial(root: Path, transaction_id: str, *, host: Host | None = None) -> dict:
    """Return two fresh idle observations only for this transaction's actual trial boot."""
    return _authorize(_TrialPolicy(root, host if host is not None else Host(root)), transaction_id)
