"""Shared paths for host-side robot runtime contract tests."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "robot"
NAV_LAUNCH = ROOT / "src" / "runtime" / "navigation" / "launch"
NAV_PARAMS = ROOT / "src" / "runtime" / "navigation" / "params" / "nav2_params.yaml"


def compose() -> dict:
    return yaml.safe_load((DEPLOY / "compose.yaml").read_text(encoding="utf-8"))


def board() -> dict:
    return yaml.safe_load((DEPLOY / "config" / "board.yaml").read_text(encoding="utf-8"))


def hardware_packages() -> tuple[str, ...]:
    packages = board().get("hardware_packages") or []
    return tuple(str(item) for item in packages)


def board_caps(mode: str) -> dict:
    return yaml.safe_load(
        (DEPLOY / "config" / f"capabilities.{mode}.yaml").read_text(encoding="utf-8")
    )


def board_profile(mode: str) -> dict:
    return yaml.safe_load(
        (DEPLOY / "config" / f"profile.{mode}.yaml").read_text(encoding="utf-8")
    )


#: Both in-tree naming conventions: `hardware.launch.py` and `bringup_launch.xml`.
LAUNCH_REFERENCE = re.compile(r"([A-Za-z0-9_]+(?:\.launch|_launch)\.(?:xml|py))")


def _launch_file(name: str) -> Path | None:
    """Resolve a launch file name to its in-tree path, whichever package owns it."""
    return next(iter(sorted((ROOT / "src").glob(f"*/*/launch/{name}"))), None)


def runtime_launch_closure(mode: str | None = None) -> dict[str, Path]:
    """Every launch file the deployed compose services can reach, transitively.

    With `mode`, only services that run in that mode are roots: a service is in
    scope when it declares no `profiles` (it always runs) or lists this mode.
    Without `mode`, every service is a root.

    Roots are the `ros2 launch <pkg> <file>` commands in `compose.yaml`; edges
    are launch-file names referenced from a launch file's own text, which
    covers both the XML `<include file="$(find-pkg-share ...)/launch/X">` form
    and the Python `os.path.join(share, "launch", "X")` form without needing a
    ROS environment to evaluate either.
    """
    pending: list[str] = []
    for service in compose()["services"].values():
        profiles = service.get("profiles")
        if mode is not None and profiles and mode not in profiles:
            continue
        command = service.get("command") or []
        pending.extend(part for part in command if LAUNCH_REFERENCE.fullmatch(part))

    closure: dict[str, Path] = {}
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        path = _launch_file(name)
        if path is None:
            continue
        closure[name] = path
        pending.extend(LAUNCH_REFERENCE.findall(path.read_text(encoding="utf-8")))
    return closure
