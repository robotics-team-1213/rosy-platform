"""Register a measured empty A tray to the current top-camera view for display."""
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path

import cv2
import numpy as np

LANES = ("R1", "R2", "R3")


def _cad_dots(gap_mm):
    # temp_slot_plate.scad v11/v12: arm_r=200, pk_l=96, pin_dw=7.99, pin_dl=8.
    angle = 2 * math.asin((30.8 + 96 * math.tan(math.radians(3)) + gap_mm) / 304)
    dots = []
    for theta in (-angle, 0, angle):
        c, s = math.cos(theta), math.sin(theta)
        rotation = np.array([[c, -s], [s, c]])
        lane = [[x, y+200] for y in (-8, 8) for x in (-7.99, 7.99)]
        dots.extend(np.array(lane) @ rotation.T - [0, 200])
    return np.float32(dots)


def _revision(dots):
    residuals = {}
    for revision, gap in (("v11", 10), ("v12", .6)):
        model = _cad_dots(gap)
        errors = []
        for lane in range(3):
            keep = np.arange(12)//4 != lane
            h, _ = cv2.findHomography(model[keep], dots[keep], 0)
            if h is None:
                return None, {}
            projected = cv2.perspectiveTransform(model[~keep, None], h)[:, 0]
            errors.extend(np.linalg.norm(projected-dots[~keep], axis=1))
        residuals[revision] = round(float(max(errors)), 3)
    best, second = sorted(residuals, key=residuals.get)
    unique = residuals[best] <= 2 and residuals[second]-residuals[best] >= 3
    return best if unique else None, residuals


def _background(gray):
    # The surveyed top strip contains static surroundings. Exclude the moving belt.
    mask = np.zeros(gray.shape, np.uint8)
    mask[:140] = 255
    mask[:,264:366] = 0
    return cv2.SIFT_create().detectAndCompute(gray, mask)


@lru_cache(maxsize=4)
def _reference(folder, json_version, image_version):
    record = json.loads((folder/"baseline.json").read_bytes())
    data = (folder/"baseline.jpg").read_bytes()
    if (record["schema"] != 1 or record["site"] != "temp_plate_a" or record["arm_id"] != "arm_a"
            or record["frame_sha256"] != sha256(data).hexdigest() or record["image_wh"] != [640, 480]):
        raise ValueError("reference_identity")
    gray = cv2.imdecode(np.frombuffer(data,np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None or gray.shape!=(480,640):
        raise ValueError("reference_image")
    dots = np.float32([record["slots"][n] for n in LANES])
    mounts = np.array(record["fasteners_px"],dtype=float)
    if dots.shape != (3,4,2) or mounts.shape != (2,2) or not np.isfinite(dots).all() or not np.isfinite(mounts).all():
        raise ValueError("reference_marks")
    for x, y in np.vstack((dots.reshape(-1,2),mounts)):
        if not (7<=x<633 and 6<=y<474):
            raise ValueError("reference_marks_outside")
    # A valid CAD fit alone could be produced by model-predicted points.
    # Every saved location must still coincide with a bright dot on the empty dark pad.
    for x,y in np.rint(dots.reshape(-1,2)).astype(int):
        window = gray[y-4:y+5,x-4:x+5]
        surround = np.concatenate((window[0],window[-1],window[1:-1,0],window[1:-1,-1]))
        if window[3:6,3:6].mean()-np.median(surround)<25:
            raise ValueError("pad_mark_not_visible")
    centers = dots.mean(axis=1)
    revision, errors = _revision(dots.reshape(-1,2))
    if revision is None:
        raise ValueError("ambiguous_fixture_revision")
    marks = []
    for x,y in np.rint(mounts).astype(int):
        patch = gray[y-5:y+6,x-6:x+7]
        if float(patch.std())<10:
            raise ValueError("blank_mount")
        marks.append(patch)
    keypoints, descriptors = _background(gray)
    return record["frame_sha256"], revision, errors, centers, mounts, marks, keypoints, descriptors


def _reject(reason):
    return {"status":"unverified", "reason":reason, "revision":None, "slots":{}, "physical_acceptance":False}


def registered_slots(frame_bgr, reference_dir):
    """Read a private hash-bound template. Missing or ambiguous support suppresses all candidates."""
    if reference_dir is None or frame_bgr is None or frame_bgr.shape != (480,640,3):
        return _reject("missing_reference_or_unrecognized_view")
    try:
        folder = Path(reference_dir)
        def version(filename):
            stat=(folder/filename).stat()
            return stat.st_size,stat.st_mtime_ns
        digest, revision, errors, centers, mounts, patches, keypoints, descriptors = _reference(
            folder,version("baseline.json"),version("baseline.jpg"))
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        current, current_descriptors = _background(gray)
        if descriptors is None or current_descriptors is None or len(current)<2:
            return _reject("insufficient_background")
        pairs = cv2.BFMatcher().knnMatch(descriptors,current_descriptors,k=2)
        good=[a for a,b in pairs if a.distance < .74*b.distance]
        if len(good)<30:
            return _reject("insufficient_background_matches")
        src=np.float32([keypoints[m.queryIdx].pt for m in good])
        dst=np.float32([current[m.trainIdx].pt for m in good])
        affine, mask=cv2.estimateAffinePartial2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=2)
        if affine is None or mask is None or int(mask.sum())<30:
            return _reject("insufficient_background_inliers")
        inliers=mask.ravel().astype(bool)
        if np.ptp(src[inliers,0])<120 or np.ptp(src[inliers,1])<35:
            return _reject("narrow_background_coverage")
        def project(points):
            return points @ affine[:,:2].T + affine[:,2]
        background_error=float(np.quantile(np.linalg.norm(project(src[inliers])-dst[inliers],axis=1),.95))
        if background_error>1.75:
            return _reject("background_residual_exceeded")
        predictions=project(mounts)
        observed=[]
        checks=[]
        for predicted, patch in zip(predictions, patches):
            i,j=np.rint(predicted).astype(int)
            if i<13 or i>=gray.shape[1]-13 or j<12 or j>=gray.shape[0]-12:
                return _reject("mount_outside_frame")
            scores=cv2.matchTemplate(gray[j-11:j+12,i-12:i+13],patch,cv2.TM_CCOEFF_NORMED)
            _,score,_,(dx,dy)=cv2.minMaxLoc(scores)
            scores[max(0,dy-2):dy+3,max(0,dx-2):dx+3] = -1
            if score-float(scores.max())<.12:
                return _reject("ambiguous_mount_match")
            found=np.array([i-6+dx,j-6+dy])
            error=float(np.linalg.norm(found-predicted))
            if not math.isfinite(score) or score<.8 or error>3:
                return _reject("mount_alignment_unverified")
            observed.append(found)
            checks.append({"center_px":found.tolist(),"score":round(score,3),"residual_px":round(error,3)})
        # The mounts confirm that the rigid fixture remains at the predicted location.
        # Fit neither depth nor a perspective transform to just two coplanar witnesses.
        observed=np.float32(observed)
        differential=float(np.linalg.norm((observed[1]-observed[0])-(predictions[1]-predictions[0])))
        if differential>2:
            return _reject("mount_spacing_changed")
        estimate=project(centers)
        if np.any(estimate<0) or np.any(estimate>=[gray.shape[1],gray.shape[0]]):
            return _reject("candidate_outside_frame")
        allowance=round(1+background_error+max(k["residual_px"] for k in checks)+differential,2)
        return {"status":"candidate","revision":revision,"revision_held_out_max_px":errors,
                "archive_sha256":digest,"physical_acceptance":False,
                "registration":{"background_inliers":int(mask.sum()),"background_p95_px":round(background_error,3),
                                "mounts":checks,"mount_spacing_residual_px":round(differential,3)},
                "slots":{lane:{"center_px":point.round(2).tolist(),"uncertainty_px":allowance,
                               "source":"registered_empty_fixture","physical_acceptance":False}
                         for lane,point in zip(LANES,estimate)}}
    except (OSError, ValueError, TypeError, KeyError, cv2.error, OverflowError):
        return _reject("missing_or_invalid_archive")
