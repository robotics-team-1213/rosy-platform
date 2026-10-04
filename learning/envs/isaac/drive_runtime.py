"""Isaac-only emergency clear of graph and USD wheel drive targets."""

import math


def passive_caster_joints(urdf_root):
    """Prove the expected caster joints are continuous and have no actuator."""
    names = ("caster_rotate_joint", "caster_wheel_joint")
    for name in names:
        joints = [joint for joint in urdf_root.findall("joint") if joint.get("name") == name]
        if len(joints) != 1 or joints[0].get("type") != "continuous" or joints[0].find("mimic") is not None:
            raise ValueError(f"Passive continuous caster joint not proven: {name}")
        for joint in urdf_root.findall("transmission/joint"):
            if joint.get("name") == name:
                raise ValueError(f"Caster joint has a transmission: {name}")
        for joint in urdf_root.findall("ros2_control/joint"):
            if joint.get("name") == name and joint.find("command_interface") is not None:
                raise ValueError(f"Caster joint has a command interface: {name}")
    return names


def configure_passive_drive(drive):
    """Disable importer-created servos on a proven unactuated caster."""
    drive.CreateStiffnessAttr(0.0)
    drive.CreateDampingAttr(0.0)
    drive.CreateTargetVelocityAttr(0.0)
    observed = (drive.GetStiffnessAttr().Get(), drive.GetDampingAttr().Get(),
                drive.GetTargetVelocityAttr().Get())
    if any(value is None or not math.isfinite(value) or abs(value) > 1e-8 for value in observed):
        raise RuntimeError(f"Passive caster drive readback failed: {observed}")


def positive_damping(value):
    damping = float(value)
    if not math.isfinite(damping) or damping <= 0:
        raise ValueError("Wheel damping must be finite and positive")
    return damping


def configure_velocity_drive(drive, damping=None):
    """Author and verify a velocity drive before physics starts.

    An explicit gain supports measured simulator tuning. Without one, preserve
    the imported positive gain, retaining the historical fallback of 1.0.
    """
    if damping is not None:
        damping = positive_damping(damping)
    else:
        imported = drive.GetDampingAttr().Get()
        if imported is not None and not math.isfinite(imported):
            raise ValueError("Imported wheel damping must be finite")
        damping = positive_damping(imported) if imported is not None and imported > 0 else 1.0
    drive.CreateStiffnessAttr(0.0)
    drive.CreateDampingAttr(damping)
    drive.CreateTargetVelocityAttr(0.0)
    expected = (0.0, damping, 0.0)
    observed = (drive.GetStiffnessAttr().Get(), drive.GetDampingAttr().Get(),
                drive.GetTargetVelocityAttr().Get())
    if any(value is None or not math.isfinite(value) or not math.isclose(value, target, abs_tol=1e-8)
           for value, target in zip(observed, expected)):
        raise RuntimeError(f"Wheel velocity drive readback failed: expected {expected}, observed {observed}")
    return damping


def force_zero_wheels(controller, wheel_drives):
    # ScriptNode output remains latched when its graph stops computing. Clear it
    # independently of graph execution, then clear the physics drive targets.
    controller.set(controller.attribute("/World/ROSYDrive/Gate.outputs:velocityCommand"), [0.0, 0.0])
    for drive in wheel_drives:
        drive.GetTargetVelocityAttr().Set(0.0)
