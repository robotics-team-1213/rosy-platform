"""Initialization artifact preparation never starts a controller or admits motion."""
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

_spec = importlib.util.spec_from_file_location(
    "preserved_description", Path(__file__).parents[1] / "deploy/robot/omx/preserved_description.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


def description():
    robot = ET.Element("robot", name="test_omx")
    control = ET.SubElement(robot, "ros2_control", name="OMXFSystem", type="system")
    hardware = ET.SubElement(control, "hardware")
    ET.SubElement(hardware, "plugin").text = "dynamixel_hardware_interface/DynamixelHardware"
    ET.SubElement(hardware, "param", name="disable_torque_at_init").text = "true"
    ET.SubElement(hardware, "param", name="port_name").text = "/dev/serial/by-id/test-follower"
    for motor_id in range(11, 17):
        gpio = ET.SubElement(control, "gpio", name=f"dxl{motor_id}")
        for name, value in {"ID": str(motor_id), "type": "dxl", "Operating Mode": "3",
                            "Position P Gain": "1000", "Current Limit": "1750",
                            "Torque Enable": "1", "Reboot": "1"}.items():
            ET.SubElement(gpio, "param", name=name).text = value
        ET.SubElement(gpio, "command_interface", name="Goal Position")
        ET.SubElement(gpio, "state_interface", name="Present Position")
    return robot


def test_description_candidate_removes_initial_register_writes_and_implicit_torque():
    original = ET.tostring(description(), encoding="unicode")
    output, receipt = _module.prepare(original)
    root = ET.fromstring(output)
    control = root.find("ros2_control")
    assert control.find("hardware/param[@name='disable_torque_at_init']").text == "false"
    for gpio in control.findall("gpio"):
        params = {item.attrib["name"]: item.text for item in gpio.findall("param")}
        assert params == {"ID": gpio.attrib["name"][3:], "type": "dxl", "Torque Enable": "0", "Reboot": "0"}
        assert gpio.find("command_interface").attrib["name"] == "Goal Position"
    assert receipt["removed_register_parameters"] == 18
    assert receipt["motion_admitted"] is False
    assert receipt["runtime_started"] is False
    assert _module.prepare(output)[0] == output
    assert ET.fromstring(original).find(".//param[@name='Operating Mode']") is not None


@pytest.mark.parametrize("invalid", ["plugin", "duplicate_id", "missing_motor", "duplicate_param", "xacro", "second_system"])
def test_unverified_or_ambiguous_description_is_rejected(invalid):
    root = description()
    control = root.find("ros2_control")
    if invalid == "plugin":
        control.find("hardware/plugin").text = "mock_components/GenericSystem"
    elif invalid == "duplicate_id":
        control.findall("gpio")[1].find("param[@name='ID']").text = "11"
    elif invalid == "missing_motor":
        control.remove(control.findall("gpio")[-1])
    elif invalid == "duplicate_param":
        ET.SubElement(control.find("gpio"), "param", name="ID").text = "11"
    elif invalid == "xacro":
        ET.SubElement(root, "{http://www.ros.org/wiki/xacro}if", value="true")
    else:
        ET.SubElement(root, "ros2_control", name="other", type="system")
    with pytest.raises(ValueError):
        _module.prepare(ET.tostring(root, encoding="unicode"))


def test_artifacts_preserve_input_and_refuse_existing_output(tmp_path):
    source = tmp_path / "input.urdf"
    content = ET.tostring(description())
    source.write_bytes(content)
    output = tmp_path / "candidate"
    receipt = _module.write_candidate(source, output)
    assert source.read_bytes() == content
    assert (output / "description.urdf").is_file()
    assert (output / "receipt.json").is_file()
    assert receipt["runtime_started"] is False
    with pytest.raises(FileExistsError):
        _module.write_candidate(source, output)
