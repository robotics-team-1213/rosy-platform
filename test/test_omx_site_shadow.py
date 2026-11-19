"""D-1024 1 L2: the real-arm shadow target is observation only; every request it can make is a Fleet read."""
import json
from email.utils import formatdate
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'integrations/robots/omx/src'), str(ROOT / 'contracts/learning/src')]
from rosy.integrations.robots.omx import policy_run as run  # noqa: E402
from rosy.integrations.robots.omx import policy_runner as runner  # noqa: E402
from rosy.integrations.robots.omx import site_shadow as site  # noqa: E402

JOINTS = ['joint1', 'joint2']
JPEG = b'\xff\xd8fake\xff\xd9'
LIMITS = {n: {'min': -1.0, 'max': 1.0, 'step': 0.1} for n in JOINTS}


class Reply:
    def __init__(self, body, headers=None, status=200):
        self.body, self.headers, self.status = body, headers or {}, status

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Site:
    """Fake Fleet: records (method, path); any other request would be a test failure."""

    def __init__(self, *, read_only=True, fresh=True, stamp=1000.0, joints=None):
        self.calls, self.read_only, self.fresh, self.stamp = [], read_only, fresh, stamp
        self.joints = joints or JOINTS

    def __call__(self, request, timeout):
        path = request.full_url.split('//', 1)[1].split('/', 1)[1]
        path = '/' + path
        self.calls.append((request.get_method(), path))
        if path == site.OBSERVATIONS:
            arm = dict(source_id='omx_b', joint_names=self.joints, fresh=self.fresh, sequence=7, source_age_s=0.1,
                       positions={'joint1': 0.1, 'joint2': -0.2} if self.fresh else None)
            return Reply(json.dumps({'read_only': self.read_only, 'workcells': [{'arms': [arm]}]}).encode())
        if path == site.VISION_LEASE:
            assert json.loads(request.data) == {'source_id': 'top'}
            return Reply(json.dumps({'lease': 'tok', 'frame_path': '/api/vision/sources/top/frame',
                                     'expires_in_s': 60}).encode())
        assert path == '/api/vision/sources/top/frame' and request.get_header('Authorization') == 'Bearer tok'
        return Reply(JPEG, {'X-Frame-Captured-At': str(self.stamp), 'X-Frame-Seq': '3',
                            'Date': formatdate(1000.5, usegmt=True)})


def make(fake, **kwargs):
    reader = site.SiteReader('https://fleet.example', 'viewer-token', opener=fake)
    return site.SiteShadowTarget(reader, source_id='omx_b', joint_names=JOINTS,
                                 cameras={'top': ('top', (2, 2))}, decode=lambda jpeg, shape: ('img', shape),
                                 clock=lambda: 1000.5, **kwargs)


def test_observation_reads_joint_state_and_frames_with_hashes():
    fake = Site()
    seen = make(fake).observe()
    assert seen['positions'] == [0.1, -0.2] and seen['images'] == {'top': ('img', (2, 2))}
    frame = seen['meta']['frames']['top']
    assert len(frame['sha256']) == 64 and frame['seq'] == '3' and seen['meta']['arm_sequence'] == 7
    assert set(fake.calls) == {('GET', site.OBSERVATIONS), ('POST', site.VISION_LEASE),
                               ('GET', '/api/vision/sources/top/frame')}


def test_target_has_no_way_to_command_and_shadow_never_calls_one():
    target = make(Site())
    assert not any(hasattr(target, n) for n in ('submit', 'send', 'send_action', 'client', 'stop', 'act'))
    with pytest.raises(AttributeError):
        runner.step(type('A', (), dict(joint_names=JOINTS, unit='ros_joint_rad', policy_type='act',
                                       preprocess=lambda s, o, t: o, infer=lambda s, b: [0.1, 0.1],
                                       postprocess=lambda s, a: a))(),
                    target, runner.ActionSpace('ros_joint_rad', 'ros_joint_rad'), '')


@pytest.mark.parametrize('method,path,body', [
    ('POST', '/api/v1/arm/actions', {'x': 1}), ('POST', '/api/v1/arm/stop', None), ('GET', '/api/v1/arm/policy', None),
    ('POST', '/api/v1/arm/observations', {}), ('POST', '/api/v1/arm/lease', {}),
    ('POST', '/api/fleet/policy-approvals', {}), ('POST', '/api/fleet/policy-approvals/a/approve', None),
    ('POST', '/api/fleet/workcells/w/policy/lease', {}), ('PUT', site.OBSERVATIONS, {}),
    ('DELETE', site.OBSERVATIONS, None), ('GET', site.OBSERVATIONS + '?x=1', None),
    ('POST', site.VISION_LEASE, {'source_id': 'top', 'measured': {}}), ('POST', site.VISION_LEASE, None),
    ('GET', '/api/vision/sources/../arm/frame', None), ('POST', '/api/vision/sources/top/frame', {})])
def test_transport_refuses_everything_outside_the_read_allow_list(method, path, body):
    fake = Site()
    with pytest.raises(PermissionError):
        site.SiteReader('https://fleet.example', 't', opener=fake).request(method, path, body)
    assert fake.calls == []


def test_the_only_api_paths_in_the_module_are_fleet_reads():
    import re
    code = Path(site.__file__).read_text(encoding='utf-8').split('"""', 2)[2]
    assert set(re.findall(r"'(/api/[^']*)'", code)) <= {site.OBSERVATIONS, site.VISION_LEASE,
                                                       '^/api/vision/sources/[A-Za-z0-9_-]{1,64}/frame$'}
    assert 'core_arm_client' not in code and 'CoreArmClient' not in code and '/api/v1' not in code


@pytest.mark.parametrize('fake,error', [
    (Site(read_only=False), PermissionError), (Site(fresh=False), OSError), (Site(stamp=990.0), OSError),
    (Site(stamp=1010.0), OSError), (Site(joints=['joint2', 'joint1']), ValueError)])
def test_stale_unfresh_or_mismatched_observations_are_refused(fake, error):
    with pytest.raises(error):
        make(fake).observe()


def test_reader_origin_and_policy_type_checks():
    with pytest.raises(ValueError):
        site.SiteReader('http://fleet.example', 't')
    with pytest.raises(ValueError):
        site.SiteReader('https://u:p@fleet.example', 't')
    with pytest.raises(ValueError):
        site.SiteShadowTarget(None, source_id='a', joint_names=JOINTS, cameras={'top': ('t', (2, 2))},
                              policy_type='diffusion')


def test_shadow_log_binds_observation_and_counts_no_commands(tmp_path):
    class Adapter:
        joint_names, unit, policy_type, n_action_steps = JOINTS, 'ros_joint_rad', 'act', 1
        preprocess = lambda self, o, t: o
        infer = lambda self, b: [0.15, -0.2]
        postprocess = lambda self, a: runner.check_output(a, JOINTS)

    log = run.RunLog(tmp_path / 'l.jsonl', dict(mode='shadow', attempt_id='att-1', checkpoint_sha256='a' * 64))
    risky = run.shadow(Adapter(), make(Site()), runner.ActionSpace('ros_joint_rad', 'ros_joint_rad'), '', LIMITS, log,
                       steps=1, teacher=lambda: [0.12, -0.2])
    log.close()
    lines = [json.loads(x) for x in (tmp_path / 'l.jsonl').read_text().splitlines()]
    assert risky == 0 and lines[0]['attempt_id'] == 'att-1' and lines[0]['checkpoint_sha256'] == 'a' * 64
    step = lines[1]
    assert step['teacher_max_abs_diff'] == pytest.approx(0.03) and step['risks'] == []
    assert step['observed']['frames']['top']['sha256'] and step['observed_positions'] == [0.1, -0.2]
    assert lines[-1]['sent_commands'] == 0


def test_frame_age_is_judged_by_the_server_date_so_a_skewed_local_clock_still_works():
    fake = Site(stamp=1000.0)
    original = fake.__call__

    def with_date(request, timeout):
        reply = original(request, timeout)
        if request.full_url.endswith('/frame'):
            reply.headers['Date'] = 'Thu, 01 Jan 1970 00:16:41 GMT'  # 1001 s: the server says the frame is 1 s old
        return reply
    reader = site.SiteReader('https://fleet.example', 't', opener=with_date)
    target = site.SiteShadowTarget(reader, source_id='omx_b', joint_names=JOINTS, cameras={'top': ('top', (2, 2))},
                                   decode=lambda j, s: 'img', clock=lambda: 1004.5)  # local clock 4.5 s ahead
    assert target.observe()['images'] == {'top': 'img'}


def test_a_repeated_frame_sequence_is_refused():
    target = make(Site())
    target.observe()
    with pytest.raises(OSError):
        target.observe()  # the fake serves X-Frame-Seq 3 again


@pytest.mark.parametrize('lease', ['', '   ', None, 5])
def test_a_malformed_view_lease_never_falls_back_to_the_site_token(lease):
    class Bad(Site):
        def __call__(self, request, timeout):
            if request.full_url.endswith(site.VISION_LEASE):
                self.calls.append(('POST', site.VISION_LEASE))
                return Reply(json.dumps({'lease': lease, 'frame_path': '/api/vision/sources/top/frame',
                                         'expires_in_s': 60}).encode())
            return super().__call__(request, timeout)
    fake = Bad()
    with pytest.raises((ValueError, PermissionError)):
        make(fake).observe()
    assert ('GET', '/api/vision/sources/top/frame') not in fake.calls


def test_a_frame_reply_without_a_server_date_is_refused():
    fake = Site()
    original = fake.__call__

    def no_date(request, timeout):
        reply = original(request, timeout)
        reply.headers.pop('Date', None)
        return reply
    reader = site.SiteReader('https://fleet.example', 't', opener=no_date)
    target = site.SiteShadowTarget(reader, source_id='omx_b', joint_names=JOINTS, cameras={'top': ('top', (2, 2))},
                                   decode=lambda j, s: 'img', clock=lambda: 1000.5)
    with pytest.raises(OSError):
        target.observe()


def test_every_registered_no_redirect_copy_refuses_redirects():
    """known_duplicates.txt ③: the three _NoRedirect copies stay equivalent — a credential never follows a redirect."""
    import importlib.util
    copies = [site]
    for rel in ('operations/fleet/fleet/server/auth/policy_delivery.py', 'learning/curation/perception/owner_robots.py'):
        spec = importlib.util.spec_from_file_location(f'_no_redirect_{len(copies)}', ROOT / rel)
        spec.loader.exec_module(module := importlib.util.module_from_spec(spec))
        copies.append(module)
    for handler in (copy._NoRedirect() for copy in copies):
        assert handler.redirect_request(None, None, 302, 'Found', {}, 'https://elsewhere.invalid/') is None
