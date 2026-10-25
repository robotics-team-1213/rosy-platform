from types import SimpleNamespace

import pytest

from core_common.protocol.schemas import MissionFeedbackTurnScope
from fleet.server import model_feedback_dispatch
from rosy.decision.deliberation.judgment import judgment, judgment_schema
from rosy.decision.model_tool_catalog import MODEL_TOOL_CATALOG, ToolEffectClass, provider_tool_schemas
from test_model_judgment import bound, payload, problem


def test_incident_projection_does_not_change_mission_provider_catalog():
    assert [tool['name'] for tool in provider_tool_schemas()] == ['get_mission_status', 'propose_replan']
    assert [tool['name'] for tool in provider_tool_schemas(feedback_only=False)] == [
        'get_mission_status', 'propose_replan', 'propose_pick_place']
    tools = provider_tool_schemas(scope='incident')
    assert [tool['name'] for tool in tools] == ['get_incident_status', 'propose_lane_back']
    assert tools[0]['parameters'] == {'type': 'object', 'properties': {}, 'additionalProperties': False}
    assert tools[1]['parameters'] == dict(type='object',
        properties={'rationale': dict(type='string', minLength=1, maxLength=512)},
        required=['rationale'], additionalProperties=False)
    assert MODEL_TOOL_CATALOG['propose_lane_back'].effect_class == ToolEffectClass.CANDIDATE_WRITING
    assert MODEL_TOOL_CATALOG['propose_lane_back'].device_action_api is False


@pytest.mark.parametrize('domain', ['line_follow', 'door'])
def test_mission_tools_are_not_incident_observation_or_success(domain):
    p = problem(domain)
    b = bound(p)
    raw = payload(p)
    raw['next_step']['tool_name'] = 'get_mission_status'
    with pytest.raises(ValueError):
        judgment(p, b, raw)
    schema = judgment_schema(p, b)
    for key in ('next_step', 'success_check'):
        names = {schema['$defs'][entry['$ref'].removeprefix('#/$defs/')]['properties']['tool_name']['const']
                 for entry in schema['properties'][key]['anyOf'] if '$ref' in entry}
        assert names == {'get_incident_status'}


def test_mission_dispatcher_refuses_incident_before_authorization_or_read(monkeypatch):
    tool = SimpleNamespace(scope='incident', feedback_enabled=True, effect_class=ToolEffectClass.READ_ONLY)
    monkeypatch.setattr(model_feedback_dispatch, 'MODEL_TOOL_CATALOG', {'get_incident_status': tool})
    def forbidden(*args):
        pytest.fail('incident tool must not touch Mission authorization or evidence')
    dispatcher = model_feedback_dispatch.MissionFeedbackToolDispatcher(
        mission_service=object(), progress_service=object(), proposal_store=object(), authorization_check=forbidden)
    scope = MissionFeedbackTurnScope.model_validate(dict(principal_id='operator', workcell_id='cell',
        mission_id='mission', action_id='action', attempt_id='attempt', dispatch_generation=1,
        event_watermark=1, model_policy_revision='p1', outcome_policy='STATUS_ONLY'))
    result = dispatcher.dispatch(scope=scope, call_id='incident-read', tool_name='get_incident_status', arguments={})
    assert result.status == 'rejected' and result.reason_code == 'TOOL_NOT_ALLOWED'
