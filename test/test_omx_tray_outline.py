import cv2
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
try:
    from cell_tray_outline import tray_outline
finally:
    sys.path.pop(0)


def synthetic_fan():
    image=np.empty((160,240,3), np.uint8)
    image[:]=(55,140,175)
    polygon=[[20,159],[54,22],[180,22],[184,36],[148,41],[129,42],
             [112,43],[119,159],[90,159],[113,43],[71,35],[38,159]]
    cv2.fillPoly(image,[np.int32(polygon)],(192,178,138))
    return image


def test_observable_segments_without_closing_partial_or_guessing_depth():
    receipt=tray_outline(synthetic_fan(),(0,0,240,160))
    assert receipt["status"]=="partial" and receipt["clipping_edges"]==["bottom"]
    assert receipt["segments"] and not receipt["outline_px"]
    assert receipt["plane_z_m"] is None and receipt["outline_arm_xy_m"] is None
    assert not receipt["pad_centers_px"] and not receipt["lane_centerlines_px"]
    for edge in receipt["segments"]:
        assert edge["support_px"]>=10 and edge["uncertainty_px"]>=2.5
        assert not all(point[1]==159 for point in edge["points_px"])


def test_roi_clipping_is_distinct_from_actual_frame_clipping():
    f = cv2.copyMakeBorder(synthetic_fan(),0,10,0,0,cv2.BORDER_REPLICATE)
    receipt=tray_outline(f,(0,0,240,160))
    assert receipt["status"]=="partial" and receipt["roi_clipping_edges"]==["bottom"]
    assert not receipt["touches_frame"] and not receipt["clipping_edges"]


def test_uniform_cargo_rectangle_and_ambiguous_second_fixture_rejected():
    f=synthetic_fan()
    pair=np.concatenate((f,f),axis=1)
    assert tray_outline(pair,(0,0,480,160))["status"]=="unverified"
    f[:]=(55,140,175)
    f[20:120,40:180]=(194,175,139)
    assert tray_outline(f,(0,0,240,160))["status"]=="unverified"
