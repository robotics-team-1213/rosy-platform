"""Versioned class sets: same names in the same order always give the same sha."""
import pytest

import class_sets
from object_boxes import OBJECT_CLASSES


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
                b'names: [a]\ncolors: [1]\n', b'names: [a]\ndisplay: x\n'):
        with pytest.raises(ValueError):
            class_sets.from_data_yaml(raw, 'detect')


def test_legacy_object_set_is_the_d423_list():
    legacy = class_sets.legacy_object_set()
    assert tuple(c['name'] for c in legacy['classes']) == OBJECT_CLASSES
    assert legacy['source']['kind'] == 'd423_v1'
