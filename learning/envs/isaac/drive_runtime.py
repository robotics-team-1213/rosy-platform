"""Isaac-only emergency clear of graph and USD wheel drive targets."""


def force_zero_wheels(controller, wheel_drives):
    # ScriptNode output remains latched when its graph stops computing. Clear it
    # independently of graph execution, then clear the physics drive targets.
    controller.set(controller.attribute("/World/ROSYDrive/Gate.outputs:velocityCommand"), [0.0, 0.0])
    for drive in wheel_drives:
        drive.GetTargetVelocityAttr().Set(0.0)
