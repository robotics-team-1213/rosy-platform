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
