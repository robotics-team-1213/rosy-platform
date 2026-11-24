"""Subject: visible ArUco identifiers for camera annotation, never robot identity.

DICT_4X4_50 is the family used by the dock observer. Recognising TAG 7 alone
does not establish that it is a dock, robot or a valid metric pose.
"""
import cv2
import numpy as np


_ARUCO_BACKEND = None
_ARUCO_DETECTOR = None
_ARUCO_DICT = None


def _get_aruco_detector():
    global _ARUCO_BACKEND, _ARUCO_DETECTOR, _ARUCO_DICT
    aruco = cv2.aruco
    if _ARUCO_BACKEND is not aruco:
        _ARUCO_BACKEND = aruco
        _ARUCO_DICT = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        _ARUCO_DETECTOR = aruco.ArucoDetector(_ARUCO_DICT) if hasattr(aruco, 'ArucoDetector') else None
    return aruco, _ARUCO_DICT, _ARUCO_DETECTOR


def detect_visual_tags(bgr):
    if not hasattr(cv2, 'aruco'):
        return None  # backend unavailable, distinct from no visible tags
    if (not isinstance(bgr, np.ndarray) or bgr.dtype != np.uint8
            or bgr.ndim != 3 or bgr.shape[2] != 3 or bgr.size == 0):
        return None
    aruco, dictionary, detector = _get_aruco_detector()
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if detector is not None:
        corners, ids, _ = detector.detectMarkers(gray)
    else:
        corners, ids, _ = aruco.detectMarkers(gray, dictionary)
    if ids is None:
        return []
    return [dict(tag_id=int(tag_id), corners_px=np.asarray(points).reshape(4, 2).tolist())
            for points, tag_id in list(zip(corners, ids.flatten()))[:8]]
