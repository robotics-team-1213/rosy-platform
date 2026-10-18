"""D-794 B: readers treat the OMX ``front`` and ``wrist`` names as one wrist camera; keys follow the recording."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "contracts/learning/src"), str(ROOT / "learning/curation/omx")]
from rosy.contracts.learning.omx import WRIST, camera_role, camera_roles  # noqa: E402
import lerobot_export  # noqa: E402


def test_alias_table_maps_both_names_to_the_writer_name():
    assert WRIST == "front"  # stage C flips this one constant
    assert camera_role("wrist") == camera_role("front") == WRIST
    assert camera_role("top") == "top"
    assert camera_roles(["top", "wrist"]) == camera_roles(["top", "front"]) == {"top", WRIST}
    with pytest.raises(ValueError, match="duplicate camera role"):
        camera_roles(["front", "wrist"])


@pytest.mark.parametrize("name", ["front", "wrist"])
def test_export_image_key_follows_the_recorded_camera(name):
    manifest = {"provenance": {"camera": {"name": name}}}
    assert lerobot_export.image_key(manifest) == "observation.images." + name
