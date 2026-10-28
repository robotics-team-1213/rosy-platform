"""Shell/CI wiring contracts; actual native image generation is a separate gate."""
from pathlib import Path

from test_ab_image_layout import IMAGE


def test_builder_assembles_ab_before_finalization_and_passes_the_same_layout():
    source = (IMAGE / "build-image.sh").read_text()
    assert source.index("assemble-ab-image.py") < source.index('"$SCRIPT_DIR/finalize-image.sh"')
    assert '--source-image "$PREPARED_IMAGE"' in source
    assert '--output-image "$RAW_IMAGE"' in source
    assert source.count('--layout-file "$LAYOUT_FILE"') == 2
    assert source.index('rm -f -- "$PREPARED_IMAGE"') < source.index('"$SCRIPT_DIR/finalize-image.sh"')


def test_finalizer_uses_inspected_gpt_roles_instead_of_assuming_partition_two():
    source = (IMAGE / "finalize-image.sh").read_text()
    assert 'ab_image_layout.py" filesystems' in source
    assert '--layout "$LAYOUT_FILE"' in source
    assert 'fsck.vfat -n "$DEVICE"' in source
    assert 'e2fsck -fn "$DEVICE"' in source


def test_native_arm_workflow_has_real_filesystem_tools_and_preserves_unsigned_boundary():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/build-pinky-image.yml").read_text()
    assert "runs-on: ubuntu-24.04-arm" in workflow
    for package in ("fdisk", "dosfstools", "rsync", "e2fsprogs"):
        assert package in workflow
    assert '.capacity.json"' in workflow
    assert 'test ! -e "$release/SHA256SUMS.sig"' in workflow


def test_privileged_image_build_owns_the_checkout_before_cms_preflight():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/build-pinky-image.yml").read_text()
    build = workflow.split("- name: Build unsigned flashable image", 1)[1].split("- name:", 1)[0]
    assert build.index('sudo chown -R root:root -- "$GITHUB_WORKSPACE"') < build.index("sudo env")
    assert '--workspace "$GITHUB_WORKSPACE"' in build
    assert 'os_cms_trust.py" --lock "$LOCK" --source-tree "$WORKSPACE"' in (IMAGE / "build-image.sh").read_text()
