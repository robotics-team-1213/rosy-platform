import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import omx_occupancy_shadow as occ


def test_held_out_bursts_and_setup_binding(tmp_path):
    k = [[400,0,320],[0,400,240],[0,0,1]]
    factory = dict(depth={"K": k}, K=k, depth_to_colour={"R": np.eye(3).tolist(), "t_m": [0,0,0]})
    (tmp_path/"camera.json").write_text(json.dumps(factory))
    rng = np.random.default_rng(52)
    frame = rng.integers(0,256,(480,640),dtype=np.uint8)
    cv2.imwrite(str(tmp_path/"ref.png"), frame)
    digest = lambda p: hashlib.sha256((tmp_path/p).read_bytes()).hexdigest()
    rois = [[100,100,160,180]]
    binding = dict(camera_id="fixture",rois=rois,reference_sha256=digest("ref.png"),factory_sha256=digest("camera.json"))
    setup = hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    samples=[]
    for i, (label,z) in enumerate([("empty",602),("occupied",570),("empty",601),("occupied",588)]):
        file = f"d{i}.raw"
        receipt = f"r{i}.json"
        rgb = f"rgb{i}.png"
        frame[:4,:4] = i
        cv2.imwrite(str(tmp_path/rgb),frame)
        np.full((480,640),z,dtype="<u2").tofile(tmp_path/file)
        (tmp_path/receipt).write_text(json.dumps(dict(frames=1,raw_sha256=digest(file),
            first_exposure_wall_estimate_s=i+10,exposure_wall_estimate_s=i+10,
            top_stamp=i+10,top_sha256=digest(rgb))))
        samples.append(dict(labels=[label],split="fit" if i<2 else "holdout",depth=file,receipt=receipt,
                            rgb=rgb,rgb_sha256=digest(rgb),setup_sha256=setup))
    doc=dict(samples=samples,rois=rois,camera_id="fixture",factory="camera.json",reference_rgb="ref.png")
    manifest=tmp_path/"manifest.json"
    def evaluate():
        manifest.write_text(json.dumps(doc))
        return occ.evaluate(manifest)
    result=evaluate()
    assert [s["patches"][0]["prediction"] for s in result["samples"][2:]] == ["empty","UNKNOWN"]
    assert not result["motion_authority"] and not result["acceptance_authority"]
    path=tmp_path/"r0.json"
    original=json.loads(path.read_text())
    path.write_text(json.dumps({k:v for k,v in original.items() if k!="top_sha256"}))
    unverified=evaluate()
    assert not unverified["samples"][0]["capture_verified"]
    assert unverified["samples"][2]["patches"][0]["prediction"]=="UNKNOWN"
    path.write_text(json.dumps({**original,"top_sha256":digest("rgb1.png")}))
    with pytest.raises(ValueError,match="differs from paired"):
        evaluate()
    path.write_text(json.dumps(original))
    samples[2]["rgb_stamp_keys"]=["exposure_wall_estimate_s"]
    with pytest.raises(ValueError,match="paired capture"):
        evaluate()
    del samples[2]["rgb_stamp_keys"]
    saved=dict(samples[2])
    samples[2].update(rgb=samples[0]["rgb"],rgb_sha256=samples[0]["rgb_sha256"])
    with pytest.raises(ValueError,match="RGB capture reused"):
        evaluate()
    samples[2]=saved
    samples[2]["setup_sha256"]="other"
    with pytest.raises(ValueError,match="setup"):
        evaluate()
    samples[2]["setup_sha256"]=setup
    samples[2].update(depth=samples[0]["depth"],receipt=samples[0]["receipt"])
    with pytest.raises(ValueError,match="overlapping"):
        evaluate()
    samples[2]["receipt"]="r2.json"
    second=json.loads((tmp_path/"r2.json").read_text())
    second["raw_sha256"]=digest(samples[2]["depth"])
    (tmp_path/"r2.json").write_text(json.dumps(second))
    with pytest.raises(ValueError,match="shares frames"):
        evaluate()


def test_weak_geometry_and_separation_abstain():
    assert occ.predict([600],[590],600) == "UNKNOWN"
    assert occ.predict([None],[570],600) == "UNKNOWN"
    assert occ.predict([600],[570],None) == "UNKNOWN"
    for invalid in ([[0,0,0,1]], [[0,0,11,8],[10,2,11,3]], [[0,0,641,480]], [[False,0,1,1]]):
        with pytest.raises(ValueError,match="ROI|footprint"):
            occ.check_rois(invalid)
