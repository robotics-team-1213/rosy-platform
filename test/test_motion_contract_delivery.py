"""D-442(b): installed release closure before the runtime imports motion contracts."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_and_sd_share_installed_contract_delivery_before_hash_compilation():
    native = (ROOT / "deploy/robot/pinky_pro/image/build-native-payload.sh").read_text(encoding="utf-8")
    image = (ROOT / "deploy/robot/pinky_pro/image/build-image.sh").read_text(encoding="utf-8")
    assert '"$SCRIPT_DIR/install-motion-contracts.sh" "$WORKSPACE" "$INSTALL_ROOT"' in native
    assert native.index('"$SCRIPT_DIR/install-motion-contracts.sh"') < native.index("python3 -m compileall")
    assert '"$SCRIPT_DIR/build-native-payload.sh"' in image


def test_core_final_image_carries_contracts_in_the_copied_install_tree_and_probes_imports():
    docker = (ROOT / "deploy/robot/pinky_pro/Dockerfile").read_text(encoding="utf-8")
    core_build = docker.split("FROM core-runtime AS core-build", 1)[1].split("FROM core-runtime AS core", 1)[0]
    assert "COPY contracts/skill /opt/rosy_ws/contracts/skill" in core_build
    assert "COPY contracts/motion /opt/rosy_ws/contracts/motion" in core_build
    assert "bash /opt/rosy_ws/install-motion-contracts.sh /opt/rosy_ws /opt/rosy_ws/install" in core_build
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert {"!contracts/", "!contracts/skill/", "!contracts/skill/**", "!contracts/motion/", "!contracts/motion/**"} <= set(ignore)
    probe = (ROOT / "deploy/robot/pinky_pro/probe-core-image.py").read_text(encoding="utf-8")
    assert "from rosy.contracts.motion import BaseTwist" in probe
    assert "from rosy.contracts.skill import AttemptIdentity" in probe


def test_both_arm64_builders_install_offline_wheel_build_prerequisites():
    # D-553 addendum 3: the payload job's prerequisites live in the payload-builder image script.
    for source_path in (".github/workflows/build-pinky-image.yml",
                        "deploy/robot/pinky_pro/image/payload-builder/install-ros-build-prereqs.sh"):
        source = (ROOT / source_path).read_text(encoding="utf-8")
        assert "python3-pip python3-setuptools python3-wheel" in source
