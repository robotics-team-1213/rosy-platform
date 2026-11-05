"""Singleton numeric features retain their vector axis before ACT collation."""
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_lerobot_entry import restore_vectors


class TensorShape:
    def __init__(self, shape):
        self.shape = shape

    def reshape(self, shape):
        if math.prod(shape) != math.prod(self.shape):
            raise ValueError('shape changes item count')
        return TensorShape(shape)


@pytest.mark.parametrize('state,action,leading,expected', [
    ((), (), {}, ((1,), (1,))),
    ((), (4,), {'action': (4,)}, ((1,), (4,1))),
    ((2,), (2,), {'observation.state': (2,), 'action': (2,)}, ((2,1), (2,1))),
    ((1,), (4,1), {'action': (4,)}, ((1,), (4,1))),
])
def test_singleton_vector_axes_preserve_temporal_and_batch_prefixes(state,action,leading,expected):
    values = {'observation.state': TensorShape(state), 'action': TensorShape(action)}
    features = {key: {'shape': [1]} for key in values}
    restore_vectors(values,features,leading)
    assert tuple(value.shape for value in values.values()) == expected


def test_existing_vector_and_chunk_shapes_are_unchanged():
    values = {'observation.state': TensorShape((7,)), 'action': TensorShape((4,5))}
    original = dict(values)
    restore_vectors(values, {'observation.state': {'shape': [7]}, 'action': {'shape': [5]}}, {'action': (4,)})
    assert all(values[key] is original[key] for key in values)
