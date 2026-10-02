"""Small launch-argument helpers for gz_multi.launch.py (kept apart for the D-362 line budget)."""

from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration


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
