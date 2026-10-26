"""Validate the explicit native simulation pose binding before Fleet composition."""


def validate_simulation_pose_binding(map_pose_port, deployment_profile, binding) -> bool:
    simulation_pose = bool(getattr(map_pose_port, "simulation_only", False))
    if simulation_pose:
        if deployment_profile != "simulation" or binding is None:
            raise ValueError("native SIM pose requires simulation deployment and explicit runner binding")
        if not callable(getattr(map_pose_port, "validate_simulation_binding", None)):
            raise ValueError("native SIM pose requires a validated runner binding")
        map_pose_port.validate_simulation_binding(binding)
    elif binding is not None:
        raise ValueError("runner SIM binding requires an explicit native SIM pose port")
    return simulation_pose
