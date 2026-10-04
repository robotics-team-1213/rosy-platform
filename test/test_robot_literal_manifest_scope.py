"""Manifest production-scope regressions after D-427 wave 5."""
import importlib.util
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def guard():
    path = Path(__file__).with_name('test_robot_literals.py')
    spec = importlib.util.spec_from_file_location('wave5_literal_guard', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def manifest_tree(tmp_path, guard, monkeypatch):
    parts = {'contracts': 'contracts', 'middleware': 'middleware', 'operations': 'operations',
             'integrations': 'integrations', 'shared_web': 'shared'}
    entries = []
    for part, top in parts.items():
        path = tmp_path / top / 'owned' / 'config.py'
        path.parent.mkdir(parents=True)
        path.write_text('DEFAULT_MODEL = "pinky_pro"\n', encoding='utf-8')
        entries.append({'path': top + '/owned', 'part': part})
    manifest = tmp_path / 'tools/harness/platform_parts.yaml'
    manifest.parent.mkdir(parents=True)

    def write():
        manifest.write_text(yaml.safe_dump({'roots': entries}), encoding='utf-8')
    write()
    monkeypatch.setattr(guard, 'ROOT', tmp_path)
    return tmp_path, entries, write


def test_moving_a_manifest_part_keeps_its_configuration_in_scope(guard, manifest_tree):
    root, entries, write = manifest_tree
    (root / 'middleware').rename(root / 'moved_runtime')
    next(row for row in entries if row['part'] == 'middleware')['path'] = 'moved_runtime/owned'
    write()
    assert 'moved_runtime/owned/config.py' in guard.hits()


def test_an_added_manifest_root_is_scanned_and_learning_stays_out(guard, manifest_tree):
    root, entries, write = manifest_tree
    for top, part in [('new_site', 'operations'), ('learning', 'learning')]:
        path = root / top / 'config.py'
        path.parent.mkdir()
        path.write_text('DEFAULT_MODEL = "pinky_pro"\n', encoding='utf-8')
        entries.append({'path': top, 'part': part})
    write()
    found = guard.hits()
    assert 'new_site/config.py' in found
    assert 'learning/config.py' not in found


def test_part_omission_fails_instead_of_reducing_the_scan(guard, manifest_tree):
    root, entries, write = manifest_tree
    entries[:] = [row for row in entries if row['part'] != 'shared_web']
    write()
    with pytest.raises(AssertionError):
        guard.hits()


def test_missing_declared_directory_fails_even_with_other_live_parts(guard, manifest_tree):
    root, entries, write = manifest_tree
    next(row for row in entries if row['part'] == 'shared_web')['path'] = 'missing_shared/owned'
    write()
    with pytest.raises(AssertionError):
        guard.hits()


def test_empty_source_scan_fails_instead_of_matching_empty_backlog(guard, manifest_tree):
    root, entries, write = manifest_tree
    for path in root.rglob('config.py'):
        path.unlink()
    with pytest.raises(AssertionError):
        guard.hits()


@pytest.mark.parametrize("missing", ["contracts", "middleware", "operations", "integrations", "shared_web"])
def test_each_policy_part_remains_required(guard, manifest_tree, missing):
    root, entries, write = manifest_tree
    entries[:] = [entry for entry in entries if entry['part'] != missing]
    write()
    with pytest.raises(AssertionError):
        guard.hits()


@pytest.mark.parametrize("invalid", ["", ".", "../outside", "/absolute", "X:/outside", "bad\\path"])
def test_invalid_scan_paths_fail_closed(guard, manifest_tree, invalid):
    root, entries, write = manifest_tree
    entries[0]['path'] = invalid
    write()
    with pytest.raises(AssertionError):
        guard.hits()


@pytest.mark.parametrize("top", ["learning", "tools"])
def test_cross_part_nesting_requires_scope_review(guard, manifest_tree, top):
    root, entries, write = manifest_tree
    (root / top).mkdir(exist_ok=True)
    entries[0]['path'] = top + '/contracts'
    write()
    with pytest.raises(AssertionError):
        guard.hits()


def test_nested_owner_does_not_hide_existing_physical_scope(guard, manifest_tree):
    root, entries, write = manifest_tree
    entries.append({'path': 'middleware/owned', 'part': 'learning'})
    write()
    assert 'middleware/owned/config.py' in guard.hits()


def test_all_five_configuration_families_are_checked(guard, manifest_tree):
    root, entries, write = manifest_tree
    assert guard.hits() == {entry['path'] + '/config.py' for entry in entries}
