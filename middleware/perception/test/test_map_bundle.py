"""map_bundle: any Nav2 map is checked by the same rules; a saved SLAM map drops in with an occupied outside."""
import importlib.util
import json
from pathlib import Path

import pytest

MAPDIR = Path(__file__).resolve().parents[1] / "map"
spec = importlib.util.spec_from_file_location("map_bundle", MAPDIR / "map_bundle.py")
mb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mb)


def write_saved(folder, rows, res=0.05, origin=(-1.0, -2.0, 0.0), name="saved"):
    """A map as slam_toolbox/map_saver writes it: unknown (205) outside, free (254), walls (0)."""
    folder.mkdir(parents=True, exist_ok=True)
    h, w = len(rows), len(rows[0])
    (folder / f"{name}.pgm").write_bytes(f"P5\n# saved\n{w} {h}\n255\n".encode() + b"".join(bytes(r) for r in rows))
    (folder / f"{name}.yaml").write_text(
        f"image: {name}.pgm\nmode: trinary\nresolution: {res}\norigin: [{origin[0]}, {origin[1]}, {origin[2]}]\n"
        "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n", encoding="utf-8")
    return folder / f"{name}.yaml"


ROOM = [[205] * 6, [205, 0, 0, 0, 0, 205], [205, 0, 254, 254, 0, 205], [205, 0, 254, 254, 0, 205],
        [205, 0, 0, 0, 0, 205], [205] * 6]


def test_the_committed_world_map_passes_the_same_rules():
    assert mb.problems(MAPDIR / "map_world_261026" / "maps" / "map_world_261026.yaml") == []


def test_a_saved_slam_map_with_unknown_edges_is_not_closed_until_imported(tmp_path):
    saved = write_saved(tmp_path / "saved", ROOM)
    assert any("border cells are not occupied" in p for p in mb.problems(saved))
    out = mb.import_saved(saved, tmp_path / "bundle", "lab", margin_m=0.10, source="y8xs/2026-11-17/slam save_map")
    assert mb.problems(out) == []
    m = mb.load(out)
    assert (m["width"], m["height"]) == (6 + 2 * 2, 6 + 2 * 2)          # 0.10 m / 0.05 = 2 cells each side
    assert m["origin"][:2] == pytest.approx([-1.0 - 0.10, -2.0 - 0.10])  # the image grew left and down
    assert m["rows"][4][2 + 2] == 254                                     # the free cell kept its place (row, col shifted by 2)
    manifest = json.loads((tmp_path / "bundle" / "maps" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"].startswith("y8xs") and manifest["margin_cells"] == 2


def test_import_rotates_the_origin_shift_with_the_map_yaw(tmp_path):
    saved = write_saved(tmp_path / "saved", ROOM, origin=(0.0, 0.0, 1.5707963267948966))
    out = mb.import_saved(saved, tmp_path / "bundle", "lab", margin_m=0.10)
    assert mb.load(out)["origin"][:2] == pytest.approx([0.10, -0.10], abs=1e-6)   # yaw 90 deg: map x -> world +y, map y -> world -x; corner moves by -s*x_axis - s*y_axis


@pytest.mark.parametrize("bad", ["not a pgm", "P5\n2 2\n255\n\x00"])
def test_unreadable_images_are_reported_not_raised(tmp_path, bad):
    (tmp_path / "m.pgm").write_bytes(bad.encode("latin1"))
    (tmp_path / "m.yaml").write_text("image: m.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n"
                                     "occupied_thresh: 0.65\nfree_thresh: 0.196\n", encoding="utf-8")
    assert mb.problems(tmp_path / "m.yaml")


def test_occupancy_grid_id_matches_core_features_exactly(tmp_path):
    import sys

    core_svc = Path(__file__).resolve().parents[3] / "middleware" / "core" / "services"
    if str(core_svc) not in sys.path:
        sys.path.insert(0, str(core_svc))
    from core_features.maps import GridFrame, occupancy_map_id

    saved = write_saved(tmp_path / "m", ROOM, res=0.05, origin=(-1.25, 0.75, 0.0))
    # Build bottom-to-top ROS OccupancyGrid equivalent of ROOM (6x6, top-to-bottom in PGM).
    ros_data = [
        100 if px < 90 else (0 if px > 205 else -1)
        for row in reversed(ROOM)
        for px in row
    ]
    core_id = occupancy_map_id(GridFrame.from_dict({
        "width": 6,
        "height": 6,
        "resolution": 0.05,
        "origin": {"x": -1.25, "y": 0.75, "yaw": 0.0},
        "data": ros_data,
    }).to_dict())
    assert mb.occupancy_grid_id(saved) == core_id


def test_import_seals_site_aligned_manifest_and_verify_bundle_catches_tampering(tmp_path):
    rot_saved = write_saved(tmp_path / "rot", ROOM, origin=(0.0, 0.0, 0.25))
    with pytest.raises(ValueError, match="origin yaw must be 0.0"):
        mb.import_saved(rot_saved, tmp_path / "bad_bundle", "site", site_map_id="site_a")

    saved = write_saved(tmp_path / "ok", ROOM, origin=(-0.5, -0.5, 0.0))
    out = mb.import_saved(
        saved, tmp_path / "bundle", "master", margin_m=0.10,
        source="pinky/2026-11-23", site_map_id="site_a",
        alignment={"tool": "slam_map_align", "rms_residual_m": 0.012},
        require_zero_yaw=True,
    )
    assert mb.verify_bundle(out, require_zero_yaw=True, require_manifest=True) == []
    assert mb.main(["check", "--verify-manifest", "--require-zero-yaw", str(out)]) == 0
    manifest = json.loads((out.parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["site_map_id"] == "site_a"
    assert manifest["grid_id"] == mb.occupancy_grid_id(out)
    assert manifest["origin"] == pytest.approx([-0.6, -0.6, 0.0])
    assert manifest["alignment"]["tool"] == "slam_map_align"

    # Flip one pixel in PGM: verify_bundle and CLI check must fail closed on hash/grid_id mismatch.
    pgm_path = out.parent / "master.pgm"
    raw = bytearray(pgm_path.read_bytes())
    raw[-15] = 254 if raw[-15] != 254 else 0
    pgm_path.write_bytes(bytes(raw))
    errs = mb.verify_bundle(out, require_zero_yaw=True, require_manifest=True)
    assert any("pgm_sha256 mismatch" in e for e in errs)
    assert any("grid_id mismatch" in e for e in errs)
    assert mb.main(["check", "--verify-manifest", "--require-zero-yaw", str(out)]) == 1
