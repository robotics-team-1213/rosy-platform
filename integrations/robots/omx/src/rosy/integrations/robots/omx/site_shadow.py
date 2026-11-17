"""D-1024 1 L2: read-only observation of the REAL OMX arm for shadow runs, while the rule_based teacher carries.

Joint state comes from Fleet's display-only ``GET /api/fleet/workcell-observations`` (``read_only: true``) and frames
from the existing signed vision-preview path (a view lease, then ``GET .../frame``). The target holds no lease, has no
``submit``, and its transport refuses every request outside that fixed allow-list, so nothing it can send reaches CORE's
``/api/v1/arm/*``, the owner, an approval window or a lease route. The same CORE/owner authority stays where it was.

Use a viewer / camera-viewer token: this module cannot tell a token's role, so a wider one is not refused here;
the allow-list below limits what the module sends, not what the token could do elsewhere.

Run: ``python -m rosy.integrations.robots.omx.site_shadow`` (mode is always shadow; there is no execute here).
"""
import argparse
import hashlib
from email.utils import parsedate_to_datetime
import math
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
import json

from . import policy_run as run
from . import policy_runner as runner

OBSERVATIONS = '/api/fleet/workcell-observations'
VISION_LEASE = '/api/fleet/vision/lease'
_FRAME = re.compile(r'^/api/vision/sources/[A-Za-z0-9_-]{1,64}/frame$')
_LEASE_BODY_KEYS = {'source_id'}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # A credential never follows a redirect.


def allowed(method, path, body=None):
    """The whole request surface of this module. The one POST only asks Fleet for a signed view lease."""
    if method == 'GET':
        return path == OBSERVATIONS or bool(_FRAME.fullmatch(path))
    return method == 'POST' and path == VISION_LEASE and isinstance(body, dict) and set(body) == _LEASE_BODY_KEYS


class SiteReader:
    def __init__(self, origin, token, *, ca_file=None, timeout=3.0, opener=None):
        parsed = urlsplit(origin)
        loopback = parsed.hostname in ('localhost', '127.0.0.1', '::1')
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/') or parsed.scheme not in ('http', 'https')
                or (parsed.scheme == 'http' and not loopback) or not token or any(c.isspace() for c in token)
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError('https site origin (loopback may be http), credential and positive timeout required')
        self.origin, self._token, self.timeout = origin.rstrip('/'), token, timeout
        context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
        self._open = opener or build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context)).open

    def request(self, method, path, body=None, bearer=None):
        if not allowed(method, path, body):
            raise PermissionError('site shadow reads only: ' + method + ' ' + path.split('?')[0])
        if bearer is not None and (not isinstance(bearer, str) or not bearer.strip()):
            raise PermissionError('a view lease must be a non-empty string')  # never fall back to the site token
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = Request(self.origin + path, data=data, method=method, headers={
            'Authorization': 'Bearer ' + (self._token if bearer is None else bearer), 'Content-Type': 'application/json'})
        with self._open(request, timeout=self.timeout) as response:
            if response.status != 200:
                raise OSError(f'site HTTP {response.status}')
            return response.read(16 * 1024 * 1024), response.headers

    def json(self, method, path, body=None):
        value = json.loads(self.request(method, path, body)[0])
        if not isinstance(value, dict):
            raise ValueError('site object response required')
        return value


def decode_rgb(jpeg, shape):
    """JPEG -> HWC uint8 RGB at the policy's camera shape (cv2 imported here only)."""
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('undecodable frame')
    height, width = shape
    if image.shape[:2] != (height, width):
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(image[:, :, ::-1])


class SiteShadowTarget:
    """Observation only: no ``submit``/``send`` exists, so a loop that tried to act fails with AttributeError."""
    unit = 'ros_joint_rad'

    def __init__(self, reader, *, source_id, joint_names, cameras, policy_type='act', decode=decode_rgb,
                 max_age_s=2.0, clock=time.time, monotonic=time.monotonic):
        if policy_type not in runner.ALLOWED_POLICY_TYPES or not cameras or not joint_names:
            raise ValueError('an allowed policy type, joints and cameras {name: (source_id, (h, w))} required')
        self.reader, self.source_id, self.policy_type = reader, source_id, policy_type
        self.joint_names, self.cameras, self._decode = list(joint_names), dict(cameras), decode
        self.max_age_s, self._clock, self._mono, self._leases = max_age_s, clock, monotonic, {}
        self._last_seq = {}

    def _arm(self):
        snapshot = self.reader.json('GET', OBSERVATIONS)
        if snapshot.get('read_only') is not True:
            raise PermissionError('site observation is not the display-only read model')
        arms = [a for cell in snapshot['workcells'] for a in cell['arms'] if a['source_id'] == self.source_id]
        if len(arms) != 1:
            raise ValueError('exactly one arm with this source id required')
        arm = arms[0]
        if arm.get('fresh') is not True or not isinstance(arm.get('positions'), dict):
            raise OSError('arm observation is not fresh')
        if list(arm['joint_names']) != self.joint_names:
            raise ValueError('arm joint order differs from the policy')
        return arm

    def _frame(self, name):
        source, shape = self.cameras[name]
        lease = self._leases.get(source)
        if lease is None or self._mono() >= lease[0]:
            wire = self.reader.json('POST', VISION_LEASE, {'source_id': source})
            lease = self._leases[source] = (self._mono() + max(0.0, float(wire['expires_in_s']) - 5.0), wire)
        wire = lease[1]
        if not isinstance(wire.get('lease'), str) or not wire['lease'].strip() or not isinstance(wire.get('frame_path'), str):
            self._leases.pop(source, None)
            raise ValueError('vision lease reply is malformed')
        try:
            jpeg, headers = self.reader.request('GET', wire['frame_path'], bearer=wire['lease'])
        except Exception:
            self._leases.pop(source, None)
            raise
        stamp, seq = float(headers['X-Frame-Captured-At']), int(headers['X-Frame-Seq'])
        # Age is judged against the server's own Date header (this host's clock may be skewed); no Date, no frame. A frame whose sequence did not advance is the same frame again.
        date = headers.get('Date')
        if not date:
            raise OSError(f'{name} frame reply has no server Date; freshness cannot be judged')
        now = parsedate_to_datetime(date).timestamp()
        if not math.isfinite(stamp) or now - stamp > self.max_age_s or stamp > now + self.max_age_s:
            raise OSError(f'{name} frame is stale or its clock is wrong')
        if self._last_seq.get(name) is not None and seq <= self._last_seq[name]:
            raise OSError(f'{name} frame sequence did not advance')
        self._last_seq[name] = seq
        if not (jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')):
            raise ValueError('invalid JPEG')
        return self._decode(jpeg, shape), dict(sha256=hashlib.sha256(jpeg).hexdigest(), captured_at=stamp,
                                              seq=headers.get('X-Frame-Seq'))

    def observe(self):
        arm = self._arm()
        positions = [arm['positions'][n] for n in self.joint_names]
        if not all(type(v) in (int, float) and math.isfinite(v) for v in positions):
            raise ValueError('finite joint positions required')
        frames = {name: self._frame(name) for name in self.cameras}
        meta = dict(arm_sequence=arm.get('sequence'), arm_source_age_s=arm.get('source_age_s'),
                    frames={name: m for name, (_, m) in frames.items()})
        return {'positions': positions, 'images': {name: image for name, (image, _) in frames.items()}, 'meta': meta}


def _camera(text):
    name, source, size = text.split('=', 2)
    height, width = (int(v) for v in size.lower().split('x'))
    return name, (source, (height, width))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('--site-url', required=True)
    parser.add_argument('--site-token-file', type=Path, required=True)
    parser.add_argument('--ca-file')
    parser.add_argument('--source-id', required=True, help='Fleet workcell-observation arm source id')
    parser.add_argument('--joints', nargs='+', required=True, help="the policy's joint order")
    parser.add_argument('--camera', action='append', required=True, metavar='NAME=SOURCE_ID=HxW')
    parser.add_argument('--attempt-id', required=True, help='attempts.jsonl id of the teacher carry being shadowed')
    parser.add_argument('--policy-revision', required=True)
    parser.add_argument('--checkpoint-sha256', required=True)
    parser.add_argument('--policy-artifact', type=Path, required=True)
    parser.add_argument('--limits', type=Path, required=True)
    parser.add_argument('--teacher-jsonl', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--steps', type=int, required=True)
    parser.add_argument('--period-s', type=float, default=0.2)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--task', default='')
    args = parser.parse_args(argv)
    if (args.steps < 1 or not math.isfinite(args.period_s) or args.period_s < 0
            or not args.attempt_id.strip() or args.attempt_id != args.attempt_id.strip()):
        raise SystemExit('positive steps, nonnegative period and a trimmed attempt id required')
    limits = json.loads(args.limits.read_text(encoding='utf-8'))
    digest = run.verify_pin(args.checkpoint, args.checkpoint_sha256)  # Before any site or model contact.
    run.bind_policy(args.policy_artifact, args.checkpoint, args.policy_revision)
    cameras = dict(_camera(c) for c in args.camera)
    reader = SiteReader(args.site_url, args.site_token_file.read_text(encoding='utf-8').strip(), ca_file=args.ca_file)
    adapter = run.load_pinned(args.checkpoint, digest, lambda: runner.LeRobotAdapter(
        args.checkpoint, args.device, joint_names=args.joints, cameras=list(cameras), unit='ros_joint_rad'))
    target = SiteShadowTarget(reader, source_id=args.source_id, joint_names=args.joints, cameras=cameras,
                              policy_type=adapter.policy_type)
    header = dict(mode='shadow', real=True, target='site_read_only', attempt_id=args.attempt_id,
                  policy_type=adapter.policy_type, checkpoint_sha256=digest, policy_revision=args.policy_revision,
                  joints=adapter.joint_names, cameras=list(cameras), source_id=args.source_id,
                  task_sha256=hashlib.sha256(args.task.encode()).hexdigest(), n_action_steps=adapter.n_action_steps)
    log = run.RunLog(args.out, header)
    try:
        teacher = run.jsonl_teacher(args.teacher_jsonl) if args.teacher_jsonl else None
        risky = run.shadow(adapter, target, runner.ActionSpace('ros_joint_rad', 'ros_joint_rad'), args.task, limits,
                           log, steps=args.steps, teacher=teacher, period_s=args.period_s)
        return 3 if risky else 0
    finally:
        log.close()


if __name__ == '__main__':
    raise SystemExit(main())
