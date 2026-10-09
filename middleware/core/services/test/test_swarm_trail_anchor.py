"""D-581: a trail follower accepts a Fleet-anchored odom stream only when it is meant for it."""

from __future__ import annotations

from core_common.protocol.schemas import PoseSample
from core_features.swarm import ReferencePose, SwarmManager
from test_swarm import CAPABLE
from test_swarm_trail import Rig


class AnchorRig(Rig):
    """The follower has no map pose (motor mode): its reported pose is odom, its odom is live."""

    def __init__(self):
        super().__init__()
        self.pose = (5.0, 5.0, 0.0, "odom", 0.0)
        self.odom = (0.0, 0.0, 0.0, 0.02)
        self.swarm = SwarmManager(
            self.events, self.state, self.nav, self.safety, CAPABLE, clock=self.clock,
            map_id_provider=lambda: self.state.map_id, robot_id="rosy_01",
            pose_provider=lambda: self.pose, twist_sink=self.sent.append,
            obstacle_gap=lambda v, w, now: self.gap(v, w, now), odom_provider=lambda: self.odom)

    def held(self, reason):
        """The trail state shows no reason before it is seeded; the hold event does."""
        hold = ("swarm.hold", {"reason": reason, "formation": "follow:rosy_02@0.50/0.00"})
        return hold in self.events.published

    def anchored(self, x, y=0.0, yaw=0.0, for_robot_id="rosy_01", anchor="fleet", map_id="site"):
        self.swarm.on_reference_pose(ReferencePose(
            "rosy_02", x, y, yaw, frame="odom", map_id=map_id, anchor=anchor,
            for_robot_id=for_robot_id))


def test_a_fleet_anchored_sample_for_this_robot_drives_in_odom():
    rig = AnchorRig()
    rig.follow()
    for k in range(1, 30):
        rig.anchored(0.5 + 0.03 * k)
        twist = rig.step()
    assert twist[0] > 0.1 and abs(twist[1]) < 1e-6
    trail = rig.swarm.state_payload()["trail"]
    assert trail["anchor"] == "fleet" and trail["hold_reason"] is None


def test_an_anchored_sample_for_another_robot_holds():
    rig = AnchorRig()
    rig.follow()
    rig.anchored(1.0, for_robot_id="rosy_03")
    assert rig.step() is None
    assert rig.held("reference_anchor_invalid")
    assert rig.swarm.state_payload()["trail"] is None    # never seeded from it


def test_a_plain_leader_odom_sample_is_still_refused():
    rig = AnchorRig()
    rig.follow()
    rig.leader(1.0, frame="odom")
    assert rig.step() is None
    assert rig.held("reference_frame_not_map")


def test_the_own_odom_must_be_fresh():
    rig = AnchorRig()
    rig.follow()
    rig.anchored(1.0)
    rig.odom = (0.0, 0.0, 0.0, 0.6)
    assert rig.step() is None and rig.hold_reason() == "own_pose_stale"
    rig.odom = None
    assert rig.step() is None and rig.hold_reason() == "own_pose_stale"


def test_a_map_sample_after_an_anchored_trail_latches_frame_changed():
    rig = AnchorRig()
    rig.pose = (0.0, 0.0, 0.0, "map", 0.0)       # even with a map pose, frames never mix
    rig.follow()
    rig.anchored(1.0)
    assert rig.step()[0] > 0
    rig.leader(1.05)
    assert rig.step() is None and rig.hold_reason() == "reference_frame_changed"
    rig.anchored(1.1)                              # latched until a new follow
    assert rig.step() is None and rig.hold_reason() == "reference_frame_changed"
    assert ("swarm.hold", {"reason": "reference_frame_changed",
                           "formation": "follow:rosy_02@0.50/0.00"}) in rig.events.published


def test_the_robot_map_id_does_not_gate_an_anchored_sample():
    rig = AnchorRig()
    rig.state.set_map_id("robot_map")
    rig.follow()
    rig.anchored(1.0, map_id="site")
    assert rig.step()[0] > 0
    assert rig.swarm.state_payload()["map_mismatch"] is None


def test_the_contract_carries_the_anchor_fields():
    sample = PoseSample.model_validate({
        "robot_id": "rosy_40", "pose": {"x": 1, "y": 2, "yaw": 0}, "seq": 3, "map_id": "site",
        "frame": "odom", "anchor": "fleet", "for_robot_id": "rosy_41", "anchor_age_s": 0.4})
    assert sample.anchor == "fleet" and sample.for_robot_id == "rosy_41"
