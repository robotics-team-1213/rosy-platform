"""Versioned class sets: same names in the same order always give the same sha."""
import pytest

import class_sets
from object_boxes import OBJECT_CLASSES
from test_review_app import open_store
from test_review_return import fixture_inputs
from review_app import ReviewStore


def test_data_yaml_dict_and_list_give_the_same_record():
    as_dict = class_sets.from_data_yaml(b'names:\n  0: robot\n  1: cone\n', 'detect')
    as_list = class_sets.from_data_yaml(b'names: [robot, cone]\n', 'detect')
    assert as_dict['sha256'] == as_list['sha256']
    assert [c['name'] for c in as_dict['classes']] == ['robot', 'cone']
    assert as_dict['classes'][0]['hotkey'] == '1'


def test_display_and_color_come_from_the_file_and_do_not_change_identity():
    plain = class_sets.from_data_yaml(b'names: [robot]\n', 'detect')
    shown = class_sets.from_data_yaml(
        'names: [robot]\ndisplay: {robot: "로봇"}\ncolors: {robot: [255, 0, 0]}\n'.encode('utf-8'), 'detect')
    assert shown['classes'][0]['display'] == '로봇'
    assert shown['classes'][0]['color'] == [255, 0, 0]
    assert shown['sha256'] == plain['sha256']


def test_bad_names_are_refused():
    for raw in (b'names: []\n', b'names: [a, a]\n', b'names: {0: a, 2: b}\n', b'nc: 2\n',
                b'names: [a]\ncolors: {a: [256, 0, 0]}\n', b'names: [a]\ncolors: {a: [1, 2]}\n',
                b'names: [a]\ncolors: [1]\n', b'names: [a]\ndisplay: x\n',
                b'names: [a\n', b'names: {0: a, x: b}\n',
                b'names: [a]\ndisplay: {a: ""}\n'):
        with pytest.raises(ValueError):
            class_sets.from_data_yaml(raw, 'detect')


def test_legacy_object_set_is_the_d423_list():
    legacy = class_sets.legacy_object_set()
    assert tuple(c['name'] for c in legacy['classes']) == OBJECT_CLASSES
    assert legacy['source']['kind'] == 'd423_v1'


def generation(store):
    with store.connect() as db:
        return int(db.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()[0])


def test_old_workspace_reads_the_legacy_set_and_binding_is_write_once(tmp_path):
    store = open_store(tmp_path)
    with store.connect() as db:   # a workspace made before D-485 has no binding row
        db.execute("DELETE FROM metadata WHERE key='object_class_set'")
    assert class_sets.object_set(store)['sha256'] == class_sets.legacy_object_set()['sha256']
    other = class_sets.from_data_yaml(b'names: [car, person]\n', 'detect')
    with pytest.raises(ValueError, match='do not reinterpret'):
        class_sets.bind_object_set(store, other)
    assert generation(store) == 1
    class_sets.bind_object_set(store, class_sets.legacy_object_set())   # first bind records it, +1
    assert generation(store) == 2
    class_sets.bind_object_set(store, class_sets.legacy_object_set())   # repeat: no change
    assert generation(store) == 2


def test_first_start_binds_the_given_set_then_is_write_once(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    other = class_sets.from_data_yaml(b'names: [car, traffic_light]\n', 'detect')
    store = ReviewStore(tmp_path / 'state', source, human, images, object_classes=other)
    assert class_sets.object_set(store)['sha256'] == other['sha256']
    assert generation(store) == 1
    with pytest.raises(ValueError, match='do not reinterpret'):
        class_sets.bind_object_set(store, class_sets.legacy_object_set())


def test_invalid_task_hotkey_limit_and_task_in_identity():
    with pytest.raises(ValueError):
        class_sets._record(['a'], 'segment', {})
    ten = class_sets.from_data_yaml(('names: [' + ','.join(f'c{i}' for i in range(10)) + ']').encode(), 'detect')
    assert ten['classes'][8]['hotkey'] == '9' and ten['classes'][9]['hotkey'] is None
    assert (class_sets.from_data_yaml(b'names: [a]\n', 'detect')['sha256']
            != class_sets.from_data_yaml(b'names: [a]\n', 'semantic')['sha256'])


def test_bind_refuses_non_detect_and_forged_sha(tmp_path):
    store = open_store(tmp_path)
    with store.connect() as db:
        db.execute('DELETE FROM frames')
    with pytest.raises(ValueError):
        class_sets.bind_object_set(store, class_sets.from_data_yaml(b'names: [a]\n', 'semantic'))
    forged = class_sets.from_data_yaml(b'names: [a]\n', 'detect')
    forged['sha256'] = class_sets.legacy_object_set()['sha256']
    with pytest.raises(ValueError):
        class_sets.bind_object_set(store, forged)


def test_reject_label_is_reserved():
    with pytest.raises(ValueError, match='reserved'):
        class_sets.from_data_yaml(b'names: [car, none]\n', 'detect')
