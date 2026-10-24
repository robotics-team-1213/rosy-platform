"""Fleet checks two complete physical samples; World records confer no authority."""
from dataclasses import replace
from importlib import import_module
from pathlib import Path
import math
import xml.etree.ElementTree as ET

import pytest

from rosy.world.state.projections.omx_geometry import load_omx_geometry
from rosy.world.state.projections.physical_transfer import (
    ArmPhysicalState, Bounds3, LinkPhysicalState, PhysicalPose, TransferObservation,
)

BASE = 1_000_000_000
PRIMARY = ("w-1", "arm-1")
SECONDARY = ("w-1", "arm-2")


def api():
    try:
        return import_module("fleet.server.physical_transfer_evidence")
    except ModuleNotFoundError:
        pytest.fail("Fleet physical transfer evidence evaluator is missing")


@pytest.fixture(scope="module")
def geometry():
    assets = Path(__file__).resolve().parents[3] / "learning/envs/isaac/assets/open_manipulator_description"
    urdf = (assets / "urdf/omx_f/omx_f.urdf").read_bytes()
    meshes = {node.attrib["filename"]: (assets / node.attrib["filename"].removeprefix(
              "package://open_manipulator_description/")).read_bytes() for node in ET.fromstring(urdf).findall(".//mesh")}
    return load_omx_geometry(urdf, meshes)


@pytest.fixture
def policy(geometry):
    m = api()
    participants = tuple(m.TransferParticipant(workcell_id=w, instance_id=i, geometry=geometry,
                         calibration_revision="cal-1", transform_revision="tf-1") for w, i in (PRIMARY, SECONDARY))
    return m.PhysicalTransferPolicy(participants=participants, primary=PRIMARY, zones=(Bounds3((-.1, -.1, 0), (.1, .1, .3)),),
        zone_margin_m=.01, producer_id="observer-1", evaluator_revision="eval-1", frame_id="world",
        catalog_digest="c" * 64, bindings_digest="d" * 64, object_ref="object-1", object_origin_id="model-origin",
        source_pose=PhysicalPose((0, 0, .2), (0, 0, 0, 1)), target_pose=PhysicalPose((.05, 0, .2), (0, 0, 0, 1)),
        position_tolerance_m=.002, orientation_tolerance_rad=.02, max_linear_speed_m_s=.01,
        max_angular_speed_rad_s=.02, max_age_ns=500_000_000, min_separation_ns=100_000_000)


def context(policy, phase="PRE_DISPATCH"):
    m = api()
    return m.TransferEvidenceContext(action_id="action-1", attempt_id="attempt-1", phase=phase, not_before_ns=BASE,
        owners=tuple(m.TransferOwnerTarget(workcell_id=p.workcell_id, instance_id=p.instance_id,
                     journal_id="journal-" + p.instance_id, owner_session_id="session-1") for p in policy.participants))


def samples(policy, *, after=False):
    result = []
    for sequence, timestamp in ((1, BASE + 100_000_000), (2, BASE + 300_000_000)):
        owners = tuple(ArmPhysicalState(p.workcell_id, p.instance_id, "journal-" + p.instance_id, "session-1",
            p.geometry.model_digest, "cal-1", "tf-1", timestamp,
            {name: LinkPhysicalState(Bounds3((1, 1, 1), (1.1, 1.1, 1.1)), (0, 0, 0), (0, 0, 0))
             for name in p.geometry.required_links}, timestamp, "OPEN", "NONE", None) for p in policy.participants)
        result.append(TransferObservation("ev-" + str(sequence), "observer-1", "eval-1", sequence, "action-1", "attempt-1",
            "world", policy.digest, "c" * 64, "d" * 64, "object-1", "model-origin", timestamp,
            policy.target_pose if after else policy.source_pose, owners))
    return tuple(result)


def check(policy, observations=None, ctx=None, **kw):
    return api().validate_transfer_observations(policy, ctx or context(policy),
        observations if observations is not None else samples(policy),
        now_ns=kw.pop("now_ns", BASE + 350_000_000), authenticated_producer_id=kw.pop("authenticated_producer_id", "observer-1"), **kw)


def change_link(sample, *, participant=0, name="link7", **changes):
    owners = list(sample.owners)
    links = dict(owners[participant].links)
    links[name] = replace(links[name], **changes)
    owners[participant] = replace(owners[participant], links=links)
    return replace(sample, owners=tuple(owners))


def test_pre_dispatch_source_and_post_action_target_are_separate(policy):
    assert check(policy) is None
    assert check(policy, samples(policy, after=True), context(policy, "POST_ACTION")) is None
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, samples(policy, after=True))
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, samples(policy), context(policy, "POST_ACTION"))


@pytest.mark.parametrize("field,value", [
    ("action_id", "other-action"), ("attempt_id", "other-attempt"), ("producer_id", "other-producer"),
    ("evaluator_revision", "other-evaluator"), ("frame_id", "other-frame"), ("policy_digest", "e" * 64),
    ("catalog_digest", "e" * 64), ("bindings_digest", "e" * 64), ("object_ref", "other-object"),
    ("object_origin_id", "grasp-frame"), ("object_pose", None), ("owners", ()),
])
def test_partial_or_differently_bound_samples_fail(policy, field, value):
    first, second = samples(policy)
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, (first, replace(second, **{field: value})))


@pytest.mark.parametrize("field,value", [("journal_id", "other-journal"), ("owner_session_id", "other-session"),
    ("model_digest", "f" * 64), ("calibration_revision", "other-cal"), ("transform_revision", "other-tf"),
    ("gripper_state", "UNKNOWN"), ("held_state", "UNKNOWN")])
def test_other_participants_are_checked_too(policy, field, value):
    first, second = samples(policy)
    owners = (second.owners[0], replace(second.owners[1], **{field: value}))
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, (first, replace(second, owners=owners)))


def test_missing_visual_only_link_and_unknown_velocities_are_not_filled(policy):
    first, second = samples(policy)
    links = dict(second.owners[1].links)
    del links["end_effector_link"]
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, (first, replace(second, owners=(second.owners[0], replace(second.owners[1], links=links)))))
    for field in ("linear_velocity_m_s", "angular_velocity_rad_s"):
        with pytest.raises(api().PhysicalEvidenceRejected):
            check(policy, (first, change_link(second, participant=1, **{field: None})))


def test_boundary_contact_and_vector_speed_fail(policy):
    first, second = samples(policy)
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, (first, change_link(second, bounds=Bounds3((.11, 0, .1), (.2, .05, .2)))))
    assert check(policy, (first, change_link(second, bounds=Bounds3((.110001, 0, .1), (.2, .05, .2))))) is None
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, (first, change_link(second, linear_velocity_m_s=(.008, .008, 0))))


def test_orientation_uses_object_origin_and_accepts_equivalent_quaternion_sign(policy):
    first, second = samples(policy)
    assert check(policy, (first, replace(second, object_pose=PhysicalPose((0, 0, .2), (0, 0, 0, -1))))) is None
    for pose in (PhysicalPose((0, 0, .21), (0, 0, 0, 1)),
                 PhysicalPose((0, 0, .2), (math.sin(.05), 0, 0, math.cos(.05)))):
        with pytest.raises(api().PhysicalEvidenceRejected):
            check(policy, (first, replace(second, object_pose=pose)))


def test_nearly_unit_measured_quaternion_does_not_hide_orientation_error(policy):
    strict = policy.model_copy(update={"orientation_tolerance_rad": 0.})
    first, second = samples(strict)
    norm = math.sqrt(1 + 9e-7)
    tilted = PhysicalPose((0, 0, .2), (norm * math.sin(.0005), 0, 0, norm * math.cos(.0005)))
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(strict, (first, replace(second, object_pose=tilted)))
    assert check(strict, (first, replace(second, object_pose=PhysicalPose((0, 0, .2), (0, 0, 0, norm))))) is None


def test_participant_cannot_use_a_manufactured_subset_descriptor(policy):
    from rosy.world.state.projections.omx_geometry import ArmGeometry
    original = policy.participants[0]
    with pytest.raises(ValueError):
        api().TransferParticipant(**{**dict(original), "geometry": ArmGeometry(original.geometry.model_digest, frozenset({"link1"}))})


def test_two_distinct_ordered_wholly_fresh_samples_after_durable_boundary(policy):
    first, second = samples(policy)
    cases = [(first,), (second, first), (first, first), (first, replace(second, evidence_id=first.evidence_id)),
             (first, replace(second, sequence=first.sequence)),
             (first, replace(second, object_observed_at_ns=BASE)),
             (first, replace(second, object_observed_at_ns=BASE + 100_000_001)),
             (first, replace(second, object_observed_at_ns=BASE + 350_000_001))]
    for observations in cases:
        with pytest.raises(api().PhysicalEvidenceRejected):
            check(policy, observations)
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, now_ns=BASE + 700_000_000)
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, authenticated_producer_id="proposer")
    changed = context(policy).model_copy(update={"not_before_ns": BASE + 200_000_000})
    with pytest.raises(api().PhysicalEvidenceRejected):
        check(policy, ctx=changed)


def test_policy_and_context_are_closed_immutable_and_digest_covers_thresholds(policy):
    assert policy.digest != policy.model_copy(update={"zone_margin_m": .02}).digest
    with pytest.raises(ValueError):
        policy.zone_margin_m = .1
    for changes in ({"zones": ()}, {"participants": ()}, {"primary": ("w", "missing")},
                    {"zone_margin_m": float("nan")}, {"max_age_ns": True}, {"min_separation_ns": 0},
                    {"max_age_ns": 10, "min_separation_ns": 100}, {"outside_zone": True}):
        with pytest.raises(ValueError):
            api().PhysicalTransferPolicy(**{**dict(policy), **changes})
