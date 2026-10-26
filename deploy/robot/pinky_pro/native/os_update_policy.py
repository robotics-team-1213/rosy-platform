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

    def _gates(self, transaction_id: str) -> list[str]:
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
        pending = read_state(self.root)["pending"]
        if pending is not None and (
            pending["transaction_id"] != transaction_id
            or pending["source_boot_id"] != self.host.boot_id()
            or pending["phase"] not in {"PREPARED", "INSTALLING", "INSTALLED", "VERIFIED", "ARMED"}
        ):
            reasons.append("pending OS transaction differs or is no longer on its source boot")
        return reasons


def authorize(root: Path, transaction_id: str, *, host: Host | None = None) -> None:
    """Raise on deferral; never waive CORE samples or mutate policy/history/journal."""
    if not isinstance(transaction_id, str) or str(uuid.UUID(transaction_id)) != transaction_id:
        raise ValueError("OS_UPDATE_POLICY: invalid transaction UUID")
    policy = _Policy(root, host if host is not None else Host(root))
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
    if reasons:
        raise ValueError("OS_UPDATE_POLICY: " + "; ".join(reasons))
