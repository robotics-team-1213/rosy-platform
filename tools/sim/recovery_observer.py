"""Independent recovery fact ingress only; never requests, approves or dispatches a child."""
import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sys
from time import time_ns
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'contracts/foundation'))
from core_common.protocol.arm_transfer_recovery import (
    ArmTransferRecoveryContext, ArmTransferRecoveryContextResponse,
    ArmTransferRecoveryObservationRequest, ArmTransferRecoveryObservationReply,
)

LIMIT = 4 * 1024 * 1024
CONTEXT = '/api/fleet/arm-transfers/recovery-context'


class SubmissionUnconfirmed(RuntimeError):
    """The POST outcome needs operator reconciliation, never an automatic retry."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _json(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate observation JSON key')
            result[key] = value
        return result

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('nonfinite observation number')
        return number

    def constant(value):
        raise ValueError('nonfinite observation constant')

    if not raw or len(raw) > LIMIT:
        raise ValueError('bounded nonempty observation JSON required')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                      parse_float=finite, parse_constant=constant)


def _read(path):
    path = Path(path)
    if not path.is_file() or any(p.is_symlink() for p in (path.absolute(), *path.absolute().parents)):
        raise ValueError('regular observation file without links required')
    with path.open('rb') as stream:
        return _json(stream.read(LIMIT + 1))


def _origin(value):
    if (not isinstance(value, str) or len(value) > 2048
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or any(c in value for c in '\\?#')):
        raise ValueError('explicit HTTPS origin or HTTP loopback origin required')
    url = urlsplit(value)
    port, host = url.port, url.hostname
    if (url.scheme not in ('https', 'http') or not host or url.username is not None or url.password is not None
            or url.path not in ('', '/') or url.netloc.endswith(':') or port == 0
            or (url.scheme == 'http' and (host not in ('localhost', '127.0.0.1', '::1') or port is None))):
        raise ValueError('HTTPS or explicit HTTP loopback origin without credentials required')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
                   for part in host.split('.')):
            raise ValueError('valid observation destination hostname required') from None
    return value.rstrip('/')


def build_request(context, observations, *, now_ns):
    context = ArmTransferRecoveryContext.model_validate(context)
    body = ArmTransferRecoveryObservationRequest.model_validate(dict(purpose='RECOVERY_RESET',
        expected_proposal_digest=context.proposal_digest, observations=observations))
    times = []
    owners = {(o.workcell_id, o.instance_id): o for o in context.context.owners}
    bindings = ('producer_id', 'evaluator_revision', 'frame_id', 'policy_digest', 'catalog_digest',
                'bindings_digest', 'object_ref', 'object_origin_id')
    for sample in body.observations:
        if (any(getattr(sample, key) != getattr(context, key) for key in bindings)
                or sample.action_id != context.context.action_id or sample.attempt_id != context.context.attempt_id
                or {(o.workcell_id, o.instance_id) for o in sample.owners} != set(owners)):
            raise ValueError('source observation differs from recovery context')
        stamps = [sample.object_observed_at_ns]
        for owner in sample.owners:
            target = owners[owner.workcell_id, owner.instance_id]
            if (owner.journal_id, owner.owner_session_id) != (target.journal_id, target.owner_session_id):
                raise ValueError('source observation differs from owner context')
            stamps += [owner.links_observed_at_ns, owner.gripper_observed_at_ns]
            if owner.joints is not None:
                stamps.append(owner.joints.observed_at_ns)
        if any(t <= context.context.not_before_ns or t > now_ns or now_ns - t > context.max_age_ns for t in stamps):
            raise ValueError('source capture time is stale, future or before the recovery request')
        times.append(stamps)
    first, second = body.observations
    if (first.evidence_id == second.evidence_id or first.sequence >= second.sequence
            or min(times[1]) - max(times[0]) < context.min_separation_ns):
        raise ValueError('distinct ordered separated source observations required')
    return body.model_dump(mode='json')


class Client:
    def __init__(self, origin, token):
        self.origin = _origin(origin)
        if (not isinstance(token, str) or not 32 <= len(token) <= 512 or token != token.strip()
                or any(ord(c) < 32 or ord(c) >= 127 for c in token)):
            raise ValueError('independent observer credential required')
        self._token = token
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, path, body=None):
        headers = {'X-Physical-Observation-Token': self._token}
        raw = None
        if body is not None:
            raw = json.dumps(body, allow_nan=False).encode()
            headers.update({'Origin': self.origin, 'Content-Type': 'application/json'})
        with self.opener.open(Request(self.origin + path, data=raw, headers=headers), timeout=10) as response:
            return _json(response.read(LIMIT + 1))

    def context(self):
        result = ArmTransferRecoveryContextResponse.model_validate(self._request(CONTEXT))
        return result.model_dump(mode='json')['context']

    def save_context(self, output):
        output = Path(output)
        resolved = output.resolve()
        if (any((p / '.git').exists() for p in (resolved, *resolved.parents))
                or any(p.is_symlink() for p in output.absolute().parents)):
            raise ValueError('context output must stay outside source checkouts and links')
        if output.exists() or output.is_symlink():
            raise FileExistsError(output)
        context = self.context()
        if context is None:
            raise ValueError('no pending recovery observation context')
        raw = (json.dumps({'context': context}, allow_nan=False, indent=2) + '\n').encode()
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return context

    def submit(self, context, observations):
        saved = ArmTransferRecoveryContext.model_validate(context).model_dump(mode='json')
        if self.context() != saved:
            raise ValueError('pending recovery context changed; collect new observations')
        body = build_request(saved, observations, now_ns=time_ns())
        path = f"/api/fleet/arm-transfers/jobs/{saved['mission_id']}/recovery/{saved['request_id']}/observations"
        try:
            reply = self._request(path, body)
            return ArmTransferRecoveryObservationReply.model_validate(reply).model_dump(mode='json')
        except Exception:
            raise SubmissionUnconfirmed('observation submission unconfirmed; operator must reconcile before retry') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('context').add_argument('--out', required=True, type=Path)
    submit = commands.add_parser('submit')
    submit.add_argument('--context', required=True, type=Path)
    submit.add_argument('--samples', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        client = Client(args.origin, os.environ.get('ROSY_TRANSFER_OBSERVER_TOKEN', ''))
        if args.command == 'context':
            result = {'context': client.save_context(args.out)}
        else:
            saved = ArmTransferRecoveryContextResponse.model_validate(_read(args.context))
            result = client.submit(saved.context, _read(args.samples))
    except SubmissionUnconfirmed:
        parser.exit(2, 'observation result unconfirmed; use the operator preview to reconcile; no automatic retry\n')
    except HTTPError as error:
        parser.exit(2, f'observer HTTP {error.code}; verify configured access/context\n')
    except (OSError, ValueError, RecursionError):
        parser.exit(2, 'observer refused input or transport; verify configured access and source observations\n')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
