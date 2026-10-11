"""D-630 grouping keeps legacy imports and monkeypatch state on the real module."""

import importlib
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[1] / "rosy_situation"


def test_stuck_and_traffic_analyzers_share_the_existing_classes():
    assert (PACKAGE / "analyzers/stuck_scene.py").is_file()
    assert (PACKAGE / "analyzers/traffic_watch.py").is_file()
    legacy = importlib.import_module("rosy_situation.analyzers")
    stuck = importlib.import_module("rosy_situation.analyzers.stuck_scene")
    traffic = importlib.import_module("rosy_situation.analyzers.traffic_watch")
    assert legacy.Analyzer is stuck.Analyzer
    assert stuck.TrafficWatch is traffic.TrafficWatch


@pytest.mark.parametrize("legacy,target,symbol", [
    ("deadlock", "analyzers.traffic_watch", "TrafficWatch"),
    ("incident_context", "incidents.context", "ContextDraft"),
    ("vlm", "incidents.vision", "Vlm"),
])
def test_legacy_module_alias_preserves_objects_and_mutations(legacy, target, symbol, monkeypatch):
    assert (PACKAGE / (target.replace(".", "/") + ".py")).is_file()
    old = importlib.import_module("rosy_situation." + legacy)
    implementation = importlib.import_module("rosy_situation." + target)
    assert old is implementation
    assert getattr(old, symbol) is getattr(implementation, symbol)
    marker = object()
    monkeypatch.setattr(old, "_layout_test_marker", marker, raising=False)
    assert implementation._layout_test_marker is marker
