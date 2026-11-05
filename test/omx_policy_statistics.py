"""Compare persisted processors with train data without overriding loaded stats."""
import numpy as np


def assert_train_statistics(normalizer_stats, unnormalizer_stats, train_stats, heldout_stats):
    for side, actual in [('normalizer', normalizer_stats), ('unnormalizer', unnormalizer_stats)]:
        assert set(actual) == set(train_stats), f'{side}: feature keys differ'
        for feature, expected in train_stats.items():
            assert set(actual[feature]) == set(expected), f'{side}: {feature} statistic keys differ'
            for name, value in expected.items():
                label = f'{side}: {feature}.{name}'
                observed = np.asarray(actual[feature][name], dtype=np.float64)
                expected_value = np.asarray(value, dtype=np.float64)
                assert observed.shape == expected_value.shape, f'{label}: shape differs'
                assert np.isfinite(observed).all() and np.isfinite(expected_value).all(), f'{label}: nonfinite'
                np.testing.assert_allclose(observed, expected_value, rtol=1e-5, atol=1e-6, err_msg=label)
    assert heldout_stats, 'held-out statistics are required to detect leakage'
    for heldout in heldout_stats:
        assert any(not np.allclose(train_stats['action'][name], heldout['action'][name])
                   for name in train_stats['action']), 'held-out action statistics must differ from train'
