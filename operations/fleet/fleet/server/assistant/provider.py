"""Independently admitted Console requests over the existing fixed broker transport."""
from pathlib import Path
import json
import logging
import time
from typing import Literal

from pydantic import Field, FiniteFloat
from rosy.decision.conversation.codec import Strict
from rosy.decision.conversation.operator import OperatorProfile, checked_operator_answer, operator_policy
from rosy.decision.deliberation import canonical
from rosy.decision.conversation.preprocessing import prepare

from ..channel.broker_transport import exchange


class OperatorConfig(Strict):
    host: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$')
    ssh_port: Literal[22, 2222] = 22
    key_file: str = Field(pattern=r'^/run/rosy-deliberation/broker.key$')
    known_hosts_file: str = Field(pattern=r'^/run/rosy-deliberation/known_hosts$')
    source_commit: str = Field(pattern=r'^[0-9a-f]{40}$')
    semantic_evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    valid_until: FiniteFloat
    primary_admitted: bool
    execution_enabled: bool = False

    def admitted(self):
        return self.primary_admitted and time.time() < self.valid_until

    @classmethod
    def load(cls, path, *, optional=False):
        try:
            return cls.model_validate_json(Path(path).read_bytes())
        except FileNotFoundError:
            if optional: return None
            raise ValueError('INVALID_OPERATOR_ASSISTANT_CONFIG') from None
        except (OSError, ValueError):
            raise ValueError('INVALID_OPERATOR_ASSISTANT_CONFIG') from None


class OperatorProvider:
    def __init__(self, config):
        self.config = config

    async def __call__(self, question, remaining):
        cfg = self.config
        if not cfg.admitted():
            raise ValueError('ASSISTANT_NOT_ADMITTED')
        binding = {'source_commit':cfg.source_commit, 'profile':OperatorProfile().model_dump(),
            'input_hash':question.digest, 'semantic_evidence_sha256':cfg.semantic_evidence_sha256}
        packet = canonical(binding | {'schema':'rosy.operator-request/1',
            'policy':operator_policy(cfg.source_commit), 'question':question.model_dump(), 'remaining':remaining}).encode()
        if len(packet) > 65536:
            raise ValueError('ASSISTANT_INPUT_LIMIT')
        try:
            result = await exchange(cfg, 'rosy-conversation-v1', packet, remaining)
        except (ValueError, OSError) as error:
            raise OSError('ASSISTANT_BROKER_RESULT_UNKNOWN') from error
        if (type(result) is not dict or set(result) != set(binding) | {'answer','cost_usd'}
                or any(result[k] != v for k, v in binding.items())
                or type(result['cost_usd']) not in (int, float) or result['cost_usd'] != 0):
            raise ValueError('ASSISTANT_BROKER_IDENTITY_CHANGED')
        answer = checked_operator_answer(result['answer'], question)
        if answer.usage is not None:
            if answer.usage.preparation_hash != prepare(question).digest:
                raise ValueError('ASSISTANT_PREPARATION_CHANGED')
            logging.getLogger('uvicorn.error').info('operator_inference %s', json.dumps({
                'input_hash':question.digest, 'profile':OperatorProfile().revision,
                'source_commit':cfg.source_commit, **answer.usage.model_dump()}, sort_keys=True))
        return answer.model_dump()
