"""Boot stage model shared by the boot indicator and the black box.

Pure and standard-library only: it runs outside CORE (D-174, D-175) precisely
when CORE may not exist. Callers gather unit states with ``systemctl`` and the
first-boot state file, then render the stage to their own sinks.
"""

from __future__ import annotations

from dataclasses import dataclass


# Boot order: the earliest failed unit explains the ones after it.
BOOT_UNITS = (
    "rosy-release-recover.service",
    "rosy-first-boot.service",
    "rosy-sd-provision.service",
    "rosy-core.service",
    "rosy-runtime.target",
)
PROVISIONED_STATES = {"PROVISIONED", "ALREADY_PROVISIONED"}
HELD_STATES = {"PROVISIONING_AP", "PROVISIONING_HOLD"}


@dataclass(frozen=True)
class Stage:
    name: str  # BOOTING | PROVISIONED | CORE_READY | FAILED
    failed_unit: str | None = None
    detail: str | None = None

    @property
    def label(self) -> str:
        if self.failed_unit is None:
            return self.name
        return f"{self.name}:{self.failed_unit.rsplit('.', 1)[0]}"


def classify(units: dict[str, str], provisioning: dict | None) -> Stage:
    """Map systemd ActiveState values and the first-boot state to one stage."""
    for unit in BOOT_UNITS:
        if units.get(unit) == "failed":
            return Stage("FAILED", unit)
    state = (provisioning or {}).get("state")
    if state in HELD_STATES:
        reason = (provisioning or {}).get("reason", "unknown")
        return Stage("FAILED", "rosy-first-boot.service", f"{state}: {reason}")
    if all(units.get(unit) == "active" for unit in BOOT_UNITS) and state in PROVISIONED_STATES:
        return Stage("CORE_READY")
    if state in PROVISIONED_STATES:
        return Stage("PROVISIONED")
    return Stage("BOOTING")
