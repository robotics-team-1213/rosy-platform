"""Optional intent epochs remain strict and survive interpretation unchanged."""
import pytest

from core_common.intent import IntentError, interpret, request_schema

BOOT = "10000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize("document", [
    {"do": "navigate", "x": 1.0, "y": 2.0},
    {"do": "navigate", "waypoint": "loading"},
    {"do": "home"},
])
def test_navigation_intent_forwards_the_caller_epoch_without_replacing_it(document):
    original = {**document, "expected_boot_id": BOOT, "expected_owner_generation": 0}
    call, = interpret(original)
    assert call.body == {key: value for key, value in original.items() if key != "do"}
    assert original == {**document, "expected_boot_id": BOOT, "expected_owner_generation": 0}


@pytest.mark.parametrize("verb", ["navigate", "home"])
@pytest.mark.parametrize(("field", "value"), [
    ("expected_boot_id", None), ("expected_boot_id", True),
    ("expected_boot_id", "not-a-uuid"), ("expected_owner_generation", None),
    ("expected_owner_generation", True), ("expected_owner_generation", -1),
    ("expected_owner_generation", 1.0), ("expected_owner_generation", "1"),
])
def test_navigation_intent_validates_supplied_epoch_fields(verb, field, value):
    document = {"do": verb, "expected_boot_id": BOOT, "expected_owner_generation": 7}
    if verb == "navigate":
        document.update(x=0, y=0)
    document[field] = value
    with pytest.raises(IntentError) as caught:
        interpret(document)
    assert caught.value.code == "INVALID_FIELD_TYPE"


def test_navigation_epoch_grammar_stays_optional_and_navigation_only():
    variants = request_schema()["oneOf"][0]["oneOf"]
    for variant in variants:
        navigation = variant["properties"]["do"]["const"] in {"navigate", "home"}
        for field in ("expected_boot_id", "expected_owner_generation"):
            assert (field in variant["properties"]) == navigation
            assert field not in variant["required"]
        if navigation:
            assert variant["properties"]["expected_boot_id"] == {"type": "string", "format": "uuid"}
            assert variant["properties"]["expected_owner_generation"] == {"type": "integer", "minimum": 0}
    with pytest.raises(IntentError) as caught:
        interpret({"do": "cancel", "expected_owner_generation": 7})
    assert caught.value.code == "UNKNOWN_FIELD"
