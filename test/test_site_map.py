"""The private site map names every arm board once; the check reports what the host has beyond or short of it."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/remote"))
import site_map  # noqa: E402

A, B, L = "2B162C9B50323952582E3120FF06202D", "7F31D1FE50323952582E3120FF061D2D", "D8F7C0C650323952582E3120FF053322"
HOST = {"arms": {"arm_a": {"follower": {"board": A}, "leader": {"board": L}}, "arm_b": {"follower": {"board": B}}}}


def test_findings_name_missing_and_unmapped_boards():
    assert site_map.board_findings(HOST, {A, B, L}) == []
    spare = "84C663DE50323952582E3120FF06132A"
    assert site_map.board_findings(HOST, {A, L, spare}) == [f"missing arm_b.follower board {B}", f"unmapped board {spare}"]


def test_a_board_mapped_twice_is_refused():
    with pytest.raises(SystemExit, match="mapped twice"):
        site_map.boards({"arms": {"arm_a": {"follower": {"board": A}}, "arm_b": {"leader": {"board": A}}}})


def test_load_requires_the_schema(tmp_path):
    path = tmp_path / "site-map.yaml"
    path.write_text(yaml.safe_dump({"schema": "rosy.site-map/1", "hosts": {"robttt": HOST}}), encoding="utf-8")
    assert site_map.load(path)["hosts"]["robttt"] == HOST
    path.write_text(yaml.safe_dump({"hosts": {}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        site_map.load(path)


def test_the_openrb_pattern_reads_by_id_names():
    listing = f"usb-ROBOTIS_OpenRB-150_{A}-if00\nusb-Intel_RealSense-video-index0\n"
    assert set(site_map.OPENRB.findall(listing)) == {A}
