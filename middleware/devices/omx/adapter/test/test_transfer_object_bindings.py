"""An execution object selects geometry through an owner map, never a requester override."""
from dataclasses import fields
from importlib import import_module

import pytest

from omx_adapter.transfer_motion import GraspGeometry, TransferPlanRejected
from test_transfer_preflight import _catalog
from test_omx_pose_plan import kin, profile  # noqa: F401


def _bindings(catalog, objects):
    try:
        module = import_module("omx_adapter.transfer_object_bindings")
    except ModuleNotFoundError:
        pytest.fail("neutral physical object-to-geometry binding is missing")
    return module.TransferObjectBindings(catalog, objects)


def _resolve(bindings, object_ref="object-1", **changes):
    return bindings.resolve(object_ref, **{
        "catalog_digest": bindings.catalog.digest, "bindings_digest": bindings.revision, **changes})


def test_owner_object_map_selects_the_exact_registered_geometry(kin, profile):
    catalog = _catalog(kin, profile)
    bindings = _bindings(catalog, {"object-1": "g1"})
    assert _resolve(bindings) is catalog.geometries["g1"]
    assert len(bindings.revision) == 64
    assert not {"approved", "mission_id", "recipe", "pallet", "layer", "grant"} & {
        field.name for field in fields(bindings)}


def test_binding_copies_its_input_and_seals_order_independent_content(kin, profile):
    catalog = _catalog(kin, profile)
    objects = {"object-1": "g1", "object-2": "g1"}
    bindings = _bindings(catalog, objects)
    expected = _bindings(catalog, dict(reversed(list(objects.items())))).revision
    objects.clear()
    assert bindings.revision == expected
    assert _resolve(bindings) == catalog.geometries["g1"]
    with pytest.raises(TypeError):
        bindings.objects["object-1"] = "g2"


def test_object_mapping_or_catalog_changes_its_revision(kin, profile):
    geometry = GraspGeometry(0.04, 0.01, 0.03, True)
    catalog = _catalog(kin, profile, geometries={"g1": GraspGeometry(0.03, 0.01, 0.03, True), "g2": geometry})
    bindings = _bindings(catalog, {"object-1": "g1"})
    assert bindings.revision != _bindings(catalog, {"object-1": "g2"}).revision
    assert bindings.revision != _bindings(_catalog(kin, profile, carry_z=0.12), {"object-1": "g1"}).revision


@pytest.mark.parametrize("objects", [{}, {"object-1": "missing"}, {True: "g1"},
                                     {"object-1": 1}, {" object-1": "g1"}, {"object\x00id": "g1"}])
def test_invalid_or_uninstalled_object_geometry_is_not_registered(kin, profile, objects):
    with pytest.raises(ValueError):
        _bindings(_catalog(kin, profile), objects)


@pytest.mark.parametrize("changes,reason", [
    ({"catalog_digest": "0" * 64}, "CATALOG_MISMATCH"),
    ({"bindings_digest": "0" * 64}, "OBJECT_BINDINGS_MISMATCH"),
])
def test_resolution_requires_both_installed_revisions(kin, profile, changes, reason):
    bindings = _bindings(_catalog(kin, profile), {"object-1": "g1"})
    with pytest.raises(TransferPlanRejected) as failure:
        _resolve(bindings, **changes)
    assert failure.value.reason == reason


@pytest.mark.parametrize("object_ref", ["unregistered", True, ["object-1"]])
def test_arbitrary_object_identity_cannot_borrow_an_approved_geometry(kin, profile, object_ref):
    bindings = _bindings(_catalog(kin, profile), {"object-1": "g1"})
    with pytest.raises(TransferPlanRejected) as failure:
        _resolve(bindings, object_ref)
    assert failure.value.reason == "OBJECT_NOT_BOUND"
