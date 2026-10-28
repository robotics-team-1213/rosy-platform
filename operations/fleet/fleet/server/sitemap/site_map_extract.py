"""Bounded classical extraction in normalized source pixels, independent of Fleet semantics."""
import hashlib

from core_common.protocol.site_drawing import DrawingExtractionRequest
from fleet.server.site_map_projection import DrawingLimitError, canonical

EXTRACTOR_VERSION = 'rosy.geometry_extraction/1'
MAX_CANDIDATES = 2000
MAX_VERTICES = 50_000
MAX_RESULT_BYTES = 8 * 1024 * 1024


def extract_geometry(path, spec: DrawingExtractionRequest) -> list[dict]:
    import cv2
    import numpy as np
    from PIL import Image
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    with Image.open(path) as image:
        width, height = image.size
        x0, y0, x1, y1 = spec.crop_px
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError('crop is outside normalized raster')
        gray = np.array(image.convert('L').crop((x0, y0, x1, y1)))
    settings = spec.settings
    candidates, vertices = {}, 0

    def add(points, closed, hole=False):
        nonlocal vertices
        geometry = [[int(x) + x0, int(y) + y0] for x, y in points]
        body = {'geometry_px': geometry, 'closed': closed, 'is_hole': hole}
        digest = hashlib.sha256(canonical(body)).hexdigest()[:20]
        if digest in candidates:
            return
        vertices += len(geometry)
        if len(candidates) >= MAX_CANDIDATES or vertices > MAX_VERTICES:
            raise DrawingLimitError('extraction candidate budget exceeded')
        candidates[digest] = {'candidate_id': digest, **body}

    if spec.method == 'lines':
        edges = cv2.Canny(gray, settings.canny_low, settings.canny_high)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, settings.threshold,
            minLineLength=settings.min_line_length_px, maxLineGap=settings.max_gap_px)
        for x1, y1, x2, y2 in [] if lines is None else lines[:, 0]:
            a, b = sorted(((int(x1), int(y1)), (int(x2), int(y2))))
            if a != b:
                add([a, b], False)
    else:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        contours, hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        for index, contour in enumerate(contours):
            points = cv2.approxPolyDP(contour, settings.tolerance_px, True)[:, 0]
            if len(points) >= 3 and cv2.contourArea(points) > 0:
                depth, parent = 0, int(hierarchy[0][index][3])
                while parent >= 0:
                    depth += 1; parent = int(hierarchy[0][parent][3])
                add(points, True, bool(depth % 2))
    result = [candidates[k] for k in sorted(candidates)]
    if len(canonical(result)) > MAX_RESULT_BYTES - 4096:
        raise DrawingLimitError('extraction response budget exceeded')
    return result
