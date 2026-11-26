import sys
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"/"sim"))
try:
    from omx_cad_stand import project_stand_center
finally:
    sys.path.pop(0)


def fixture(tmp_path, name, *, shift=0, hide=None):
    image = np.full((480,640),182,np.uint8)
    cv2.rectangle(image,(95,379),(141,476),55,-1)
    for i,(x,y) in enumerate([(109,425),(127,425),(108,444),(126,444)]):
        if hide != i:
            cv2.circle(image,(x+shift,y),2,190,-1)
    if hide != "arrow":
        triangle = np.array([[120,390],[117,396],[123,396]], np.int32) + [shift,0]
        cv2.fillConvexPoly(image,triangle.astype(np.int32),193)
    for i,x in enumerate((75,168)):
        if hide != f"roof{i}":
            cv2.circle(image,(x+shift,358),2,55,-1)
    p = tmp_path / name
    assert cv2.imwrite(str(p),image)
    return p


def test_direct_center_with_independent_fixtures(tmp_path):
    src = fixture(tmp_path,"src.png")
    ref = fixture(tmp_path,"ref.png",shift=1)
    center,evidence = project_stand_center(src,ref,[117.5,434.5])
    assert center == pytest.approx([118.5,434.5])
    assert evidence["source_sha256"] != evidence["reference_sha256"]
    assert len(evidence["source"]["independent_errors_px"]) == 3
    assert evidence["max_displacement_px"] == pytest.approx(1)


@pytest.mark.parametrize("hidden", [0,"arrow","roof0","roof1"])
@pytest.mark.parametrize("role", ["source","reference"])
def test_missing_landmark_refuses_either_view(tmp_path, hidden, role):
    src=fixture(tmp_path,"src.png",hide=hidden if role=="source" else None)
    ref=fixture(tmp_path,"ref.png",hide=hidden if role=="reference" else None)
    with pytest.raises(ValueError,match="landmark"):
        project_stand_center(src,ref,[117.5,434.5])


def test_excess_movement_refused(tmp_path):
    with pytest.raises(ValueError):
        project_stand_center(fixture(tmp_path,"src.png"),fixture(tmp_path,"ref.png",shift=6),[117.5,434.5])


def test_right_hand_stand_is_outside_b_fixture(tmp_path):
    path = fixture(tmp_path,"stand.png")
    with pytest.raises(ValueError, match="B-side"):
        project_stand_center(path,path,[520,434])
