"""D-977 5 (2026-11-17): the host-side operator-attested producer posts PRE_DISPATCH only behind a valid SOURCE_CLEAR."""
import importlib.util
from pathlib import Path

import pytest

from test_device_trial_pre_dispatch_attestation import clear, gated  # noqa: F401
from test_physical_transfer_dispatcher import Port  # noqa: F401
from test_physical_transfer_evidence import geometry, policy  # noqa: F401
from test_physical_transfer_observer_api import TOKEN, approved, rig  # noqa: F401
from test_physical_transfer_store import installation  # noqa: F401
from test_recovery_observer_client import ApiTransport
from test_transfer_observer_client import ASSETS, BASES

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def tool():
    spec = importlib.util.spec_from_file_location('operator_attested_producer',
                                                  ROOT / 'deploy/robot/omx/operator_attested_producer.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NoContext:
    def context(self):
        return None


def test_the_producer_id_is_its_own_and_visible(tool):
    assert tool.PRODUCER_ID == 'operator-attested-producer'


def test_without_a_context_the_producer_reads_nothing_and_posts_nothing(tool):
    def boom():
        raise AssertionError('must not read arm state without an attested context')
    assert tool.observe_once(NoContext(), boom, None, {}, set()) is None


def test_a_foreign_producer_context_is_refused(tool):
    class Foreign:
        def context(self):
            return {'phase': 'PRE_DISPATCH', 'producer_id': 'observer-1'}
    with pytest.raises(PermissionError):
        tool.observe_once(Foreign(), None, None, {}, set())


def test_stale_or_unmoving_live_state_is_refused(tool):
    row = {'t': 100.0, 'state': [0, 0, 0, 0, 0, 100]}
    live = tool.LiveState('arm-a', lambda: row, {'position_m': [0, 0, .2], 'orientation_xyzw': [0, 0, 0, 1]},
                          now=lambda: 100.1, grip_open=56.0)
    with pytest.raises(TimeoutError):  # first read has no previous row to take joint rates from
        live()
    with pytest.raises(TimeoutError):  # same stamp: the session has not advanced
        live()
    row['t'] = 100.1
    state = live()
    assert state['owners']['arm-a']['gripper_state'] == 'OPEN' and state['owners']['arm-a']['held_state'] == 'NONE'
    live.grip_open = None  # no calibrated open value: never claim OPEN
    row['t'] = 100.15
    live.now = lambda: 100.2
    assert live()['owners']['arm-a']['gripper_state'] == 'UNKNOWN'
    live.now = lambda: 200.0
    row['t'] = 100.2
    with pytest.raises(TimeoutError):
        live()


def test_valid_source_clear_lets_the_producer_dispatch_once_with_fk_of_measured_joints(tool, gated, monkeypatch):
    monkeypatch.setattr(tool, 'PRODUCER_ID', gated.installation.policy.producer_id)
    mission = approved(gated)
    client = tool.sim.Client('http://127.0.0.1:8765', TOKEN)
    client.opener = ApiTransport(gated)
    ids = [p.instance_id for p in gated.installation.policy.participants]
    arms = dict(zip(ids, BASES))  # the sim rig installs two arms; the device_trial cell has one
    assert client.context() is None  # no SOURCE_CLEAR: Fleet shows nothing, so the producer cannot act
    assert tool.observe_once(client, None, None, arms, set()) is None
    clear(gated, mission)
    context = client.context()
    base = context['not_before_ns']
    gated.clock[0] = base + 350_000_000
    rows = iter([{'t': (base + 50_000_000) / 1e9, 'state': [0, 0, 0, 0, 0, 100]},
                 {'t': (base + 100_000_000) / 1e9, 'state': [0, 0, 0, 0, 0, 100]},
                 {'t': (base + 200_000_000) / 1e9, 'state': [0, 0, 0, 0, 0, 100]},
                 {'t': (base + 300_000_000) / 1e9, 'state': [0, 0, 0, 0, 0, 100]}])
    live = tool.LiveState(ids[0], lambda: next(rows),
                          {k: list(getattr(gated.installation.policy.source_pose, k)) for k in ('position_m', 'orientation_xyzw')}, now=lambda: base / 1e9 + .4, grip_open=56.0)
    inner = live

    def live():
        state = inner()
        state['owners'] = {i: state['owners'][ids[0]] for i in ids}
        return state
    with pytest.raises(TimeoutError):  # the first poll only primes the joint rates; the next poll posts
        live()
    reply = tool.observe_once(client, live, tool.sim.ArmModel.load(ASSETS), arms, set())
    assert reply['job']['status'] == 'RUNNING'
    assert len(gated.port.submitted) == 1
    assert not gated.attestations.source_clear_valid(mission)
    assert client.context() is None or client.context()['phase'] != 'PRE_DISPATCH'
