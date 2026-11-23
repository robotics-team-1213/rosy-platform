"""Offline multi-Pinky master map consensus fusion and sealing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import master_map_fuse as mmf  # noqa: E402
import slam_map_align as sma  # noqa: E402


def _write_site_map(folder: Path, name: str, cells: np.ndarray, *,
                    res: float = 0.05, origin: tuple[float, float, float] = (-1.5, -1.0, 0.0)) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    h, w = cells.shape
    (folder / f"{name}.pgm").write_bytes(
        f"P5\n# test\n{w} {h}\n255\n".encode() + cells[::-1].astype(np.uint8).tobytes()
    )
    (folder / f"{name}.yaml").write_text(
        f"image: {name}.pgm\nmode: trinary\nresolution: {res}\n"
        f"origin: [{origin[0]}, {origin[1]}, {origin[2]}]\n"
        "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n",
        encoding="utf-8",
    )
    return folder / f"{name}.yaml"


def _base_room(w: int = 60, h: int = 40) -> np.ndarray:
    """60x40 cells = 3.0x2.0 m room with closed perimeter walls and interior feature."""
    cells = np.full((h, w), 254, dtype=np.uint8)
    cells[0, :] = cells[-1, :] = cells[:, 0] = cells[:, -1] = 0
    cells[10:20, 12] = 0  # interior asymmetric partition wall
    return cells


def test_fuse_preserves_jittered_walls_fills_blind_spots_and_drops_transient_peer(tmp_path):
    r1 = _base_room()
    r2 = _base_room()

    # 1-cell quantization jitter on r2 partition wall (col 13 instead of col 12).
    r2[10:20, 12] = 254
    r2[10:20, 13] = 0

    # Transient peer obstacle present in r1 only where r2 observes free corridor.
    r1[28:30, 40:42] = 0

    # Blind spot alcove in top-right where r2 didn't observe (205=unknown), r1 mapped wall at y=h-2.
    r1[8:14, 48] = 0
    r2[8:14, 48] = 205

    p1 = _write_site_map(tmp_path / "maps", "pinky1", r1)
    p2 = _write_site_map(tmp_path / "maps", "pinky2", r2)
    bundle = tmp_path / "bundle"
    assert mmf.main([
        str(p1), str(p2),
        "--seal-bundle", str(bundle),
        "--name", "master_v1",
        "--site-map-id", "site_v1",
        "--source", "pinky1+pinky2",
    ]) == 0

    sealed = bundle / "maps" / "master_v1.yaml"
    mb = sma.load_map_bundle_module()
    assert mb.verify_bundle(sealed, require_zero_yaw=True, require_manifest=True) == []
    manifest = json.loads((bundle / "maps" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["site_map_id"] == "site_v1"
    assert manifest["alignment"]["tool"] == "master_map_fuse"
    assert manifest["alignment"]["input_count"] == 2
    assert len(manifest["alignment"]["source_pgm_sha256s"]) == 2
    assert manifest["alignment"]["transient_obstacles_removed"] == 4
    assert manifest["alignment"]["blind_spot_cells_filled"] == 6

    fused_grid = sma.load_map(sealed)
    pad = manifest["margin_cells"]
    assert fused_grid.cells[pad + 28, pad + 40] == 0  # transient peer cleared to free
    assert fused_grid.cells[pad + 10, pad + 12] == 1  # jittered wall kept
    assert fused_grid.cells[pad + 10, pad + 48] == 1  # blind-spot wall kept


def test_fuse_three_maps_consensus_keeps_two_of_three_static_walls(tmp_path):
    r1, r2, r3 = _base_room(), _base_room(), _base_room()
    # Dynamic obstacle seen only in r3 -> dropped even against min_support=2.
    r3[25:27, 25:27] = 0
    # New static crate seen by r1 and r2 -> kept.
    r1[15:17, 30:32] = 0
    r2[15:17, 30:32] = 0

    paths = [
        _write_site_map(tmp_path / "m", f"p{i}", arr)
        for i, arr in enumerate((r1, r2, r3), 1)
    ]
    out_yaml = tmp_path / "out" / "master3.yaml"
    out_yaml.parent.mkdir()
    assert mmf.main([str(p) for p in paths] + ["--min-support", "2", "--write", str(out_yaml)]) == 0
    grid = sma.load_map(out_yaml)
    assert grid.cells[25, 25] == 0   # transient cleared
    assert grid.cells[15, 30] == 1   # 2/3 consensus static obstacle kept

    # With min_support=3 on 3 maps where r3 had unknown (-1) over a 2-pass wall, uncontradicted wall stays WALL (1).
    r1_u, r2_u, r3_u = _base_room(), _base_room(), _base_room()
    r1_u[15:18, 30] = 0
    r2_u[15:18, 30] = 0
    r3_u[15:18, 30] = 205
    u_paths = [
        _write_site_map(tmp_path / "mu", f"u{i}", arr)
        for i, arr in enumerate((r1_u, r2_u, r3_u), 1)
    ]
    out_u = tmp_path / "out" / "master_uncontradicted.yaml"
    assert mmf.main([str(p) for p in u_paths] + ["--min-support", "3", "--write", str(out_u)]) == 0
    assert sma.load_map(out_u).cells[16, 30] == 1


def test_fuse_refuses_invalid_inputs_low_overlap_nonzero_yaw_or_overwrite(tmp_path):
    r1 = _base_room()
    p1 = _write_site_map(tmp_path / "in", "p1", r1)
    p2 = _write_site_map(tmp_path / "in", "p2", _base_room())
    bad_yaw = _write_site_map(tmp_path / "in", "yaw", _base_room(), origin=(-1.5, -1.0, 0.2))
    bad_res = _write_site_map(tmp_path / "in", "res", _base_room(), res=0.02)
    disjoint = _write_site_map(tmp_path / "in", "disjoint", _base_room(), origin=(10.0, 10.0, 0.0))

    assert mmf.main([str(p1)]) == sma.REFUSED
    assert mmf.main([str(p1), str(p1)]) == sma.REFUSED
    assert mmf.main([str(p1), str(tmp_path / "in" / "missing.yaml")]) == sma.REFUSED
    assert mmf.main([str(p1), str(p2), "--min-support", "3"]) == sma.REFUSED
    assert mmf.main([str(p1), str(p2), "--min-support", "0"]) == sma.REFUSED
    assert mmf.main([str(p1), str(bad_yaw)]) == sma.REFUSED
    assert mmf.main([str(p1), str(bad_res)]) == sma.REFUSED
    assert mmf.main([str(p1), str(disjoint)]) == sma.REFUSED
    assert mmf.main([str(p1), str(p2), "--write", str(p1)]) == sma.REFUSED
    assert mmf.main([str(p1), str(p2), "--seal-bundle", str(tmp_path / "b")]) == sma.REFUSED

    out_yaml = tmp_path / "existing.yaml"
    out_yaml.write_text("stub", encoding="utf-8")
    assert mmf.main([str(p1), str(p2), "--write", str(out_yaml)]) == sma.REFUSED

    bundle = tmp_path / "sealed"
    assert mmf.main([str(p1), str(p2), "--seal-bundle", str(bundle), "--name", "m"]) == 0
    assert mmf.main([str(p1), str(p2), "--seal-bundle", str(bundle), "--name", "m"]) == sma.REFUSED
    assert mmf.main([str(p1), str(p2), "--seal-bundle", str(bundle), "--name", "other"]) == sma.REFUSED
