"""D-977 2: the cell Fleet's device_trial ARM transfer settings, read from the environment at startup.

Unset keeps today's behaviour (profile `production`, no ARM transfer HTTP, no observer). Nothing here lets a goal
reach the arm: the hardware owner still refuses goals until D-977 Decision 4.
"""
from datetime import datetime
import json
import os
from pathlib import Path

PROFILE_ENV = "ROSY_DEPLOYMENT_PROFILE"
INSTALLATION_ENV = "ROSY_ARM_TRANSFER_INSTALLATION"  # same written file the owner reads (tools/sim/transfer_installation.py)
GRANTS_ENV = "ROSY_FLEET_OMX_GRANT_REVISIONS"
OBSERVER_TOKEN_ENV = "ROSY_ARM_TRANSFER_OBSERVER_TOKEN"  # filled from a secret file by deploy/site/secret_exec.py
OBSERVER_VALID_UNTIL_ENV = "ROSY_ARM_TRANSFER_OBSERVER_VALID_UNTIL"
_GRANT_KEYS = frozenset({"capability_revision", "config_revision", "commissioning_revision"})


def deployment_profile(environ=os.environ) -> str:
    value = environ.get(PROFILE_ENV)
    if value is None:
        return "production"
    if value not in ("device_trial", "production"):
        raise SystemExit(f"{PROFILE_ENV} must be device_trial or production, got {value!r}")
    return value


def grant_revisions(environ=os.environ):
    """{instance: {capability_revision, config_revision, commissioning_revision}} from JSON; unset = None."""
    raw = environ.get(GRANTS_ENV)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(f"{GRANTS_ENV} must be a JSON object") from None
    if (not isinstance(value, dict) or not value
            or not all(isinstance(k, str) and k and isinstance(v, dict) and v and set(v) <= _GRANT_KEYS
                       and all(isinstance(x, str) and x for x in v.values()) for k, v in value.items())):
        raise SystemExit(f"{GRANTS_ENV} must map instance ids to {sorted(_GRANT_KEYS)} strings")
    return value


OWNER_DOWN = "owner-unavailable"  # placeholder id; no live owner ever reports it, so every live-capability check fails closed


def fleet_installation(written, socket_root, *, owner_may_be_down=False):
    """Fleet's TransferInstallation: the written policy plus each running owner's own capability.

    The owner's resource_policy_digest must equal the written policy digest (TransferInstallation refuses otherwise).
    owner_may_be_down (cell Fleet startup): an unreachable owner gets a placeholder capability instead of aborting
    Fleet; admit and prepare then refuse (capability changed) until Fleet restarts with the owner answering.
    """
    from fleet.server.local_action_transport import UnixLocalActionTransport
    from fleet.server.physical_transfer_evidence import PhysicalTransferPolicy
    from fleet.server.physical_transfer_store import TransferInstallation
    installed = PhysicalTransferPolicy.model_validate_json(json.dumps(written["policy"]))
    if installed.digest != written["policy_digest"]:
        raise ValueError("policy digest does not match the written policy")
    transport = UnixLocalActionTransport(socket_root)
    def capability(p):
        try:
            return transport.transfer_capability(p.instance_id, workcell_id=p.workcell_id)
        except (OSError, TimeoutError):
            if not owner_may_be_down:
                raise
            from core_common.protocol.arm_transfer import ArmTransferCapability
            return ArmTransferCapability(action_kind="ARM_TRANSFER", control_mode="fleet_managed",
                workcell_id=p.workcell_id, instance_id=p.instance_id, journal_id=OWNER_DOWN,
                owner_session_id=OWNER_DOWN, catalog_digest=installed.catalog_digest,
                bindings_digest=installed.bindings_digest, resource_policy_digest=installed.digest,
                capability_revision=OWNER_DOWN, config_revision=OWNER_DOWN)
    capabilities = tuple(capability(p) for p in installed.participants)
    return TransferInstallation(policy=installed, source="source", target="target", capabilities=capabilities)


def load_installation(profile, socket_root, environ=os.environ):
    """None without the env; refuses outside device_trial, for other than one arm, or when the owner disagrees."""
    path = environ.get(INSTALLATION_ENV)
    if not path:
        return None
    if profile != "device_trial":
        raise SystemExit(f"{INSTALLATION_ENV} requires {PROFILE_ENV}=device_trial")
    try:
        written = json.loads(Path(path).read_text(encoding="utf-8"))
        if len(written["policy"]["participants"]) != 1:
            raise SystemExit("device_trial ARM transfer installs exactly one participant arm")
        return fleet_installation(written, socket_root, owner_may_be_down=True)
    except SystemExit:
        raise
    except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        raise SystemExit(f"cannot install ARM transfer from {path}: {exc}") from exc


def load_observer(installation, environ=os.environ):
    """None without the token (dispatch is then impossible); producer id comes from the installed policy."""
    token = environ.get(OBSERVER_TOKEN_ENV)
    if not token:
        return None
    if installation is None:
        raise SystemExit(f"{OBSERVER_TOKEN_ENV} requires an installed ARM transfer ({INSTALLATION_ENV})")
    from fleet.server.physical_transfer_observer import PhysicalTransferObserver
    try:
        return PhysicalTransferObserver(producer_id=installation.policy.producer_id, token=token,
                                        valid_until=datetime.fromisoformat(environ.get(OBSERVER_VALID_UNTIL_ENV, "")))
    except ValueError as exc:
        raise SystemExit(f"invalid ARM transfer observer settings ({OBSERVER_VALID_UNTIL_ENV} needs an ISO "
                         f"timestamp with a timezone): {exc}") from exc
