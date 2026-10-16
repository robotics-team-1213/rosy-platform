"""Prepare an offline OMX startup-description candidate; never start hardware.

The pinned driver still writes command buffers on activation and exposes write
services. This transformation does not make the driver read-only or authorize
its deployment. It removes the explicit GPIO initialization register writes and
the driver's default torque-enabling selection for subsequent runtime review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

PLUGIN = "dynamixel_hardware_interface/DynamixelHardware"
METADATA = frozenset({"ID", "type", "model_num", "comm_id", "[unit info]"})


def parameters(element):
    result = {}
    for item in element.findall("param"):
        name = item.get("name")
        if not name or name in result or item.text is None:
            raise ValueError("parameters need unique names and explicit values")
        result[name] = item
    return result


def prepare(text):
    if (len(text.encode()) > 2_000_000 or "<!DOCTYPE" in text.upper()
            or "<!ENTITY" in text.upper() or "${" in text or "$(" in text):
        raise ValueError("a bounded, expanded XML description is required")
    root = ET.fromstring(text)
    if root.tag != "robot" or any("xacro}" in item.tag for item in root.iter()):
        raise ValueError("expected expanded robot XML")
    systems = list(root.iter("ros2_control"))
    if len(systems) != 1 or systems[0].get("type") != "system":
        raise ValueError("expected exactly one OMX hardware system")
    control = systems[0]
    hardware = control.findall("hardware")
    if (len(hardware) != 1 or len(hardware[0].findall("plugin")) != 1
            or hardware[0].findtext("plugin") != PLUGIN):
        raise ValueError("expected the pinned Dynamixel hardware plugin")
    hardware = hardware[0]
    params = parameters(hardware)
    disable = params.get("disable_torque_at_init")
    if disable is None:
        disable = ET.SubElement(hardware, "param", name="disable_torque_at_init")
    disable.text = "false"  # Existing enabled torque must fail initialization, not be switched off.
    gpios = control.findall("gpio")
    ids = []
    removed = 0
    for gpio in gpios:
        params = parameters(gpio)
        if "ID" not in params or "type" not in params or params["type"].text != "dxl":
            raise ValueError("expected only six explicit follower motors")
        ids.append(params["ID"].text)
        for name, item in params.items():
            if name not in METADATA and name not in {"Torque Enable", "Reboot"}:
                gpio.remove(item)
                removed += 1
        for name in ("Torque Enable", "Reboot"):
            item = params.get(name)
            if item is None:
                item = ET.SubElement(gpio, "param", name=name)
            item.text = "0"
    if ids != [str(value) for value in range(11, 17)]:
        raise ValueError("expected ordered, unique follower IDs 11..16")
    output = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode()
    return output, {
        "schema": "rosy.omx-startup-description-candidate.v1",
        "scope": "offline_candidate_not_accepted_runtime",
        "motion_admitted": False, "runtime_started": False,
        "removed_register_parameters": removed,
        "unverified": ["driver_activation_writes", "write_service_authority", "ros_compatibility",
                       "physical_limits", "independent_stop", "calibration", "owner_binding"],
    }


def write_candidate(source, output):
    source, output = Path(source), Path(output)
    if source.resolve().is_relative_to(output.resolve()):
        raise ValueError("output must not contain the input")
    original = source.read_bytes()
    prepared, receipt = prepare(original.decode("utf-8-sig"))
    output.mkdir()  # Refuse overwrites and never modify source or device configuration.
    target = output / "description.urdf"
    target.write_bytes(prepared.encode())
    if source.read_bytes() != original:
        raise RuntimeError("input changed while preparing candidate; output is incomplete")
    receipt.update(source_sha256=hashlib.sha256(original).hexdigest(),
                   description_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        receipt = write_candidate(args.source, args.output)
    except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
        parser.exit(2, f"Candidate not created: {error}\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
