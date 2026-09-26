"""Stage-1 loop wiring. OpenCV stays in an observation adapter, not here."""

from games.host.hold import HoldObserver
from games.host.loop import MatchHost, PlayerClient
from games.host.observer import Observer
from games.host.robots import MatchSetup, RobotEndpoint, load_match
from games.host.session import run_match

__all__ = [
    "HoldObserver",
    "MatchHost",
    "MatchSetup",
    "Observer",
    "PlayerClient",
    "RobotEndpoint",
    "load_match",
    "run_match",
]
