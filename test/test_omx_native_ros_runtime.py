"""Opt-in native ROS tests inside the committed remote-runner checkout."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.environ.get("ROSY_OMX_NATIVE_RUNTIME_TESTS") != "1",
                    reason="requires a Jazzy/Python 3.12 lab host")
def test_native_ros_runtime():
    root = Path(__file__).resolve().parents[1]
    command = r'''
set -e
source /opt/ros/jazzy/setup.bash
test "$ROS_DISTRO" = jazzy
export ROS_DOMAIN_ID=113 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_STATIC_PEERS=''
unset CYCLONEDDS_URI FASTDDS_DEFAULT_PROFILES_FILE FASTRTPS_DEFAULT_PROFILES_FILE ROS_DISCOVERY_SERVER
exec "$1" -m pytest middleware/devices/omx/adapter/test/test_omx_ros_runtime.py -q -rA
'''
    result = subprocess.run(["bash", "-c", command, "omx-native-runtime", sys.executable],
                            cwd=root, capture_output=True, text=True, timeout=180)
    print(result.stdout, result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout and "skipped" not in result.stdout
