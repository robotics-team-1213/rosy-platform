"""Status brokers use distinct fixed identities without mutating the incident adapters."""
import json

import pytest

from deploy.ai_pc import deliberation_ollama as local
from deploy.ai_pc import deliberation_glm_judgment as reviewer
from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.profiles import BoundProfile
from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation.versioned_request import prepare_request


def question():
    return Problem('fleet', 'request', 'observations-1', 'fleet_status', 1,
        ('e1',), ('human','reobserve'), 'READ_ONLY_QUERY', goal='Read current status',
        facts_json='{"state":"offline"}')


def answer(p, bound):
    return dict(schema_version=2,profile_revision=bound.profile.profile_revision,
        subject_id=p.subject_id,case_id=p.case_id,generation=p.generation,input_hash=p.digest,
        verdict='abstain',alternatives=[{'choice':'human','probability':.5},
        {'choice':'reobserve','probability':.5}],evidence_ids=['e1'],missing_evidence=[],
        objections=['insufficient_evidence'],next_step=None,success_check=None)


def test_status_identities_are_distinct_and_default_admission_stays_off():
    for module in (local,reviewer):
        legacy=module.model_profile('legacy-1')
        status=module.status_model_profile('status-1')
        assert legacy.domains==('line_follow','door','arm_target')
        assert status.domains==('fleet_status',) and status.profile_id!=legacy.profile_id
        assert status.adapter!=legacy.adapter and status.model_id==legacy.model_id
    assert local.status_capabilities().ready is False
    assert local.status_capabilities().isolated is False
    assert local.status_capabilities().cost_verified is False


def test_primary_status_raw_request_and_result_are_bound(monkeypatch):
    p=question();bound=BoundProfile(local.status_model_profile('status-1'),p.digest)
    _,raw=prepare_request(p,bound,(),30,budget_usd=0)
    calls=[]
    def exchange(path,body,remaining):
        calls.append(path)
        if path=='/api/ps':
            return {'models':[{'name':local.MODEL,'model':local.MODEL,'digest':local.DIGEST,'context_length':8192}]}
        assert body['format']['properties']['verdict']['enum']==['do_not_intervene','reobserve','abstain']
        return {'model':local.MODEL,'done':True,'done_reason':'stop','message':{
            'role':'assistant','content':canonical(answer(p,bound))},'prompt_eval_count':10,'eval_count':10}
    monkeypatch.setattr(local,'exchange',exchange)
    result=local.execute(raw,30)
    assert result['judgment']==answer(p,bound) and result['cost_usd']==0
    assert calls==['/api/ps','/api/chat','/api/ps']


def test_reviewer_status_codec_preserves_its_scoped_primary():
    p=question();primary=BoundProfile(local.status_model_profile('primary-1'),p.digest)
    bound=BoundProfile(reviewer.status_model_profile('reviewer-1'),p.digest)
    checked=judgment(p,primary,answer(p,primary))
    # No invented primary choice is passed as a trusted prior.
    _,raw=prepare_request(p,bound,(),30,budget_usd=0)
    parsed,selected,missing,body=reviewer.request(json.loads(raw))
    assert parsed==p and selected==bound and body.encode()==raw
    assert reviewer.result(p,body,answer(p,bound))==answer(p,bound)
    assert checked.choice is None and not missing


def test_direct_bound_profile_cannot_smuggle_an_unadmitted_status_domain():
    p=question()
    wrong=BoundProfile(local.model_profile('legacy-1'),p.digest)
    with pytest.raises(ValueError):prepare_request(p,wrong,(),30,budget_usd=0)


def test_status_glm_launcher_preserves_default_off_and_refuses_old_admission(monkeypatch):
    from deploy.ai_pc import deliberation_opencode as cli
    from deploy.ai_pc import deliberation_glm_receipt as receipt
    class Sandbox:
        def close(self): pass
    monkeypatch.setattr(cli,'SandboxLauncher',lambda *args:Sandbox())
    selected=reviewer.status_model_profile('status-1')
    with cli.GlmOpenCodeLauncher(profile=selected) as launch:
        assert launch.cost_verified is False
        assert launch.adapter_capabilities==receipt.status_capabilities()
    with pytest.raises(ValueError):
        cli.GlmOpenCodeLauncher(profile=selected,admission=receipt.CAPABILITIES)
