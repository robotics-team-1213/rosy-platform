"""Direct recognition of B R2 on the 640x480 field camera using its four CAD pins.

The initial axis/pixel scale is specific to the installed top view. Report only the
symmetric centre of the pins, never a robot-frame pose or a floor depth.
"""
from __future__ import annotations

import cv2
import numpy as np

from omx_cad_reference import _read


# r13_temp_slot_plate.scad:46–49 (pin centres), :66 (F3/F4), :149 (arrow centroid).
_PINS = np.array([[-7.99,-8],[7.99,-8],[-7.99,8],[7.99,8]], dtype=float)
_CHECK = np.array([[0,-36 + 2/3],[-40,-65.5],[40,-65.5]], dtype=float)
_CAD = np.vstack((_PINS, _CHECK))
# Seed only, in top-image axes: +y away from arm, either mirror gives the same R2 centre.
_INITIAL_AXES = np.array([[1.155,-0.016],[-0.080,1.17]])


def _feature(image, predicted, kind):
    x, y = np.rint(predicted).astype(int)
    radius = 9 if kind == 'roof' else 8
    x0, y0 = x - radius, y - radius
    if x0 < 0 or y0 < 0 or x+radius >= image.shape[1] or y+radius >= image.shape[0]:
        raise ValueError("stand feature extends outside image")
    crop = image[y0:y+radius+1,x0:x+radius+1]
    mask = crop < 105 if kind == 'roof' else crop > 125
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    size_range = {'roof': (7,27), 'pin': (11,38), 'arrow': (22,56)}[kind]
    candidates = []
    for i in range(1,n):
        xx, yy, w, h, area = stats[i]
        if (xx == 0 or yy == 0 or xx+w == crop.shape[1] or yy+h == crop.shape[0]
                or not size_range[0] <= area <= size_range[1] or not 0.60 <= w/h <= 1.65):
            continue
        component = labels == i
        ring = cv2.dilate(component.astype(np.uint8), np.ones((5,5), np.uint8)).astype(bool) & ~component
        contrast = float(crop[component].mean() - np.median(crop[ring]))
        if (contrast if kind != 'roof' else -contrast) < 40:
            continue
        if kind == 'arrow':
            widths = component[yy:yy+h].sum(axis=1)
            if np.mean(widths[-2:]) <= np.mean(widths[:2]) + 0.5:
                continue
        center = centroids[i] + [x0,y0]
        if np.linalg.norm(center-predicted) <= 5:
            candidates.append(center)
    if len(candidates) != 1:
        raise ValueError(f"stand {kind} landmark missing or ambiguous")
    return candidates[0]


def _locate(image, seed):
    observed = []
    for xy, kind in zip(_CAD @ _INITIAL_AXES + seed, ['pin']*4 + ['arrow','roof','roof']):
        observed.append(_feature(image, xy, kind))
    observed = np.asarray(observed)
    cad = np.column_stack((_CAD,np.ones(len(_CAD))))
    fit = np.linalg.lstsq(cad[:4],observed[:4],rcond=None)[0]
    axes = fit[:2]
    if np.max(np.abs(axes - _INITIAL_AXES)) > 0.12:
        raise ValueError("stand pin axes disagree with top-view geometry")
    error = np.linalg.norm(cad @ fit - observed,axis=1)
    if max(error[:4]) > 0.4 or max(error[4:]) > 3:
        raise ValueError("stand CAD shape disagrees with independent landmarks")
    return fit[-1], observed, {
        "pins_px":observed[:4].tolist(),"arrow_f3_f4_px":observed[4:].tolist(),
        "independent_errors_px":error[4:].tolist(),"pin_fit_max_px":float(max(error[:4])),
    }


def project_stand_center(source_path, reference_path, center_px):
    """Return the reference-image B R2 pin centre and diagnostic evidence from both images."""
    src, source_hash = _read(source_path)
    ref, ref_hash = _read(reference_path)
    seed = np.asarray(center_px,dtype=float)
    if src.shape != (480,640) or ref.shape != src.shape or seed.shape!=(2,) or not np.isfinite(seed).all():
        raise ValueError("stand fallback requires 640x480 field views and a valid seed")
    if seed[0] >= src.shape[1] / 2 or seed[1] < src.shape[0] / 2:
        raise ValueError("stand seed outside B-side fixture region")
    src_center, src_landmarks, a = _locate(src, seed)
    if np.linalg.norm(src_center-seed) > 1.5:
        raise ValueError("source CAD center disagrees with pinned landmarks")
    ref_center, ref_landmarks, b = _locate(ref, src_center)
    drift = np.linalg.norm(src_landmarks-ref_landmarks,axis=1)
    if max(drift)>3:
        raise ValueError("stand landmarks moved beyond 3px")
    return ref_center.tolist(), {"method":"direct_stand_landmarks","source_sha256":source_hash,
        "reference_sha256":ref_hash,"image_wh":[640,480],"source":a,"reference":b,
        "source_center_px":src_center.tolist(),"max_displacement_px":float(max(drift)),
        "holdout_max_px":max(*a["independent_errors_px"],*b["independent_errors_px"])}
