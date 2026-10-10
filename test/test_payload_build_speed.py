"""Payload build time contracts (2026-10-01 measurement).

On the ARM64 runner the payload build took ~6.5 min, of which colcon was 40 s.
rosdep installed ~958 packages through 22 separate `apt-get install` runs
(~4.5 min, 30 trigger passes). The build now resolves rosdep's apt packages
once and installs them in one transaction with rosdep's own flags; rosdep
still runs afterwards and must find nothing left to do.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "deploy" / "robot" / "pinky_pro" / "image"
BATCH = IMAGE / "rosdep_apt_batch.py"
BUILD = IMAGE / "build-native-payload.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "build-native-payload.yml"

SIMULATE_AS_ROOT = """\
#[apt] Installation commands:
  apt-get install -y ros-jazzy-nav2-msgs
  apt-get install -y python3-uvicorn
  apt-get install -y ros-jazzy-nav2-msgs
#[pip] Installation commands:
  pip3 install -U something
"""
SIMULATE_WITH_SUDO = """\
#[apt] Installation commands:
  sudo -H apt-get install -y ros-jazzy-xacro
  sudo -H apt-get install -y python3-opencv libboost1.83-dev
"""


def _batch(text: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BATCH)], input=text, capture_output=True,
                          text=True, timeout=30)


def test_the_batch_lists_each_apt_package_once_in_a_stable_order():
    completed = _batch(SIMULATE_AS_ROOT)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split() == ["python3-uvicorn", "ros-jazzy-nav2-msgs"]


def test_the_batch_reads_sudo_lines_and_several_packages_per_line():
    completed = _batch(SIMULATE_WITH_SUDO)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split() == ["libboost1.83-dev", "python3-opencv", "ros-jazzy-xacro"]


def test_nothing_to_install_prints_nothing():
    completed = _batch("#All required rosdeps installed successfully\n")

    assert completed.returncode == 0 and completed.stdout == ""


def test_a_name_that_is_not_a_debian_package_is_refused():
    # The list reaches apt-get as root; anything but a package name fails closed.
    completed = _batch("  apt-get install -y ros-jazzy-x;reboot\n")

    assert completed.returncode != 0
    assert completed.stdout == ""


def test_the_build_installs_rosdep_apt_packages_in_one_transaction_before_rosdep():
    script = BUILD.read_text(encoding="utf-8")

    simulate = script.index("--simulate")
    batch = script.index("rosdep_apt_batch.py")
    install = script.index('apt-get install -y "${ROSDEP_APT[@]}"')
    confirm = script.index("rosdep install --from-paths", install)
    assert simulate < batch < install < confirm
    # rosdep's own flags only: the installed set (and ros-packages.txt) stays the same.
    assert "--no-install-recommends" not in script[simulate:confirm]


def test_the_runner_skips_fsync_and_man_db_for_dpkg_before_any_install():
    # D-553 addendum 3: the prerequisites install inside the payload-builder image.
    workflow = (IMAGE / "payload-builder" / "install-ros-build-prereqs.sh").read_text(encoding="utf-8")

    unsafe_io = workflow.index("force-unsafe-io")
    first_install = workflow.index("apt-get install")
    assert unsafe_io < first_install
    assert "/var/lib/man-db/auto-update" in workflow[:first_install]
    # Runner only: the image build path never sees these settings.
    for path in IMAGE.glob("*.sh"):
        assert "force-unsafe-io" not in path.read_text(encoding="utf-8"), path.name
