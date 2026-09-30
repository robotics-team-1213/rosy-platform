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


def test_every_name_is_one_the_emotion_node_knows():
    # The GIF filenames are the set_emotion vocabulary; a typo here would be a
    # silent no-op on the robot (the node rejects unknown names).
    known = {"hello", "basic", "angry", "bored", "fun", "happy", "interest", "sad"}
    from core_features.command.emotion_map import EMOTION_BY_MODE, NAV_STUCK_EMOTION
    assert set(EMOTION_BY_MODE.values()) <= known
    assert NAV_STUCK_EMOTION in known
