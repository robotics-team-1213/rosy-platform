"""Protected independent forced-command conversation broker, proposal authority only."""
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time

from rosy.decision.conversation.codec import ConversationInput, Profile, source_policy
from rosy.decision.deliberation import canonical
from .deliberation_conversation import execute
from .deliberation_status_broker import protected
from .conversation_acceptance import source_files, validate as validate_evaluation

CONFIG = Path('/etc/rosy-deliberation/conversation.json')
ROOT = Path(__file__).resolve().parents[2]


def configuration():
    import pwd
    if os.getuid() != pwd.getpwnam('rosy-deliberation').pw_uid:
        raise ValueError('PROTECTED_CONVERSATION_UID_REQUIRED')
    cfg = json.loads(protected(CONFIG))
    if set(cfg) != {'source_commit', 'profile', 'policy', 'valid_until', 'semantic_evidence_sha256', 'files'}:
        raise ValueError('INDEPENDENT_CONVERSATION_HOST_ADMISSION_REQUIRED')
    profile = Profile.model_validate(cfg['profile'])
    if (cfg['policy'] != source_policy(cfg['source_commit'], profile)
            or type(cfg['valid_until']) not in (int, float) or not math.isfinite(cfg['valid_until'])
            or not time.time() < cfg['valid_until']):
        raise ValueError('CONVERSATION_HOST_NOT_ADMITTED')
    if type(cfg['files']) is not dict or not 1 <= len(cfg['files']) <= 1000:
        raise ValueError('CONVERSATION_SOURCE_MANIFEST_REQUIRED')
    if not set(source_files(ROOT)) <= set(cfg['files']):
        raise ValueError('CONVERSATION_SOURCE_CLOSURE_REQUIRED')
    evidence = []
    for name, sha in cfg['files'].items():
        path = ROOT/name
        if not path.resolve().is_relative_to(ROOT):raise ValueError('CONVERSATION_SOURCE_PATH_REFUSED')
        raw = protected(path)
        if hashlib.sha256(raw).hexdigest() != sha:raise ValueError('CONVERSATION_SOURCE_CHANGED')
        if sha == cfg['semantic_evidence_sha256']:evidence.append(raw)
    if len(evidence) != 1:raise ValueError('CONVERSATION_SEMANTIC_EVIDENCE_REQUIRED')
    validate_evaluation(json.loads(evidence[0]), cfg, profile)
    return cfg, profile


async def dispatch(value, cfg, profile):
    if (type(value) is not dict or set(value) != {'schema', 'source_commit', 'profile', 'policy',
            'input_hash', 'question', 'remaining'} or value['schema'] != 'rosy.conversation-request/1'
            or value['source_commit'] != cfg['source_commit'] or value['profile'] != profile.model_dump()
            or value['policy'] != cfg['policy'] or type(value['remaining']) not in (int, float)
            or not math.isfinite(value['remaining']) or not 0 < value['remaining'] <= 30):
        raise ValueError('CONVERSATION_REQUEST_NOT_BOUND')
    question = ConversationInput.model_validate(value['question'])
    if question.digest != value['input_hash']:raise ValueError('CONVERSATION_INPUT_CHANGED')
    result = await asyncio.to_thread(execute, question, profile, value['remaining'])
    return {'source_commit':cfg['source_commit'], 'profile':profile.model_dump(),
            'input_hash':question.digest, 'answer':result, 'cost_usd':0.0}


def main():
    try:
        if len(sys.argv) != 1:raise ValueError('CONVERSATION_ARGUMENTS_REFUSED')
        signal.signal(signal.SIGALRM, lambda *_:(_ for _ in ()).throw(TimeoutError()))
        signal.setitimer(signal.ITIMER_REAL, 30)
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:raise ValueError('CONVERSATION_INPUT_LIMIT')
        value = json.loads(raw)
        if type(value) is dict and value.get('schema') == 'rosy.operator-request/1':
            from . import operator_broker
            cfg, profile = operator_broker.configuration()
            result = asyncio.run(operator_broker.dispatch(value, cfg, profile))
        else:
            cfg, profile = configuration()
            result = asyncio.run(dispatch(value, cfg, profile))
        print(canonical(result), flush=True)
        return 0
    except Exception:
        print('{"state":"HOLD","reason":"CONVERSATION_BROKER_NOT_ADMITTED_OR_RESULT_UNKNOWN"}', flush=True)
        return 1
    finally:signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == '__main__':sys.exit(main())
