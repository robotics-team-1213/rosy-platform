import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dataset'))
import qwen_review_completion as completion


BINDING = {'classes': [{'name': 'background', 'index': 0},
                       {'name': 'lane_left', 'index': 1},
                       {'name': 'lane_right', 'index': 2},
                       {'name': 'drivable', 'index': 5}]}


def test_qwen_points_only_inside_unknown_and_human_pixels_survive():
    human = np.array([[0, 255, 255, 5], [0, 255, 255, 5]], dtype=np.uint8)
    predicted = completion.points({'background': [[3, 0], [0, 0]],
                                   'drivable': [[9, 3], [11, 0]]}, human)
    assert predicted == {'background': [[1, 0]], 'drivable': []}
    # A segment can cover known pixels, but compose must never replace them.
    area = np.array([[True, True, False, False], [True, True, False, False]])
    result = completion.compose(human, {'background': area}, BINDING)
    assert np.array_equal(result[human != 255], human[human != 255])
    assert np.array_equal(result[:, 1], np.array([0, 0]))


def test_conflicting_segment_is_rejected():
    human = np.array([[0, 255, 5]], dtype=np.uint8)
    result = completion.compose(human, {'background': np.array([[True, True, True]])}, BINDING)
    assert np.array_equal(result, human)


def test_overlap_between_model_classes_stays_unknown():
    human = np.array([[0, 255, 255, 5]], dtype=np.uint8)
    result = completion.compose(human, {
        'background': np.array([[True, True, True, False]]),
        'drivable': np.array([[False, False, True, True]])}, BINDING)
    assert np.array_equal(result, np.array([[0, 0, 255, 5]], dtype=np.uint8))


def test_qwen_points_reject_malformed_coordinates():
    human = np.full((2, 2), 255, dtype=np.uint8)
    with pytest.raises(ValueError):
        completion.points({'background': [[-1, 0]], 'drivable': []}, human)
    with pytest.raises(ValueError):
        completion.points({'background': [[1.5, 1]], 'drivable': []}, human)
