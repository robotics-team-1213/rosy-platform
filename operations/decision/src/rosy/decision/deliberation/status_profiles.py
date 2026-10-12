"""D-720 fixed identities; runtime admission is supplied independently."""
from .profiles import ModelProfile


def profiles(revision):
    return (
        ModelProfile('ollama-status-primary',revision,'primary','local','qwen3-vl:8b-instruct',
            '0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319',
            'ollama-status-json-v2',('fleet_status',),('text',),30,16384,1,0),
        ModelProfile('glm-status-reviewer',revision,'reviewer','opencode',
            'zai-coding-plan/glm-5.3-flash','glm-5.3-flash','opencode-1.18.35-status-json-v2',
            ('fleet_status',),('text',),30,16384,1,10))
