"""OMX instance graph names come from the namespace, never from root literals (D-778 §1, D-779)."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "deploy/robot/omx") not in sys.path:
    sys.path.insert(0, str(ROOT / "deploy/robot/omx"))

from cell_sim_tools import refuse_second_owner  # noqa: E402
from instance_names import InstanceNames, names_from_environment, namespace_from_environment  # noqa: E402

_SCRIPTS = ("run_cell_owner.py", "g2_owner.py", "g2_common.py", "g2_observer.py", "probe_cell_transfer.py")


def test_root_graph_keeps_the_single_arm_names():
    names = InstanceNames()
    assert names.joint_state_topic == "/joint_states"
    assert names.trajectory_action == "/arm_controller/follow_joint_trajectory"
    assert names.list_controllers_service == "/controller_manager/list_controllers"


def test_instance_namespace_prefixes_every_name():
    names = InstanceNames("/omx_02")
    assert names.joint_state_topic == "/omx_02/joint_states"
    assert names.trajectory_action == "/omx_02/arm_controller/follow_joint_trajectory"
    assert names.list_controllers_service == "/omx_02/controller_manager/list_controllers"


@pytest.mark.parametrize("bad", ["", "omx_02", "/omx_02/", "/omx-02", "/2omx", "//omx", "/omx 02"])
def test_malformed_namespace_is_refused(bad):
    with pytest.raises(ValueError, match="absolute ROS namespace"):
        InstanceNames(bad)
    with pytest.raises(ValueError, match="absolute ROS namespace"):
        namespace_from_environment({"ROSY_OMX_ROS_NAMESPACE": bad})


def test_environment_selects_the_namespace_and_defaults_to_root():
    assert namespace_from_environment({}) == "/"
    assert names_from_environment({"ROSY_OMX_ROS_NAMESPACE": "/cell/omx_01"}).trajectory_action == \
        "/cell/omx_01/arm_controller/follow_joint_trajectory"


@pytest.mark.parametrize("script", _SCRIPTS)
def test_owner_and_probe_scripts_take_names_from_the_namespace(script):
    text = (ROOT / "deploy/robot/omx" / script).read_text(encoding="utf-8")
    assert '"/joint_states"' not in text
    assert '"/arm_controller/follow_joint_trajectory"' not in text
    assert "names_from_environment" in text


def _owner(proc: Path, pid: str, environ: bytes | None) -> None:
    (proc / pid).mkdir(parents=True)
    (proc / pid / "cmdline").write_bytes(b"python3\0deploy/robot/omx/run_cell_owner.py")
    if environ is not None:
        (proc / pid / "environ").write_bytes(environ)


def test_second_owner_in_another_namespace_is_allowed(tmp_path):
    proc = tmp_path / "proc"
    _owner(proc, "4001", b"PATH=/usr/bin\0ROSY_OMX_ROS_NAMESPACE=/omx_01\0")
    refuse_second_owner(proc_root=proc, namespace="/omx_02")
    with pytest.raises(RuntimeError, match="4001"):
        refuse_second_owner(proc_root=proc, namespace="/omx_01")


def test_owner_without_namespace_is_the_root_graph(tmp_path):
    proc = tmp_path / "proc"
    _owner(proc, "4001", b"PATH=/usr/bin\0")
    with pytest.raises(RuntimeError, match="4001"):
        refuse_second_owner(proc_root=proc)
    refuse_second_owner(proc_root=proc, namespace="/omx_02")


def test_unreadable_owner_namespace_counts_as_the_same_graph(tmp_path):
    proc = tmp_path / "proc"
    _owner(proc, "4001", None)
    with pytest.raises(RuntimeError, match="4001"):
        refuse_second_owner(proc_root=proc, namespace="/omx_02")
