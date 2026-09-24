"""Vision handoff: JPEG preview only. NITROS is not a Core dependency."""

from pathlib import Path

import pytest

from core_features.vision import (
    PREVIEW_TOPIC,
    TransportUnavailable,
    accept_preview,
)
from core_features.vision.transport import PROVIDERS, select

ROOT = Path(__file__).resolve().parents[3]
BRIDGE = ROOT / "core" / "core" / "core" / "bridge" / "ros_bridge.py"
ROAD = ROOT / "core" / "control" / "control" / "road_observer_node.py"
CORE_PKG = ROOT / "core" / "core" / "package.xml"


def test_standard_jpeg_is_the_only_wired_transport():
    meta = accept_preview("jpeg; source=front; width=640; height=480")
    assert meta["source"] == "FRONT"
    assert meta["width"] == 640
    for name in PROVIDERS:
        if name == "standard_ros_image":
            assert select(name) == name
        else:
            with pytest.raises(TransportUnavailable):
                select(name)


def test_preview_topic_matches_the_camera_and_the_bridge():
    assert PREVIEW_TOPIC == "camera/preview/compressed"
    assert PREVIEW_TOPIC in ROAD.read_text(encoding="utf-8")
    assert "PREVIEW_TOPIC" in BRIDGE.read_text(encoding="utf-8")
    assert "nitros" not in CORE_PKG.read_text(encoding="utf-8").lower()
    assert "isaac" not in CORE_PKG.read_text(encoding="utf-8").lower()
