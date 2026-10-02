"""ROS-free Skill boundary checks for the pallet.transfer execution seam."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import ast
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for package_root in (
    ROOT / "modules/skills/api/src",
    ROOT / "modules/execution/src",
    ROOT / "modules/skills/manipulation/src",
):
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from rosy.execution.api import AttemptIdentity, ReceiptBinding  # noqa: E402
from rosy.execution.local.receipts import (  # noqa: E402
    AttemptIdentity as LocalAttemptIdentity,
    ReceiptBinding as LocalReceiptBinding,
)
from rosy.skills.api import SkillInvocation  # noqa: E402
from rosy.skills.manipulation.transfer import (  # noqa: E402
    COMPLETION_CONDITIONS,
    EvidenceVerdict,
    TransferSkill,
)


class FakePlanner:
    def __init__(self):
        self.invocations = []

    def plan(self, invocation):
        self.invocations.append(invocation)
        return {"plan": "opaque-to-skill"}


class FakePhaseExecutor:
    def __init__(self):
        self.plans = []

    def start(self, plan):
        self.plans.append(plan)
        return {
            "state": "ACCEPTED", "action_id": "action-1",
            "attempt_id": "attempt-1",
        }


class FakeEvidence:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []

    def verify(self, invocation, plan, receipt):
        self.calls.append((invocation, plan, receipt))
        return self.verdict


def _invocation():
    return SkillInvocation("pallet.transfer", "1.0.0", {
        "item": "box", "pallet_id": "pallet-1", "layer_index": 0,
        "home_pose_base": {"x_m": 0.1, "y_m": 0.0, "z_m": 0.2, "yaw_rad": 0.0},
        "source_pose_base": {
            "x_m": 0.2, "y_m": 0.0, "z_m": 0.04, "yaw_rad": 0.0,
        },
        "destination_pose_base": {
            "x_m": 0.3, "y_m": 0.0, "z_m": 0.04, "yaw_rad": 0.0,
        },
        "source_approach_z_base_m": 0.12,
        "destination_approach_z_base_m": 0.12,
        "carry_z_base_m": 0.18,
    })


def test_execution_api_keeps_receipt_binding_compatibility_alias():
    assert AttemptIdentity is LocalAttemptIdentity
    assert ReceiptBinding is LocalReceiptBinding


def test_skill_plans_then_starts_only_through_injected_ports():
    skill = TransferSkill()
    invocation = _invocation()
    planner, executor = FakePlanner(), FakePhaseExecutor()

    planned = skill.plan(invocation, planner)
    receipt = skill.start(planned, executor)

    assert planner.invocations == [invocation]
    assert executor.plans == [planned]
    assert receipt["state"] == "ACCEPTED"
    assert not hasattr(planned, "action_id")
    assert not hasattr(planned, "attempt_id")


def test_skill_requires_complete_independent_evidence_for_success():
    skill = TransferSkill()
    invocation = _invocation()
    planned = skill.plan(invocation, FakePlanner())
    receipt = {"state": "SUCCEEDED", "journal_event_id": 9}
    evidence = FakeEvidence(EvidenceVerdict(
        state="VERIFIED", conditions=COMPLETION_CONDITIONS,
        references=("gripper:readback:7", "sim-model-pose:frame:11"),
    ))

    result = skill.verify_completion(
        invocation, planned, receipt, evidence, action_state="SUCCEEDED",
    )

    assert result.state == "SUCCEEDED"
    assert set(result.evidence_references) == set(evidence.verdict.references)
    assert evidence.calls == [(invocation, planned, receipt)]
    with pytest.raises(FrozenInstanceError):
        result.state = "HOLD"


@pytest.mark.parametrize(
    ("action_state", "evidence_state", "expected"),
    [
        ("UNKNOWN", "VERIFIED", "UNKNOWN"),
        ("ACCEPTED", "VERIFIED", "HOLD"),
        ("SUCCEEDED", "UNKNOWN", "UNKNOWN"),
        ("SUCCEEDED", "HOLD", "HOLD"),
    ],
)
def test_skill_never_promotes_unresolved_execution_or_evidence(
    action_state, evidence_state, expected,
):
    skill = TransferSkill()
    invocation = _invocation()
    planned = skill.plan(invocation, FakePlanner())
    evidence = FakeEvidence(EvidenceVerdict(
        state=evidence_state, conditions=frozenset(), references=(),
    ))

    result = skill.verify_completion(
        invocation, planned, {"state": action_state}, evidence,
        action_state=action_state,
    )

    assert result.state == expected
    assert result.state != "SUCCEEDED"


def test_skill_rejects_missing_evidence_and_malformed_inputs_before_ports():
    skill = TransferSkill()
    planner, executor = FakePlanner(), FakePhaseExecutor()
    invocation = _invocation()
    planned = skill.plan(invocation, planner)
    incomplete = FakeEvidence(EvidenceVerdict(
        state="VERIFIED", conditions=frozenset({"gripper_release_verified"}),
        references=("gripper:readback:7",),
    ))
    result = skill.verify_completion(
        invocation, planned, {"state": "SUCCEEDED"}, incomplete,
        action_state="SUCCEEDED",
    )
    assert result.state == "HOLD"

    bad = SkillInvocation("pallet.transfer", "1.0.0", {"item": "box"})
    with pytest.raises(ValueError, match="inputs"):
        skill.plan(bad, planner)
    with pytest.raises(ValueError, match="ID/version"):
        skill.plan(SkillInvocation("pallet.transfer", "2.0.0", {}), planner)
    assert len(planner.invocations) == 1
    assert executor.plans == []


def test_skill_module_has_no_robot_or_persistence_imports():
    relative = (
        "modules/skills/manipulation/src/rosy/skills/"
        "manipulation/transfer.py"
    )
    path = ROOT / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = {
        "rclpy", "sqlite3", "omx_adapter", "core_common.protocol.schemas",
    }
    assert not forbidden & imported
