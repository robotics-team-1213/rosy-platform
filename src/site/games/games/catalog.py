"""Named game and policy plugins. Soccer lives here as the first kind."""

from __future__ import annotations

from games.field import Field
from games.game.protocol import Game
from games.game.soccer import SoccerGame
from games.policy.heuristic import HeuristicPolicy
from games.policy.protocol import Policy

GAMES = {"soccer": SoccerGame}
POLICIES = {"heuristic": HeuristicPolicy}
OBSERVERS = frozenset({"hold", "overhead"})


def make_game(kind: str, field: Field) -> Game:
    try:
        cls = GAMES[kind]
    except KeyError as exc:
        raise ValueError(f"unknown game {kind!r}") from exc
    return cls(field)


def make_policy(
    kind: str,
    field: Field,
    *,
    speed: float = 0.08,
    angular: float = 0.40,
) -> Policy:
    try:
        cls = POLICIES[kind]
    except KeyError as exc:
        raise ValueError(f"unknown policy {kind!r}") from exc
    return cls(field, speed=speed, angular=angular)


def make_observer(kind: str, setup):
    if kind not in OBSERVERS:
        raise ValueError(f"unknown observer {kind!r}")
    if kind == "hold":
        from games.host.hold import HoldObserver

        return HoldObserver(setup.field.home_id, setup.field.away_id)
    from games.host.overhead import OverheadCamera

    return OverheadCamera(setup)
