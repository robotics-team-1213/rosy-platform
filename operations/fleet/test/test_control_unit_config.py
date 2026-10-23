"""Static control-unit ownership must be valid before any delegation is opened."""

import copy

import pytest


def topology():
    return {
        "revision": "lab-1",
        "units": [
            {"id": "R", "resources": []},
            {"id": "A", "parent": "R", "resources": ["robot:a"]},
            {"id": "B", "parent": "R", "resources": ["robot:b"]},
            {"id": "A1", "parent": "A", "resources": ["robot:a1"]},
        ],
    }


def load(document):
    from fleet.server.control_unit_config import ControlUnitTopology
    return ControlUnitTopology.from_mapping(document)


def test_independent_and_nested_ownership():
    root = load({"revision": "standalone", "units": [{"id": "A", "resources": ["robot:a"]}]})
    assert root.unit("A").parent is None
    nested = load(topology())
    assert nested.revision == "lab-1"
    assert nested.child("R", "A").unit_id == "A"
    assert nested.next_hop("R", "A1") == "A"
    assert nested.next_hop("A", "A1") == "A1"
    assert nested.unit("A1").resources == frozenset({"robot:a1"})


@pytest.mark.parametrize("change", [
    lambda d: d["units"].append({"id": "A"}),
    lambda d: d["units"][0].update(parent="R"),
    lambda d: d["units"][0].update(parent="A1"),
    lambda d: d["units"][1].update(parent="missing"),
    lambda d: d["units"][2].update(resources=["robot:a"]),
    lambda d: d["units"][1].update(resources=["robot:a", "robot:a"]),
    lambda d: d["units"].append({"id": "A2", "parent": "A1"}),
    lambda d: d["units"][1].update(parent=["R", "B"]),
    lambda d: d["units"][1].update(id=" A"),
    lambda d: d.update(revision=True),
    lambda d: d["units"][1].update(parent="R", endpoint="http://untrusted"),
    lambda d: d.update(units=[]),
])
def test_rejects_invalid_or_ambiguous_configuration(change):
    document = copy.deepcopy(topology())
    change(document)
    with pytest.raises(ValueError):
        load(document)


def test_unrelated_tree_and_grandchild_are_not_direct_peers():
    document = topology()
    document["units"].append({"id": "other", "resources": []})
    tree = load(document)
    for call in [lambda: tree.child("R", "A1"), lambda: tree.next_hop("A", "B"),
                 lambda: tree.next_hop("R", "other"), lambda: tree.unit("unknown")]:
        with pytest.raises(ValueError):
            call()


def test_source_mutation_does_not_change_approved_scope():
    document = topology()
    tree = load(document)
    document["units"][1]["resources"].append("robot:other")
    assert tree.unit("A").resources == frozenset({"robot:a"})
