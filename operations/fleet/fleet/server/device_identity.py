"""D-797 3 owner identity predicates shared by every Fleet dispatcher (D-977 3)."""
from typing import Any, Mapping


def device_trial_identity_ok(identity: Mapping[str, Any], *, workcell_id: str, instance_id: str, expected: Any) -> bool:
    """A real owner reports ``device: true``, no simulation, its own ids and the configured commissioning revision."""
    return (identity.get("device") is True and identity.get("simulation") is not True
            and isinstance(expected, str) and expected != ""
            and identity.get("commissioning_revision") == expected
            and identity.get("instance_id") == instance_id and identity.get("workcell_id") == workcell_id)
