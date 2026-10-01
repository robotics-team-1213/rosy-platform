from __future__ import annotations

import pytest

from fleet.ai.model_tool_catalog import (
    MODEL_TOOL_CATALOG, ToolEffectClass, provider_tool_schemas,
)


def test_provider_projection_contains_only_feedback_tools_with_closed_schemas():
    tools = provider_tool_schemas()

    assert [tool["name"] for tool in tools] == [
        "get_mission_status", "propose_replan",
    ]
    assert tools[0]["parameters"] == {
        "type": "object", "properties": {}, "additionalProperties": False,
    }
    assert tools[1]["parameters"]["required"] == ["based_on_event_id", "rationale"]
    assert tools[1]["parameters"]["additionalProperties"] is False


def test_catalog_classifies_existing_tools_without_actuation():
    assert MODEL_TOOL_CATALOG["get_mission_status"].effect_class is ToolEffectClass.READ_ONLY
    assert MODEL_TOOL_CATALOG["propose_replan"].effect_class is ToolEffectClass.CANDIDATE_WRITING
    assert MODEL_TOOL_CATALOG["propose_pick_place"].effect_class is ToolEffectClass.CANDIDATE_WRITING
    assert all(entry.device_action_api is False for entry in MODEL_TOOL_CATALOG.values())


@pytest.mark.parametrize("name", [
    "move", "move_robot", "gripper", "open_gripper", "cancel_action",
    "stop", "emergency_stop", "e_stop", "rearm", "submit_action",
    "openapi_operation",
])
def test_low_level_actuation_and_dynamic_tools_are_not_catalogued(name):
    assert name not in MODEL_TOOL_CATALOG
