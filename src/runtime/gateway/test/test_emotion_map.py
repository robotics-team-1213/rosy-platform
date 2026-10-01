"""D-385: the mode chooses the robot's face — policy table, ROS-free."""

from __future__ import annotations

import pytest

from core_features.command.emotion_map import emotion_for


@pytest.mark.parametrize("mode,face", [
    ("IDLE", "basic"),
    ("MANUAL", "interest"),
    ("NAVIGATION", "happy"),
    ("DOCKING", "fun"),
    ("EMERGENCY", "sad"),
])
def test_every_mode_has_a_calm_face(mode, face):
    assert emotion_for(mode) == face


@pytest.mark.parametrize("nav,face", [
    ("BLOCKED", "bored"), ("FAILED", "bored"),
    ("NAVIGATING", "happy"), ("PLANNING", "happy"), ("ARRIVED", "happy"),
    (None, "happy"),
])
def test_a_stuck_navigation_waits_with_a_bored_face(nav, face):
    assert emotion_for("NAVIGATION", nav) == face


@pytest.mark.parametrize("mode", [None, "DRIVE", "", 7, True])
def test_an_unknown_mode_keeps_the_current_face(mode):
    assert emotion_for(mode) is None


# --- idle boredom ---------------------------------------------------------------


@pytest.mark.parametrize("idle_s,face", [
    (0.0, "basic"), (299.9, "basic"),
    (300.0, "bored"), (600.0, "bored"), (3600.0, "bored"),
])
def test_a_long_idle_gets_bored(idle_s, face):
    assert emotion_for("IDLE", idle_seconds=idle_s) == face


@pytest.mark.parametrize("mode", ["MANUAL", "NAVIGATION", "DOCKING", "EMERGENCY"])
def test_boredom_never_leaks_into_operating_modes(mode):
    from core_features.command.emotion_map import EMOTION_BY_MODE
    assert emotion_for(mode, idle_seconds=99999.0) == EMOTION_BY_MODE[mode]


def test_every_name_is_one_the_emotion_node_knows():
    # The GIF filenames are the set_emotion vocabulary; a typo here would be a
    # silent no-op on the robot (the node rejects unknown names).
    known = {"hello", "basic", "angry", "bored", "fun", "happy", "interest", "sad"}
    from core_features.command.emotion_map import EMOTION_BY_MODE, NAV_STUCK_EMOTION
    assert set(EMOTION_BY_MODE.values()) <= known
    assert NAV_STUCK_EMOTION in known
