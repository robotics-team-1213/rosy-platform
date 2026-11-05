"""Saved processors must retain train statistics, including joint column order."""
from copy import deepcopy

import pytest

from omx_policy_statistics import assert_train_statistics


@pytest.fixture
def statistics():
    train = {
        'action': {'mean': [1., 2., 3.], 'std': [.1, .2, .3], 'count': [4]},
        'observation.state': {'mean': [4., 5., 6.], 'std': [.4, .5, .6], 'count': [4]},
    }
    heldout = deepcopy(train)
    heldout['action']['mean'] = [21., 22., 23.]
    return train, heldout


def test_accepts_saved_train_statistics(statistics):
    train, heldout = statistics
    assert_train_statistics(deepcopy(train), deepcopy(train), train, [heldout])


@pytest.mark.parametrize('side', ['normalizer', 'unnormalizer'])
def test_accepts_equivalent_scalar_count_serialization(statistics, side):
    train, heldout = statistics
    actual = {'normalizer': deepcopy(train), 'unnormalizer': deepcopy(train)}
    actual[side]['action']['count'] = 4
    assert_train_statistics(actual['normalizer'], actual['unnormalizer'], train, [heldout])


@pytest.mark.parametrize('side', ['normalizer', 'unnormalizer'])
def test_rejects_heldout_statistics_in_either_saved_processor(statistics, side):
    train, heldout = statistics
    actual = {'normalizer': deepcopy(train), 'unnormalizer': deepcopy(train)}
    actual[side] = heldout
    with pytest.raises(AssertionError, match=side):
        assert_train_statistics(actual['normalizer'], actual['unnormalizer'], train, [heldout])


@pytest.mark.parametrize('fault', ['joint_order', 'missing_feature', 'missing_stat', 'shape', 'nan',
                                  'count_value', 'count_shape'])
def test_rejects_corrupt_saved_statistics(statistics, fault):
    train, heldout = statistics
    actual = deepcopy(train)
    if fault == 'joint_order':
        actual['action']['mean'].reverse()
    elif fault == 'missing_feature':
        del actual['observation.state']
    elif fault == 'missing_stat':
        del actual['action']['std']
    elif fault == 'shape':
        actual['action']['mean'] = [[1., 2., 3.]]
    elif fault == 'nan':
        actual['action']['mean'][0] = float('nan')
    elif fault == 'count_value':
        actual['action']['count'] = [5]
    else:
        actual['action']['count'] = [4, 4]
    with pytest.raises(AssertionError, match='normalizer'):
        assert_train_statistics(actual, deepcopy(train), train, [heldout])


def test_refuses_a_fixture_that_cannot_distinguish_heldout_leakage(statistics):
    train, _ = statistics
    with pytest.raises(AssertionError, match='held-out'):
        assert_train_statistics(deepcopy(train), deepcopy(train), train, [deepcopy(train)])


def test_count_only_difference_cannot_hide_an_ineffective_leakage_fixture(statistics):
    train, _ = statistics
    heldout = deepcopy(train)
    heldout['action']['count'] = [100]
    with pytest.raises(AssertionError, match='held-out'):
        assert_train_statistics(deepcopy(train), deepcopy(train), train, [heldout])
