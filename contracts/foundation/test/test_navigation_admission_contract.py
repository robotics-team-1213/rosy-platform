"""One canonical wire value qualifies the navigation cancellation barrier."""
from core_common.protocol import navigation_cancel, schemas


def test_navigation_admission_fence_has_a_canonical_integer_wire_version():
    assert hasattr(navigation_cancel, "NAVIGATION_ADMISSION_FENCE_VERSION")
    value = navigation_cancel.NAVIGATION_ADMISSION_FENCE_VERSION
    assert type(value) is int and value == 1
    exported = getattr(schemas, "NAVIGATION_ADMISSION_FENCE_VERSION", None)
    assert type(exported) is int and exported == value
