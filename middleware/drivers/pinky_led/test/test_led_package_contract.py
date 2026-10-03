"""ROS-free LED package surface (D-73). Does not start the rclpy node."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_entry_point_declares_led_server_main():
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "led_server=led.led_server:main" in setup
    server = (ROOT / "led" / "led_server.py").read_text(encoding="utf-8")
    assert "def main(" in server
    assert "LedServiceServer" in server


def test_package_xml_names_the_led_package():
    text = (ROOT / "package.xml").read_text(encoding="utf-8")
    assert "<name>led</name>" in text
    assert "interfaces" in text
