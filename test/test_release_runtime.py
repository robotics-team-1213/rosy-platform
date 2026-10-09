import importlib.util
import json
import os
import subprocess

import pytest

from layout import ActivationRecord, Layout, write_activation
from release_fixture import signed_tree

# CI runs as root in its container; a non-root POSIX host (the shared test PCs) cannot.
# Windows keeps its existing behaviour.
REQUIRES_ROOT = pytest.mark.skipif(os.name == "posix" and os.geteuid() != 0,
                                   reason="needs root: chown of the activation config to root needs root")


def test_host_runtime_exists():
    assert importlib.util.find_spec("release_runtime") is not None


def test_a_running_compose_container_blocks_maintenance(tmp_path):
    from bundle import BundleError
    from release_runtime import DockerRuntime
    runner = lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "container-id\n", "")
    runtime = DockerRuntime(Layout.rooted(tmp_path), runner=runner)
    with pytest.raises(BundleError, match="RUNTIME_BUSY"):
        runtime.assert_stopped()


def test_docker_failure_is_not_an_empty_running_set(tmp_path):
    from bundle import BundleError
    from release_runtime import DockerRuntime
    runner = lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, "", "daemon unavailable")
    with pytest.raises(BundleError, match="RUNTIME_COMMAND"):
        DockerRuntime(Layout.rooted(tmp_path), runner=runner).assert_stopped()


def test_loaded_image_must_match_digest_and_arm64(tmp_path):
    from bundle import BundleError
    from release_runtime import DockerRuntime
    root, _, _ = signed_tree(tmp_path / "input")
    manifest = json.loads((root / "manifest.json").read_text())
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        result = [{"Id": manifest["containers"]["rosy_core"], "Architecture": "amd64", "Os": "linux"}]
        return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")

    with pytest.raises(BundleError, match="IMAGE_IDENTITY"):
        DockerRuntime(Layout.rooted(tmp_path / "device"), runner=runner).load_images(root, manifest)
    assert calls[0][:3] == ["docker", "image", "load"]


@REQUIRES_ROOT
def test_start_selects_activation_paths_and_never_builds(tmp_path):
    from release_runtime import DockerRuntime
    layout = Layout.rooted(tmp_path / "device")
    root, _, _ = signed_tree(layout.releases)
    version = root.name
    layout.etc.mkdir(parents=True)
    (layout.etc / "runtime.env").write_text("ROS_DOMAIN_ID=41\nROSY_NAMESPACE=rosy_01\nROSY_UID=960\nROSY_GID=960\nROSY_DATA_GENERATION=stale\n")
    config = layout.config_generation(version)
    config.mkdir(parents=True)
    (config / "rosy.yaml").write_text("robot: {}")
    working = layout.var / "data-working" / version
    working.mkdir(parents=True)
    write_activation(layout, ActivationRecord.create(release_id=version, release_path=root,
                                                     config_generation=version, data_generation=version))
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    DockerRuntime(layout, runner=runner).start("core")
    argv, kwargs = calls[-1]
    assert "--no-build" in argv and "--pull" in argv and "never" in argv
    assert argv[-1] == "rosy-core"
    assert kwargs["env"]["ROSY_CORE_IMAGE"] == "sha256:" + "a" * 64
    assert kwargs["env"]["ROSY_CONFIG_PATH"] == str(config / "rosy.yaml")
    assert kwargs["env"]["ROSY_DATA_PATH"] == str(working)
    assert kwargs["env"]["ROSY_DATA_GENERATION"] == version
    assert kwargs["env"]["ROSY_RUNTIME_MODE"] == "core"
