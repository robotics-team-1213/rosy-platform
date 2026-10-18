"""Media sheds load before control traffic and never grows frame queues."""

import importlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def implementation():
    assert (ROOT / 'src/rosy_media_edge/policy.py').is_file(), 'D-789 media degradation policy missing'
    return importlib.import_module('rosy_media_edge.policy')


def test_lost_demand_and_old_encoded_queue_stop_instead_of_adding_delay():
    policy = implementation().MediaPolicy()
    normal = policy.update(demand_age_s=0, queue_age_ms=0, loss_fraction=0, wire_bps=1_000_000)
    assert normal.enabled and (normal.fps, normal.bitrate) == (15, 800_000)
    assert policy.update(demand_age_s=5.1, queue_age_ms=0, loss_fraction=0, wire_bps=0).enabled is False
    old = policy.update(demand_age_s=0, queue_age_ms=201, loss_fraction=0, wire_bps=0)
    assert old.enabled is False and old.reset_idr is True


def test_loss_degrades_fps_and_wire_budget_excess_disables_media():
    policy = implementation().MediaPolicy()
    slow = policy.update(demand_age_s=0, queue_age_ms=0, loss_fraction=.04, wire_bps=1_000_000)
    assert (slow.fps, slow.bitrate) == (10, 550_000)
    slower = policy.update(demand_age_s=0, queue_age_ms=0, loss_fraction=.08, wire_bps=1_000_000)
    assert (slower.fps, slower.bitrate) == (5, 300_000)
    assert policy.update(demand_age_s=0, queue_age_ms=0, loss_fraction=0, wire_bps=1_400_000).enabled is False


def test_malformed_feedback_is_not_clear_evidence():
    policy = implementation().MediaPolicy()
    for field in ['demand_age_s', 'queue_age_ms', 'loss_fraction', 'wire_bps']:
        feedback = dict(demand_age_s=0, queue_age_ms=0, loss_fraction=0, wire_bps=0)
        feedback[field] = float('nan')
        assert policy.update(**feedback).enabled is False
