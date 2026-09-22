import pytest
import importlib.util
import sys
from pathlib import Path

# Load verify-mounted-image.py dynamically
spec = importlib.util.spec_from_file_location(
    "verify_mounted_image",
    Path(__file__).resolve().parents[1] / "verify-mounted-image.py"
)
verify_mounted_image = importlib.util.module_from_spec(spec)
sys.modules["verify_mounted_image"] = verify_mounted_image
spec.loader.exec_module(verify_mounted_image)

def test_package_names(tmp_path):
    f = tmp_path / "pkgs.txt"
    f.write_text("pkg_a\n\n# comment\n  pkg_b  \n", encoding="utf-8")
    names = verify_mounted_image.package_names(f)
    assert names == {"pkg_a", "pkg_b"}

def test_inspect_passes_with_valid_image(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    release_id = "2026.01.01-001"
    release_dir = root / "opt/rosy/releases" / release_id
    release_dir.mkdir(parents=True)
    
    # Required paths
    paths = [
        "opt/ros/jazzy/setup.bash",
        f"opt/rosy/releases/{release_id}/install/setup.bash",
        "etc/rosy/motion_profiles.yaml",
        "etc/rosy/cyclonedds.xml",
        "opt/rosy/first-boot/rosy-first-boot.py",
        "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem",
    ]
    for p in paths:
        path = root / p
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        
    # Required units
    for unit in verify_mounted_image.REQUIRED_UNITS:
        path = root / "etc/systemd/system" / unit
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        
    # Inventory
    (release_dir / "required-ros-packages.txt").write_text("pkg_a", encoding="utf-8")
    (release_dir / "rosy-packages.txt").write_text("pkg_a\npkg_b", encoding="utf-8")

    # chrony ships enabled (CORE SRS §25 premise, verifier-checked).
    (root / "usr/sbin").mkdir(parents=True, exist_ok=True)
    (root / "usr/sbin/chronyd").write_text("mock", encoding="utf-8")
    wants = root / "etc/systemd/system/multi-user.target.wants/chrony.service"
    wants.parent.mkdir(parents=True, exist_ok=True)
    wants.write_text("mock", encoding="utf-8")

    findings = verify_mounted_image.inspect(root, release_id)
    assert not findings, findings

def test_inspect_fails_if_docker_present(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    release_id = "2026.01.01-001"
    release_dir = root / "opt/rosy/releases" / release_id
    release_dir.mkdir(parents=True)
    
    # Required paths
    paths = [
        "opt/ros/jazzy/setup.bash",
        f"opt/rosy/releases/{release_id}/install/setup.bash",
        "etc/rosy/motion_profiles.yaml",
        "etc/rosy/cyclonedds.xml",
        "opt/rosy/first-boot/rosy-first-boot.py",
        "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem",
    ]
    for p in paths:
        path = root / p
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        
    for unit in verify_mounted_image.REQUIRED_UNITS:
        path = root / "etc/systemd/system" / unit
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        
    (release_dir / "required-ros-packages.txt").write_text("", encoding="utf-8")
    (release_dir / "rosy-packages.txt").write_text("", encoding="utf-8")
    
    docker = root / "usr/bin/docker"
    docker.parent.mkdir(parents=True, exist_ok=True)
    docker.write_text("bin", encoding="utf-8")
    
    findings = verify_mounted_image.inspect(root, release_id)
    assert any("docker must not be installed" in f for f in findings)
