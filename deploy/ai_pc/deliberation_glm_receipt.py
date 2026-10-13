"""Trusted host receipts distinguish included-plan policy from observed charges."""
from dataclasses import asdict, dataclass, replace
import hashlib
import hmac
import json
import math
import re
import time

from rosy.decision.deliberation import canonical, identifier
from . import deliberation_glm_judgment as codec
from rosy.decision.deliberation.profiles import AdapterCapabilities

ENDPOINT = 'https://api.z.ai/api/coding/paas/v4/chat/completions'
MODEL = 'glm-5.3-flash'
POLICY_BASIS = 'https://docs.z.ai/devpack/faq'
CAPABILITIES = AdapterCapabilities('opencode', 'zai-coding-plan/glm-5.3-flash',
    'glm-5.3-flash', 'opencode-1.18.35-json-v2', 2,
    ('line_follow', 'door', 'arm_target'), ('text',), False, False, False)


def status_capabilities():
    return replace(CAPABILITIES, adapter='opencode-1.18.35-status-json-v2', domains=('fleet_status',))


def admission(value):
    if (type(value) is not AdapterCapabilities
            or replace(value, ready=False, isolated=False, cost_verified=False)
            not in (CAPABILITIES, status_capabilities())):
        raise ValueError('EXACT_GLM_RUNTIME_ADMISSION_REQUIRED')
    return value


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def reference(value):
    identifier(value)
    if len(value) > 128 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ValueError('INVALID_PROVIDER_REFERENCE')
    return value


def credential(token, expected):
    actual = hashlib.sha256(token.encode()).hexdigest()
    if (type(expected) is not str or re.fullmatch('[0-9a-f]{64}', expected) is None
            or not hmac.compare_digest(actual, expected)):
        raise ValueError('BILLING_CREDENTIAL_CHANGED')
    return actual


def usage(value):
    fields = {'prompt_tokens', 'completion_tokens', 'total_tokens'}
    if (type(value) is not dict or not fields <= set(value)
            or set(value) - fields - {'completion_tokens_details'}
            or any(type(value[key]) is not int or value[key] < 0 for key in fields)
            or value['completion_tokens'] > 1024
            or value['total_tokens'] != value['prompt_tokens'] + value['completion_tokens']):
        raise ValueError('INVALID_PROVIDER_USAGE')
    details = value.get('completion_tokens_details', {})
    if (type(details) is not dict or set(details) - {'reasoning_tokens'}
            or 'reasoning_tokens' in details and (type(details['reasoning_tokens']) is not int
                or not 0 <= details['reasoning_tokens'] <= value['completion_tokens'])):
        raise ValueError('INVALID_PROVIDER_USAGE')
    return value


def receipt(body, response, *, credential_sha256):
    problem, bound, _, _ = codec.request(json.loads(body))
    payload = codec.result(problem, body, json.loads(response['choices'][0]['message']['content']))
    if response.get('model') != MODEL:
        raise ValueError('INVALID_PROVIDER_MODEL')
    counts = {key: response['usage'][key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    if 'reasoning_tokens' in response['usage'].get('completion_tokens_details', {}):
        counts['completion_tokens_details'] = {
            'reasoning_tokens': response['usage']['completion_tokens_details']['reasoning_tokens']}
    return dict(schema_version=2, job_sha256=digest(json.loads(body)),
        profile_sha256=digest(asdict(bound.profile)), judgment_sha256=digest(payload),
        provider_response_id=reference(response['id']), provider_request_id=reference(response['request_id']),
        credential_sha256=credential_sha256, usage=usage(counts), cost_status='UNKNOWN')


@dataclass(frozen=True)
class TrustedIncludedPlanPolicy:
    """Host composition supplies verified active-plan/account/key evidence.

    Evidence must cover pinned OpenCode, this coding endpoint and no PAYG fallback.
    The credential fingerprint binds the actual gateway key. This input establishes
    included-plan marginal-cash policy, never observed charges or host isolation.
    """
    policy_revision: str
    evidence_sha256: str
    account_ref: str
    key_ref: str
    profile_sha256: str
    valid_until: float
    credential_sha256: str

    def validate(self, profile_sha256):
        for value in (self.policy_revision, self.account_ref, self.key_ref):
            reference(value)
        if (any(type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None
                for value in (self.evidence_sha256, self.profile_sha256, self.credential_sha256))
                or self.profile_sha256 != profile_sha256
                or type(self.valid_until) not in (int, float) or not math.isfinite(self.valid_until)
                or self.valid_until <= time.time()):
            raise ValueError('BILLING_POLICY_NOT_VERIFIED_OR_EXPIRED')


def normalize(body, raw, host, policy, limit, budget):
    problem, bound, _, _ = codec.request(json.loads(body))
    profile_sha = digest(asdict(bound.profile))
    if type(policy) is not TrustedIncludedPlanPolicy:
        raise ValueError('BILLING_POLICY_UNKNOWN')
    policy.validate(profile_sha)
    if (type(raw) is not bytes or len(raw) > limit or type(budget) not in (int, float)
            or not math.isfinite(budget) or not 0 <= budget <= bound.profile.max_cost_usd):
        raise ValueError('INVALID_RECEIPT_BUDGET')
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if any(item.get('type') not in {'text', 'step_start', 'step_finish'} for item in records):
        raise ValueError('CLI_UNEXPECTED_EVENT')
    texts = [item['part']['text'] for item in records if item['type'] == 'text']
    if len(texts) != 1 or sum(item['type'] == 'step_finish' for item in records) != 1:
        raise ValueError('CLI_RESULT_UNKNOWN')
    payload = codec.result(problem, body, json.loads(texts[0]))
    fields = {'schema_version', 'job_sha256', 'profile_sha256', 'judgment_sha256',
              'provider_response_id', 'provider_request_id', 'credential_sha256', 'usage', 'cost_status'}
    if (type(host) is not dict or set(host) != fields | {'state', 'calls'}
            or host['state'] != 'PASS_GLM_PROVIDER_ONLY' or type(host['calls']) is not int or host['calls'] != 1
            or type(host['schema_version']) is not int or host['schema_version'] != 2
            or host['job_sha256'] != digest(json.loads(body)) or host['profile_sha256'] != profile_sha
            or host['judgment_sha256'] != digest(payload) or host['cost_status'] != 'UNKNOWN'
            or host['credential_sha256'] != policy.credential_sha256):
        raise ValueError('GATEWAY_BINDING_UNKNOWN')
    usage(host['usage'])
    reference(host['provider_response_id'])
    reference(host['provider_request_id'])
    normalized = (canonical({'type': 'text', 'part': {'text': canonical(payload)}}) + '\n'
                  + canonical({'type': 'step_finish', 'part': {'cost': 0.0}})).encode()
    if len(normalized) > limit:
        raise ValueError('CLI_RESULT_LIMIT')
    billing = dict(basis='vendor_included_plan', policy_basis=POLICY_BASIS,
        policy_revision=policy.policy_revision, evidence_sha256=policy.evidence_sha256,
        account_ref=policy.account_ref, key_ref=policy.key_ref, endpoint=ENDPOINT,
        marginal_cash_usd=0.0, observed_usd_charge=None, **host)
    return normalized, billing
