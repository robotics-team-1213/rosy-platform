"""The selected SDK interpreter must supply its own Jazzy library directory."""
import importlib.util
from pathlib import Path

import pytest


def module():
    path=Path(__file__).parents[1]/'sdk_ros.py'
    assert path.is_file(), 'SDK-selected ROS library resolver is missing'
    spec=importlib.util.spec_from_file_location('sdk_ros_under_test',path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize('python,extension', [('python3.11','isaacsim.ros2.bridge'),
                                             ('python3.12','isaacsim.ros2.core')])
def test_jazzy_libraries_follow_selected_sdk(tmp_path,python,extension):
    site=tmp_path/'lib'/python/'site-packages'
    expected=site/'isaacsim/exts'/extension/'jazzy/lib'
    expected.mkdir(parents=True)
    assert module().library_path(site)==expected


def test_core_is_selected_when_both_extensions_are_present(tmp_path):
    for extension in ('isaacsim.ros2.core','isaacsim.ros2.bridge'):
        (tmp_path/'isaacsim/exts'/extension/'jazzy/lib').mkdir(parents=True)
    assert module().library_path(tmp_path)==tmp_path/'isaacsim/exts/isaacsim.ros2.core/jazzy/lib'


def test_missing_bundled_libraries_are_refused(tmp_path):
    with pytest.raises(FileNotFoundError,match='Jazzy'):
        module().library_path(tmp_path)
