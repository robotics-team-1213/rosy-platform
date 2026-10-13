"""Import and codec readiness only: no provider, credential, marker or device access."""
from importlib.metadata import version
import json
import platform
import sys

from rosy.decision.deliberation import Problem, canonical
from rosy.decision.deliberation.profiles import BoundProfile
from rosy.decision.deliberation.versioned_request import prepare_request
from . import deliberation_glm_judgment as codec
from .deliberation_glm_receipt import CAPABILITIES
from .deliberation_opencode import GlmOpenCodeLauncher

PINS = {'pydantic': '2.13.4', 'pydantic-core': '2.46.4', 'annotated-types': '0.8.0',
        'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4'}


def probe():
    installed = {name: version(name) for name in PINS}
    if (installed != PINS or sys.version_info[:2] != (3, 12) or sys.prefix == sys.base_prefix
            or platform.system() != 'Linux' or platform.machine() != 'x86_64'):
        raise ValueError('V2_DEPENDENCY_CLOSURE_NOT_VERIFIED')
    problem = Problem('synthetic-no-robot', 'import-only', 'probe-v2', 'line_follow', 1,
                      ('synthetic-evidence',), ('human', 'reobserve'), 'INTERVENE')
    bound = BoundProfile(codec.model_profile('import-only-v2'), problem.digest)
    _, raw = prepare_request(problem, bound, (), 30, budget_usd=0)
    parsed, checked, _, rendered = codec.request(json.loads(raw))
    if parsed != problem or checked != bound or rendered.encode() != raw:
        raise ValueError('V2_CODEC_NOT_VERIFIED')
    if any((CAPABILITIES.ready, CAPABILITIES.isolated, CAPABILITIES.cost_verified,
            GlmOpenCodeLauncher.cost_verified)):
        raise ValueError('UNEXPECTED_DEFAULT_ADMISSION')
    return dict(state='PASS_V2_IMPORT_CODEC_ONLY', packages=installed,
                actual_model_calls=0, runtime_admitted=False, cost_verified=False,
                action_admissible=False)


if __name__ == '__main__':
    try:
        print(canonical(probe()))
    except Exception:
        print('{"state":"HOLD","reason":"V2_IMPORT_CODEC_FAILED","actual_model_calls":0}')
        raise SystemExit(1)
