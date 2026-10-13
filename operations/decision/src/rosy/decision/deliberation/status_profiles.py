"""D-720 fixed identities; runtime admission is supplied independently."""
from .profiles import ModelProfile
from dataclasses import asdict
import hashlib
from . import canonical

QWEN_DIGEST='0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319'


def profiles(revision):
    return (
        ModelProfile('ollama-status-primary',revision,'primary','local','qwen3-vl:8b-instruct',
            QWEN_DIGEST,
            'ollama-status-json-v2',('fleet_status',),('text',),30,16384,1,0),
        ModelProfile('glm-status-reviewer',revision,'reviewer','opencode',
            'zai-coding-plan/glm-5.3-flash','glm-5.3-flash','opencode-1.18.35-status-json-v2',
            ('fleet_status',),('text',),30,16384,1,10))


def status_query_policy(source_commit,revision):
    return {'revision':'d720-read-only-status-v1','source_commit':source_commit,
        'primary_profile_sha256':hashlib.sha256(canonical(asdict(profiles(revision)[0])).encode()).hexdigest(),
        'domain':'fleet_status','necessity':'READ_ONLY_QUERY','tools':'READ_ONLY',
        'calibration':'EXEMPT_NO_ACTION_OR_MODEL_TEXT_FACTS','action_admissible':False}
