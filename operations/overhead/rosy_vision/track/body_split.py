"""D-547 addendum: split robots parked side by side out of one baked dark blob.

Robots in adjacent charge bays merge into one dark background blob (a cable or touching
bodies bridge them) that fails the aspect or solidity test, so none was guessed (site
2026-11-05: C1+C2 at aspect 2.18, C3 solidity 0.79). Only a rejected blob is split at its
distance-transform cores, one per robot body, by watershed; every piece then faces the same
footprint, aspect and solidity tests. A strip whose ridge is one line keeps one core and
stays rejected.
"""
from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

#: A core is deeper than this share of the blob's deepest point.
BODY_CORE_SHARE = 0.55


def compact(labels: np.ndarray, stats: np.ndarray, label: int, max_aspect: float, min_solidity: float) -> bool:
    """Minimum-area-rectangle aspect and pixel-count-over-hull solidity of one component."""
    left, top, w, h = (int(stats[label, i]) for i in range(4))
    points = cv2.findNonZero((labels[top:top + h, left:left + w] == label).astype(np.uint8))
    short, long = sorted(cv2.minAreaRect(points)[1])
    hull = cv2.convexHull(points)
    # Hull of pixel centres plus half its perimeter and one: about its pixel count.
    hull_px = cv2.contourArea(hull) + cv2.arcLength(hull, True) / 2 + 1
    return long + 1 <= max_aspect * (short + 1) and int(stats[label, cv2.CC_STAT_AREA]) >= min_solidity * hull_px


def body_pieces(component: np.ndarray) -> list[np.ndarray]:
    """Masks of the bodies in one blob; [] when it has a single core."""
    blob = component.astype(np.uint8)
    depth = cv2.distanceTransform(blob, cv2.DIST_L2, 5)
    cores = (depth >= BODY_CORE_SHARE * float(depth.max())).astype(np.uint8)
    count, markers = cv2.connectedComponents(cores, connectivity=8)
    if count <= 2:
        return []
    markers = markers.astype(np.int32)
    markers[blob == 0] = count  # the outside is its own seed
    cv2.watershed(cv2.cvtColor(blob * 255, cv2.COLOR_GRAY2BGR), markers)
    return [(markers == core) & (blob > 0) for core in range(1, count)]


def split_rejected(count: int, labels: np.ndarray, stats: np.ndarray, centroids: np.ndarray,
                   accepted: Callable[[np.ndarray, np.ndarray, np.ndarray, int], bool]) -> tuple:
    """connectedComponentsWithStats-shaped result with every rejected multi-body blob split."""
    next_label = count
    for label in range(1, count):
        if accepted(labels, stats, centroids, label):
            continue
        pieces = body_pieces(labels == label)
        if pieces:
            labels[labels == label] = 0  # watershed seams belong to no robot
        for piece in pieces:
            labels[piece] = next_label
            next_label += 1
    return (count, labels, stats, centroids) if next_label == count else relabel(labels)


def relabel(labels: np.ndarray) -> tuple:
    """connectedComponentsWithStats-shaped result from a label image whose labels may touch."""
    values = np.unique(labels)
    values = values[values > 0]
    compacted = np.zeros_like(labels)
    stats = np.zeros((len(values) + 1, 5), np.int32)
    centroids = np.zeros((len(values) + 1, 2))
    for index, value in enumerate(values, start=1):
        ys, xs = np.nonzero(labels == value)
        compacted[ys, xs] = index
        stats[index] = (xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1, len(xs))
        centroids[index] = (xs.mean(), ys.mean())
    return len(values) + 1, compacted, stats, centroids
