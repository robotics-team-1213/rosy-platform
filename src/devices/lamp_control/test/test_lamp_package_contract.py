"""ROS-free lamp driver package surface (D-73)."""

from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_package_declares_set_lamp_interface():
    package = ET.parse(ROOT / "package.xml").getroot()
    name = package.find("name")
    assert name is not None and name.text == "lamp_control"
    text = (ROOT / "src" / "main_node.cpp").read_text(encoding="utf-8")
    assert "SetLamp" in text
    assert "ws2811" in text
