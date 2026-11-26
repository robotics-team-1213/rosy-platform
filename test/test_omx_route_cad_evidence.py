"""The offline importer binds image observations to files and emits only verified sites."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
try:
    import omx_route_cad_evidence as cad
    import omx_cad_reference
    import omx_cad_stand
finally:
    sys.path.pop(0)


@pytest.fixture
def reports(tmp_path):
    images = []
    for index in range(3):
        image = tmp_path / f"{index}.png"
        assert cv2.imwrite(str(image), np.full((32,32), index, dtype=np.uint8))
        images.append(image)
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in images[:2]]
    stand = {
        "route": "tmp-b-2-l1", "fit_rgb": images[0].name, "test_rgb": images[1].name,
        "image_sha256": hashes, "heldout_frame_pin_error_px": [1,1,1,1], "center_px": [6,7],
        "images": {"holdout": {"check_error_px": [1,1,1.8]}},
    }
    ship = {
        "sources": {k: {"sha256": h} for k,h in zip((cad.SOURCE,cad.HOLDOUT),hashes)},
        "held_out_sites": [cad.SHIP], "fits": {"pitch38_spacing98": {
            "frames": {cad.SOURCE: {"same_frame_center_px": [13,14]}},
            "common_frozen_holdout": {"fit_source": cad.SOURCE, "holdout_source": cad.HOLDOUT,
                "target": cad.SHIP, "errors": {"n":12,"max_px":0.8}}
        }}
    }
    s, h = tmp_path/"stand.json", tmp_path/"ship.json"
    s.write_text(json.dumps(stand))
    h.write_text(json.dumps(ship))
    return s,h,images


def test_only_binds_verified_fit_and_holdout(reports):
    stand,ship,images = reports
    fragment, warnings = cad.fragment(stand,ship)
    rows = fragment["cad_image_observations"]
    assert rows[cad.SHIP]["camera_reference_sha256"] == hashlib.sha256(images[0].read_bytes()).hexdigest()
    assert rows[cad.STAND]["holdout_max_px"] == 1.8 and not warnings
    with pytest.raises(ValueError, match="distinct"):
        cad.fragment(stand,ship,holdout=images[0])
    with pytest.raises(ValueError, match="hashes"):
        cad.fragment(stand,ship,capture=images[2])
    d = json.loads(ship.read_text())
    d["fits"]["pitch38_spacing98"]["common_frozen_holdout"]["errors"]["max_px"] = True
    ship.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="finite"):
        cad.fragment(stand,ship)


@pytest.mark.parametrize("survivor", [cad.SHIP,cad.STAND,None])
def test_each_site_requires_its_own_reference_evidence(reports,monkeypatch,survivor):
    stand,ship,images = reports
    def mapped(source,ref,centers):
        if list(centers) == [cad.SHIP] and survivor == cad.SHIP:
            return {cad.SHIP:[13.5,14]}, {"local": {cad.SHIP: {"max_residual_px": 2.3}}}
        raise ValueError("local agreement failed")
    def direct(source,ref,xy):
        if survivor == cad.STAND:
            return [6,7.1], {"holdout_max_px": 2.5}
        raise ValueError("no independent landmarks")
    monkeypatch.setattr(omx_cad_reference,"project_centers",mapped)
    monkeypatch.setattr(omx_cad_stand,"project_stand_center",direct)
    if survivor is None:
        with pytest.raises(ValueError, match="no verified site"):
            cad.fragment(stand,ship,images[2])
        return
    data, warnings = cad.fragment(stand,ship,images[2])
    assert list(data["cad_image_observations"]) == [survivor] and warnings
    row = data["cad_image_observations"][survivor]
    assert row["holdout_max_px"] == (2.3 if survivor == cad.SHIP else 2.5)
    assert row["camera_reference_sha256"] == hashlib.sha256(images[2].read_bytes()).hexdigest()
