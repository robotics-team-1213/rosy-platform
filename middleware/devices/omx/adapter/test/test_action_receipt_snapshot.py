"""The real producer must not mix a cached watermark with later phase events."""
from datetime import timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[5]/'operations/fleet'))
from fleet.server.local_action_transport import UnixLocalActionTransport
from core_common.protocol.schemas import DeviceActionReceipt, FleetActionGrant, FleetCellTransferGrant
from omx_adapter.action_api import ActionApi
from omx_adapter.action_store import ActionStore
from test_omx_action_api import FakePhaseExecution, _cell_transfer_grant, _grant, _runner


def _setup(tmp_path, cell=False):
    kind = 'CELL_TRANSFER' if cell else 'PICK_PLACE'
    grant = (FleetCellTransferGrant.model_validate(_cell_transfer_grant()) if cell
             else FleetActionGrant.model_validate(_grant()))
    store, driver, runner = _runner(tmp_path, phase_runner_factories={kind: lambda grant, recorder: FakePhaseExecution(recorder)})
    runner.submit(grant, peer_uid=1001)
    return grant, store, runner


@pytest.mark.parametrize('cell', [False, True])
def test_phase_writer_between_cached_watermark_and_phase_read_cannot_corrupt_v1_v2_receipt(tmp_path, monkeypatch, cell):
    grant, store, runner = _setup(tmp_path, cell)
    cached = store.get_action(grant.action_id)
    writer = ActionStore(store.path)
    original = store._connect
    committed = []
    class Connection:
        def __init__(self):
            self.actual = original()
        def execute(self, sql, *args):
            if 'SELECT * FROM omx_action_phases' in sql and not committed:
                writer.mark_phase_running(grant.action_id, grant.attempt_id,
                    phase_id='approach', driver_goal_id='ros-goal-approach')
                writer.mark_running(grant.action_id, grant.attempt_id, driver_goal_id='ros-goal-approach')
                committed.append(True)
            return self.actual.execute(sql, *args)
        def close(self):
            self.actual.close()
    monkeypatch.setattr(store, '_connect', Connection)
    response = ActionApi(runner)._success(2 if cell else 1, runner._receipt(cached, created=True))
    # Fleet uses v2 for both kinds; legacy v1 API reads retain their phase-free schema.
    parsed = (UnixLocalActionTransport._parse_receipt(grant, response) if cell else
              DeviceActionReceipt.model_validate(response['receipt']))
    assert committed == [True]
    assert parsed.state == 'ACCEPTED' and parsed.observed_at.isoformat() == cached['updated_at']
    assert parsed.journal_event_id == cached['journal_event_id']
    if cell:
        assert parsed.phase_summaries[0].state == 'ACCEPTED'
        assert parsed.phase_summaries[0].journal_event_id <= parsed.journal_event_id
    assert writer.get_action(grant.action_id)['state'] == 'RUNNING'


def test_cached_parent_state_and_goal_are_refreshed_with_its_watermark(tmp_path):
    grant, store, runner = _setup(tmp_path, True)
    cached = store.get_action(grant.action_id)
    store.mark_phase_running(grant.action_id, grant.attempt_id, phase_id='approach', driver_goal_id='ros-goal-approach')
    store.mark_running(grant.action_id, grant.attempt_id, driver_goal_id='ros-goal-approach')
    receipt = runner._receipt(cached, created=False)
    assert receipt['state'] == 'RUNNING'
    assert receipt['journal_event_id'] == store.latest_event_id(grant.action_id)
    assert receipt['observed_at'] == store.get_action(grant.action_id)['updated_at']


@pytest.mark.parametrize('change', [{'action_id': 'missing'}, {'attempt_id': 'another-attempt'}])
def test_missing_or_changed_attempt_cannot_mint_receipt_from_cached_binding(tmp_path, change):
    grant, store, runner = _setup(tmp_path, True)
    with pytest.raises(PermissionError):
        runner._receipt({**store.get_action(grant.action_id), **change}, created=False)


def test_prepared_without_attempt_remains_a_coherent_empty_phase_read(tmp_path):
    grant = FleetActionGrant.model_validate(_grant())
    store, driver, runner = _runner(tmp_path)
    action = store.create_action(workcell_id=grant.workcell_id, instance_id=grant.instance_id,
        principal_id='fleet-uid-1001', request_key=grant.action_id, action_id=grant.action_id,
        action_kind=grant.action_kind, configuration_revision=grant.config_revision,
        observation_id='obs-1', owner_generation=grant.dispatch_generation,
        payload=grant.model_dump(mode='json'))['action']
    receipt = runner._receipt(action, created=True)
    assert receipt['state'] == 'PREPARED' and receipt['attempt_id'] is None
    assert receipt['phase_summaries'] == [] and receipt['journal_event_id'] == 1


def test_expired_grant_still_allows_read_only_reconciliation_without_resubmit(tmp_path):
    grant, store, runner = _setup(tmp_path, True)
    history = store.history(grant.action_id)
    runner.now = lambda: grant.expires_at+timedelta(seconds=1)
    receipt = runner.get(grant.action_id, peer_uid=1001)
    assert receipt['attempt_id'] == grant.attempt_id and receipt['state'] == 'ACCEPTED'
    assert store.history(grant.action_id) == history
