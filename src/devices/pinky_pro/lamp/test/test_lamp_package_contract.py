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


def test_the_lamp_test_helper_is_built_with_the_node_and_touches_only_the_lamp():
    # D-247 6: rosy-hw-test.service runs lib/lamp_control/lamp_selftest as root.
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "add_executable(lamp_selftest src/lamp_selftest.c)" in cmake
    assert "target_link_libraries(lamp_selftest ws2811 m)" in cmake
    install = cmake[cmake.index("install(TARGETS"):]
    assert "lamp_selftest" in install[:install.index(")")]
    source = (ROOT / "src" / "lamp_selftest.c").read_text(encoding="utf-8")
    for fragment in (".gpionum = LAMP_GPIO", "#define LAMP_GPIO 19", "#define LAMP_COUNT 8",
                     "WS2811_STRIP_GBR", "#define LAMP_DMA 10", "ws2811_fini(&lamp)", "fill(&lamp, 0)"):
        assert fragment in source, fragment
    assert "rclcpp" not in source and "main_node" not in source.split("*/", 1)[1]
