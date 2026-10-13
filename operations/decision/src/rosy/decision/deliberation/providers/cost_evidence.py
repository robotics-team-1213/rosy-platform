"""Project trusted transport billing metadata; never accepts model-authored billing."""

from .. import canonical
from ..contracts.billing import CostEvidence


def project(problem, bound, checked, cost, body, raw):
    if type(raw) is not dict or raw.get('basis') != 'vendor_included_plan':
        raise ValueError('UNSUPPORTED_TRANSPORT_COST_EVIDENCE')
    # The launcher establishes account/key/endpoint policy. Only this allowlist crosses the call boundary.
    if (type(raw.get('schema_version')) is not int or raw['schema_version'] != 2
            or type(raw.get('calls')) is not int or raw['calls'] != 1
            or raw.get('cost_status') != 'UNKNOWN'):
        raise ValueError('TRANSPORT_COST_BINDING_UNKNOWN')
    usage = raw['usage']
    tokens = dict(input_tokens=usage['prompt_tokens'], output_tokens=usage['completion_tokens'], total_tokens=usage['total_tokens'])
    details = usage.get('completion_tokens_details', {})
    if 'reasoning_tokens' in details: tokens['reasoning_tokens'] = details['reasoning_tokens']
    evidence = CostEvidence(canonical(dict(schema='rosy.model.cost_evidence/1', input_hash=problem.digest,
        basis='included_plan', policy_revision=raw['policy_revision'], evidence_sha256=raw['evidence_sha256'],
        credential_sha256=raw['credential_sha256'], job_sha256=raw['job_sha256'],
        profile_sha256=raw['profile_sha256'], judgment_sha256=raw['judgment_sha256'],
        provider_request_id=raw['provider_request_id'], provider_response_id=raw['provider_response_id'],
        usage=tokens, marginal_cash_usd=raw['marginal_cash_usd'], observed_usd_charge=raw['observed_usd_charge'])))
    evidence.validate(problem, bound, checked, cost, body=body)
    return evidence
