from pathlib import Path

from games.catalog import GAMES, OBSERVERS, POLICIES, make_game, make_observer, make_policy
from games.field import Field
from games.game import SoccerGame
from games.policy import HeuristicPolicy

PKG = Path(__file__).resolve().parents[1]


def test_catalog_builds_soccer_and_heuristic_from_names():
    field = Field()
    game = make_game("soccer", field)
    policy = make_policy("heuristic", field, speed=0.08)
    assert isinstance(game, SoccerGame)
    assert game.field is field
    assert isinstance(policy, HeuristicPolicy)
    assert policy.speed == 0.08


def test_catalog_rejects_unknown_kinds():
    field = Field()
    try:
        make_game("chess", field)
        raise AssertionError("unknown game must fail")
    except ValueError as exc:
        assert "chess" in str(exc)
    try:
        make_policy("neural", field)
        raise AssertionError("unknown policy must fail")
    except ValueError as exc:
        assert "neural" in str(exc)


def test_catalog_has_only_soccer_and_heuristic_until_field_repeats():
    """D-98/D-99: Isaac 폴더와 NeuralPolicy는 FIELD 반복 전 없다."""
    assert set(GAMES) == {"soccer"}
    assert set(POLICIES) == {"heuristic"}
    assert not (PKG / "games" / "isaac").exists()
    assert not (PKG / "games" / "policy" / "neural.py").exists()


def test_catalog_observers_are_hold_and_overhead_until_field_repeats():
    """D-97/D-109: onboard는 계단 4 전에 없다."""
    assert OBSERVERS == frozenset({"hold", "overhead"})
    assert not (PKG / "games" / "host" / "onboard.py").exists()
    try:
        make_observer("onboard", None)
        raise AssertionError("onboard observer must fail")
    except ValueError as exc:
        assert "onboard" in str(exc)
    catalog = (PKG / "games" / "catalog.py").read_text(encoding="utf-8")
    assert "import cv2" not in catalog
    assert "from cv2" not in catalog
