"""Small launch-argument helpers for gz_multi.launch.py (kept apart for the D-362 line budget)."""

import os
import xml.etree.ElementTree as ET

from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration

#: The IMU publishes at 100 Hz; a longer physics step would drop its samples.
MAX_PHYSICS_STEP_S = 0.01


def optional_float(raw: str):
    text = (raw or "").strip()
    if text == "":
        return None
    return float(text)


def nav_composition_argument() -> DeclareLaunchArgument:
    return DeclareLaunchArgument("nav_composition", default_value="false", choices=["true", "false"],
                                 description="mode:=nav: Nav2 in one container per robot (device layout)")


def apply_nav_composition(nav_args: dict, context) -> None:
    """Opt-in (D-395 S2): one Nav2 container per robot, as on the device (hardware.launch.py).
    Four uncomposed stacks starved the S2 host to RTF 0.02. Default stays uncomposed."""
    if LaunchConfiguration("nav_composition").perform(context).lower() in ("true", "1"):
        nav_args["use_composition"] = "True"


def sim_speed_arguments() -> list:
    """Sim-only speed knobs (D-395 S2 rerun). Empty / false keeps the world and renderer as they are."""
    return [
        DeclareLaunchArgument("physics_step", default_value="",
                              description="physics max_step_size in s (e.g. 0.005); empty: the world's"),
        DeclareLaunchArgument("real_time_factor", default_value="",
                              description="target real-time factor; empty: the world's (1 if none)"),
        DeclareLaunchArgument("gpu", default_value="false", choices=["true", "false"],
                              description="WSL: render sensors on the GPU (GALLIUM_DRIVER=d3d12)"),
    ]


def physics_world(world_path: str, step, rtf, out_dir: str) -> str:
    """The world with its <physics> step / real-time factor overridden, written to `out_dir`.

    Set in the SDF before Gazebo loads it, not through `/world/<w>/set_physics` at run time:
    that service takes a whole gz.msgs.Physics, so an unset field arrives as 0. Mesh URIs are
    model://, so the copy resolves the same as the original."""
    if step is None and rtf is None:
        return world_path
    if step is not None and not 0. < step <= MAX_PHYSICS_STEP_S:
        raise ValueError(f"physics_step {step} outside (0, {MAX_PHYSICS_STEP_S}]")
    if rtf is not None and rtf <= 0.:
        raise ValueError(f"real_time_factor {rtf} must be > 0")
    tree = ET.parse(world_path)
    world = tree.getroot().find("world")
    physics = world.find("physics")
    if physics is None:
        physics = ET.SubElement(world, "physics", name="sim_speed", type="ode")
    for tag, value in (("max_step_size", step), ("real_time_factor", rtf)):
        if value is not None:
            node = physics.find(tag)
            (node if node is not None else ET.SubElement(physics, tag)).text = repr(value)
    if physics.find("real_time_factor") is None:
        ET.SubElement(physics, "real_time_factor").text = "1.0"
    path = os.path.join(out_dir, "physics_" + os.path.basename(world_path))
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def apply_sim_speed(world_path: str, context, out_dir: str) -> tuple:
    """(world path to load, actions to put before the Gazebo server)."""
    def arg(name):
        return LaunchConfiguration(name).perform(context)
    path = physics_world(world_path, optional_float(arg("physics_step")), optional_float(arg("real_time_factor")),
                         out_dir)
    # Mesa in WSL defaults to llvmpipe (CPU); d3d12 is the GPU behind /dev/dxg. Sim only: the
    # sensors, their rates and samples are unchanged, only where ogre2 renders them.
    env = [SetEnvironmentVariable("GALLIUM_DRIVER", "d3d12")] if arg("gpu").lower() in ("true", "1") else []
    return path, env
