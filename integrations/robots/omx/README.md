# ROSY OMX Robot Integration

This package binds the ROS-free `pallet.transfer` Skill to the existing OMX
analytic cell planner and the local `PickPlaceRunner` execution owner.

`ActionRunner` validates the Fleet grant, peer, capability revision, stop fence,
and existing Action journal before it calls this provider. The provider projects
the grant into the Skill contract, resolves grasp geometry from the accepted
recipe revision, plans against the accepted Cell profile and a fresh joint-state
snapshot, and adapts the resulting plan to the existing four-phase runner.
Cancellation remains delegated to that runner's exact active goal.

The module has no direct ROS imports. The `omx_adapter` package supplies the
existing device-side planner/runtime types in the ROS workspace; CI builds and
installs this integration wheel alongside the manipulation Skill wheel before
consumer tests. The integration does not establish independent destination
pose evidence or ROS-SIM acceptance by itself.

`mixed_reach.py` answers the mixed palletizing planner's injected reach question
(`mixed_cell.Reach`, D-781 §3 rule 4) with the same analytic top-down IK and a
planning profile's limits, per arm base (`IkReach`, `ik_reach_from_profile`). It
checks single poses only (no segments, timing or collisions) and uses the
simulation profile's nominal limits. The palletizing process does not import it;
a composition passes it in. G1 SIM use and findings:
`docs/validation/bimanual-g1-sim-2026-10-17/README.md`.

## CORE and LeRobot

The optional HTTP-only `rosy_omx` Robot adapter connects LeRobot recording and
inference to CORE's installed OMX policy session. See [setup and limits](docs/CORE_LEROBOT.md).
