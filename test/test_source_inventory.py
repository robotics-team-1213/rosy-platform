"""A truncated compare must not conceal changed paths or permit an unsafe delta."""
import copy
import importlib.util
from pathlib import Path

import pytest


BASE, HEAD, OLD_TREE, NEW_TREE = (c * 40 for c in "abcd")
ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location(
        "source_inventory", ROOT / "tools/release/source_inventory.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def entry(path, sha="e" * 40, *, mode="100644", kind="blob"):
    return {"path": path, "sha": sha, "mode": mode, "type": kind}


def responses(old=(), new=()):
    return {
        f"git/commits/{BASE}": {"sha": BASE, "tree": {"sha": OLD_TREE}},
        f"git/commits/{HEAD}": {"sha": HEAD, "tree": {"sha": NEW_TREE}},
        f"git/trees/{OLD_TREE}?recursive=1": {"sha": OLD_TREE, "truncated": False, "tree": list(old)},
        f"git/trees/{NEW_TREE}?recursive=1": {"sha": NEW_TREE, "truncated": False, "tree": list(new)},
    }


def changes(data):
    requested = []

    def api(path):
        requested.append(path)
        return copy.deepcopy(data[path])

    result = module().changes(api, BASE, HEAD)
    assert set(requested) <= set(data), "never follow a candidate-supplied URL"
    return result


def test_full_inventory_keeps_every_change_past_the_compare_limit():
    old = [entry("gone.py"), entry("same.py"), entry("changed.py")]
    new = [entry(f"added-{n:03}.py") for n in range(350)]
    new += [entry("same.py"), entry("changed.py", "f" * 40)]
    result = changes(responses(old, new))
    assert len(result) == 352
    assert [r["filename"] for r in result] == sorted(r["filename"] for r in result)
    assert {r["filename"]: r["status"] for r in result} == {
        **{f"added-{n:03}.py": "added" for n in range(350)},
        "changed.py": "modified", "gone.py": "removed",
    }
    assert next(r for r in result if r["filename"] == "changed.py")["sha"] == "f" * 40


def test_rename_is_conservative_add_and_remove_and_tree_hashes_are_not_file_changes():
    old = [entry("lib", OLD_TREE, mode="040000", kind="tree"), entry("lib/old.py")]
    new = [entry("lib", NEW_TREE, mode="040000", kind="tree"), entry("lib/new.py")]
    assert [(r["filename"], r["status"]) for r in changes(responses(old, new))] == [
        ("lib/new.py", "added"), ("lib/old.py", "removed")]


@pytest.mark.parametrize("mode,kind", [("100755", "blob"), ("120000", "blob"), ("160000", "commit")])
def test_mode_or_type_change_stays_visible_but_cannot_become_a_delta(mode, kind):
    assert changes(responses([entry("asset")], [entry("asset", mode=mode, kind=kind)])) == [
        {"filename": "asset", "status": "unsupported", "sha": "e" * 40}]


@pytest.mark.parametrize("mode,kind", [("120000", "blob"), ("160000", "commit")])
def test_special_entry_add_or_remove_is_also_not_a_regular_delta(mode, kind):
    special = entry("special", mode=mode, kind=kind)
    for old, new in [([], [special]), ([special], [])]:
        assert changes(responses(old, new))[0]["status"] == "unsupported"


def test_file_to_tree_keeps_the_conflict_and_child_change():
    new = [entry("asset", NEW_TREE, mode="040000", kind="tree"), entry("asset/child.py")]
    assert [(r["filename"], r["status"]) for r in changes(responses([entry("asset")], new))] == [
        ("asset", "unsupported"), ("asset/child.py", "added")]


@pytest.mark.parametrize("path", ["", "/absolute", "../escape", "a/../b", "a/./b", "a//b",
                                     "a/", "a\\b", "C:/absolute", "a\x00b", "a\nb"])
def test_ambiguous_paths_close_inventory(path):
    assert changes(responses(new=[entry(path)])) is None


@pytest.mark.parametrize("case", ["commit-sha", "commit-tree", "tree-sha", "truncated", "no-truncated",
                                     "false-integer", "not-list", "not-entry", "duplicate", "bad-sha",
                                     "bad-mode", "bad-type", "parent-missing", "parent-is-blob"])
def test_incomplete_or_inconsistent_api_identity_is_never_classified(case):
    data = responses(new=[entry("asset")])
    commit = data[f"git/commits/{HEAD}"]
    tree = data[f"git/trees/{NEW_TREE}?recursive=1"]
    if case == "commit-sha": commit["sha"] = BASE
    elif case == "commit-tree": commit["tree"]["sha"] = "main"
    elif case == "tree-sha": tree["sha"] = OLD_TREE
    elif case == "truncated": tree["truncated"] = True
    elif case == "no-truncated": del tree["truncated"]
    elif case == "false-integer": tree["truncated"] = 0
    elif case == "not-list": tree["tree"] = {}
    elif case == "not-entry": tree["tree"] = [None]
    elif case == "duplicate": tree["tree"] *= 2
    elif case == "bad-sha": tree["tree"][0]["sha"] = "E" * 40
    elif case == "bad-mode": tree["tree"][0]["mode"] = "040000"
    elif case == "bad-type": tree["tree"][0]["type"] = "unknown"
    elif case == "parent-missing": tree["tree"] = [entry("missing/child")]
    elif case == "parent-is-blob": tree["tree"] += [entry("asset/child")]
    assert changes(data) is None


def test_inventory_bound_is_fail_closed(monkeypatch):
    tool = module()
    monkeypatch.setattr(tool, "MAX_ENTRIES", 1)
    data = responses(new=[entry("one"), entry("two")])
    assert tool.changes(data.__getitem__, BASE, HEAD) is None


def test_invalid_revision_is_refused_before_any_api_request():
    tool = module()
    assert tool.changes(lambda _: pytest.fail("unexpected API request"), "main", HEAD) is None


def test_transport_failure_is_not_relabelled_as_an_empty_diff():
    def unavailable(_):
        raise RuntimeError("API unavailable")

    with pytest.raises(RuntimeError, match="API unavailable"):
        module().changes(unavailable, BASE, HEAD)
