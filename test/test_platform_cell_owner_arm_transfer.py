"""D-927 stream C: the simulation cell owner serves Fleet-managed ARM_TRANSFER from one installed catalog."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for relative in ("middleware/devices/omx/adapter/test",):
    if str(ROOT / relative) not in sys.path:
        sys.path.insert(0, str(ROOT / relative))

from test_platform_cell_owner_assembly import FLEET_UID, _build  # noqa: E402
from test_omx_pose_plan import kin, profile  # noqa: E402,F401
from test_transfer_preflight import _catalog  # noqa: E402

from omx_adapter.transfer_object_bindings import TransferObjectBindings  # noqa: E402
from rosy.integrations.robots.omx.arm_transfer import ArmTransferInstallation  # noqa: E402
from rosy_agent.omx_cell_owner import sim_gripper_observation  # noqa: E402


def _installation(kin, profile, **changes):
    values = dict(workcell_id="omx_cell_sim", instance_id="omx_cell_sim_01",
                  calibration_revision="omx-f-gazebo-only-v1", transform_revision="gz-world-is-link0-v1")
    catalog = _catalog(kin, profile, **{**values, **changes})
    return ArmTransferInstallation(TransferObjectBindings(catalog, {"object-1": "g1"}), "arm-cap-1", "cfg-1", "d" * 64)


def _arm_owner(tmp_path, installation):
    return _build(tmp_path, arm_transfer=installation,
                  goal_port_factory=lambda runtime: SimpleNamespace(command_owner=runtime.owner))[0]


def test_owner_describes_its_installed_arm_transfer_capability(tmp_path, kin, profile):
    installation = _installation(kin, profile)
    owner = _arm_owner(tmp_path, installation)
    reply = owner.action_api.dispatch({"version": 2, "operation": "GetTransferCapability"}, peer_uid=FLEET_UID)
    assert reply["status"] == 200, reply
    capability = reply["capability"]
    assert capability["catalog_digest"] == installation.bindings.catalog.digest
    assert capability["bindings_digest"] == installation.bindings.revision
    assert capability["owner_session_id"] == owner.runtime.owner.session_id
    assert capability["journal_id"] == owner.action_api.identity["journal_id"]
    # Managed mode excludes Pilot seats on the same arm.
    with pytest.raises(PermissionError):
        owner.runner.control_admission.acquire("token", "seat", ttl_s=1)


def test_owner_without_arm_transfer_still_refuses_the_capability(tmp_path):
    owner, _ = _build(tmp_path)
    reply = owner.action_api.dispatch({"version": 2, "operation": "GetTransferCapability"}, peer_uid=FLEET_UID)
    assert reply["error"]["code"] == "ARM_TRANSFER_CAPABILITY_UNAVAILABLE", reply


def test_a_catalog_for_another_owner_is_refused(tmp_path, kin, profile):
    with pytest.raises(ValueError, match="another owner"):
        _arm_owner(tmp_path, _installation(kin, profile, instance_id="omx_cell_sim_02"))


def test_sim_gripper_reads_the_bound_object_for_an_arm_grant(tmp_path, kin, profile):
    installation = _installation(kin, profile)
    owner = _arm_owner(tmp_path, installation)
    catalog = installation.bindings.catalog
    grant = SimpleNamespace(action_kind="ARM_TRANSFER", dispatch_generation=8, arm_transfer=SimpleNamespace(
        object_ref="object-1", catalog_digest=catalog.digest, bindings_digest=installation.bindings.revision))
    joint = owner.profile.gripper_joint
    closed = owner.profile.gripper_contact_for_width(catalog.geometries["g1"].grasp_width_m)
    held = sim_gripper_observation(owner, SimpleNamespace(sequence=5, received_at=100.0,
                                                          positions={joint: closed}), grant)
    assert (held.state, held.object_id) == ("CLOSED", "object-1")
    opened = sim_gripper_observation(owner, SimpleNamespace(sequence=6, received_at=100.0,
                                                            positions={joint: owner.profile.gripper_open}), grant)
    assert (opened.state, opened.object_id) == ("OPEN", None)
