"""Shared resource identities have no dependency on a transaction or decision owner."""
from importlib import import_module

import pytest


def normalizer():
    try:
        return import_module("core_common.resource_keys").normalize_resources
    except ModuleNotFoundError:
        pytest.fail("shared resource-key contract is missing")


def test_all_resource_kinds_are_typed_deduplicated_and_canonical():
    kinds = ("robot", "workcell", "object", "pallet", "station", "arm", "zone")
    values = [(kind, "scope.id") for kind in kinds]
    assert normalizer()(iter(values + values)) == sorted((kind, "scope.id", f"{kind}:scope.id") for kind in kinds)


def test_resource_identifiers_keep_the_existing_exact_length_boundary():
    assert normalizer()([("arm", "a" * 128)]) == [("arm", "a" * 128, "arm:" + "a" * 128)]


@pytest.mark.parametrize("values", [[], [("cargo", "a")], [("arm", "bad/path")], [("arm", "a" * 129)], [("arm", True)]])
def test_invalid_resource_keys_cannot_enter_the_shared_claim_namespace(values):
    with pytest.raises(ValueError):
        normalizer()(values)
