"""Wire-budget evidence comes from counters, including existing bulk/control load."""

import importlib
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def implementation():
    assert (ROOT / 'src/rosy_media_edge/feedback.py').is_file(), 'D-789 wire sampler is missing'
    return importlib.import_module('rosy_media_edge.feedback')


def counters(root, tx, rx):
    path = root / 'wlan0/statistics'
    path.mkdir(parents=True, exist_ok=True)
    (path / 'tx_bytes').write_text(str(tx))
    (path / 'rx_bytes').write_text(str(rx))


def test_wire_budget_counts_both_directions_and_includes_other_robot_traffic(tmp_path):
    module = implementation()
    counters(tmp_path, 0, 0)
    sampler = module.WireSampler('wlan0', root=tmp_path)
    assert sampler.sample(now=0) is None
    for second in range(1, 13):
        counters(tmp_path, second*100000, second*65000)
        assert sampler.sample(now=second) == 1320000
    assert sampler.window_seconds == 10


def test_interface_reset_or_missing_counter_is_unknown_not_zero_load(tmp_path):
    module = implementation()
    counters(tmp_path, 100000, 100000)
    sampler = module.WireSampler('wlan0', root=tmp_path)
    sampler.sample(now=0)
    counters(tmp_path, 200000, 200000)
    assert sampler.sample(now=1) == 1600000
    counters(tmp_path, 0, 0)
    assert sampler.sample(now=2) is None
    (tmp_path / 'wlan0/statistics/tx_bytes').unlink()
    assert sampler.sample(now=3) is None


def test_wire_sampler_rejects_paths_and_counter_clock_regression(tmp_path):
    module = implementation()
    for name in ('../wlan0', '/sys/class/net/wlan0', '..', ''):
        with pytest.raises(ValueError):
            module.WireSampler(name, root=tmp_path)
    counters(tmp_path, 1, 1)
    sampler = module.WireSampler('wlan0', root=tmp_path)
    sampler.sample(now=10)
    assert sampler.sample(now=9) is None
