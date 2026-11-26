from hashlib import sha256
import json
from pathlib import Path
import sys
import cv2
import numpy as np
import pytest
OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_tray_archive as archive
finally:
    sys.path.pop(0)


def make_reference(folder, gap=10):
    rng=np.random.default_rng(783)
    im=np.full((480,640,3),135,np.uint8)
    texture=rng.integers(0,255,(140,640),dtype=np.uint8)
    im[:140]=cv2.cvtColor(texture,cv2.COLOR_GRAY2BGR)
    mounts=[[442,363],[525,364]]
    for x,y in mounts:
        cv2.circle(im,(x,y),3,(15,15,15),-1)
    model=archive._cad_dots(gap)*1.05+[482,426]
    slots={name:model[4*i:4*i+4].tolist() for i,name in enumerate(archive.LANES)}
    for x,y in np.rint(model).astype(int):
        cv2.circle(im,(x,y),2,(240,240,240),-1)
    data=cv2.imencode(".jpg",im)[1].tobytes()
    (folder/"baseline.jpg").write_bytes(data)
    record=dict(schema=1,arm_id="arm_a",site="temp_plate_a",image_wh=[640,480],
                frame_sha256=sha256(data).hexdigest(),slots=slots,fasteners_px=mounts)
    (folder/"baseline.json").write_text(json.dumps(record))
    return cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR),record


@pytest.mark.parametrize("gap,revision",[(10,"v11"),(.6,"v12")])
def test_archive_revision_and_registration_under_translation(tmp_path,gap,revision):
    im,record=make_reference(tmp_path,gap)
    tx,ty=2,-1
    live=cv2.warpAffine(im,np.float32([[1,0,tx],[0,1,ty]]),(640,480))
    out=archive.registered_slots(live,tmp_path)
    assert out["revision"]==revision and out["status"]=="candidate"
    assert out["revision_held_out_max_px"][revision]<1
    for name,marks in record["slots"].items():
        np.testing.assert_allclose(out["slots"][name]["center_px"],np.mean(marks,axis=0)+[tx,ty],atol=.15)
        assert not out["slots"][name]["physical_acceptance"]


def test_missing_or_moved_fixture_invalidates_registration_with_stationary_camera(tmp_path):
    im,_=make_reference(tmp_path)
    im[350:377,426:456]=135
    assert not archive.registered_slots(im,tmp_path)["slots"]
    im[:140]=0
    assert not archive.registered_slots(im,tmp_path)["slots"]


def test_reject_digest_mismatch_missing_and_ambiguous_dots(tmp_path):
    im,_=make_reference(tmp_path)
    (tmp_path/"baseline.jpg").write_bytes(b"other")
    assert not archive.registered_slots(im,tmp_path)["slots"]
    assert not archive.registered_slots(im,tmp_path/"absent")["slots"]
    ambiguous=(archive._cad_dots(10)+archive._cad_dots(.6))/2
    assert archive._revision(ambiguous)[0] is None


def test_geometrically_valid_metadata_without_observed_archive_marks_rejected(tmp_path):
    im,record=make_reference(tmp_path)
    for marks in record["slots"].values():
        for mark in marks:
            mark[0]+=5
    (tmp_path/"baseline.json").write_text(json.dumps(record))
    assert not archive.registered_slots(im,tmp_path)["slots"]


def test_registered_slots_report_canonical_owner_xy_and_keep_partial_outline_open(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(OMX))
    from cell_fixture_outline import inspect_fixtures

    folder = tmp_path / "fixture-observations/temp_plate_a"
    folder.mkdir(parents=True)
    frame, _ = make_reference(folder)
    config = {"arm_id": "arm_a", "work_dir": str(tmp_path), "sites": {"temp_plate_a": {"surface_z": 0.0}},
              "cameras": {"top": {"height_m": .70, "center_px": [320, 240]}}}
    record = {"homography": [[.001, 0, 0], [0, .001, 0], [0, 0, 1]], "z_view": 0.10}
    fixture = inspect_fixtures(frame, config, {"sites": {"temp_plate_a": record}})["fixtures"]["temp_plate_a"]
    assert fixture["outline_arm_xy_m"] is None
    assert fixture["placement_slots"]["status"] == "candidate"
    for i, lane in enumerate(archive.LANES, start=1):
        row = fixture["placement_slots"]["slots"][lane]
        assert row["slot_id"] == f"temp_a:r{i}-s1"
        assert row["plane_estimate"]["xy_m"] and row["physical_acceptance"] is False
    config["arm_id"] = "arm_b"
    assert not inspect_fixtures(frame, config, {"sites": {}})["fixtures"]
