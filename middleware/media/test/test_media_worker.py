"""D-789 T3: the robot runtime publishes only on fresh viewer demand and sheds load safely."""

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def implementation():
    assert (ROOT / 'src/rosy_media_edge/worker.py').is_file(), 'D-789 robot media runtime missing'
    return importlib.import_module('rosy_media_edge.worker')


@dataclass
class Grant:
    grant_id: str
    token: str
    expires_at: int


@dataclass
class Frame:
    epoch: int
    sequence: int
    captured_ms: int
    rgb: bytes


class Client:
    def __init__(self):
        self.active, self.fail, self.grants, self.renewed, self.issued = True, None, [], [], 0

    def source_grant(self, grant_id=None):
        if self.fail:
            raise self.fail
        self.grants.append(grant_id)
        self.issued += 1
        return Grant('a' * 32, f'publish-{self.issued}', self.now + 60)

    def demand(self, grant):
        if self.fail:
            raise self.fail
        return {'active': self.active, 'robot_id': 'rosy_01', 'fps': 15,
                'target_bitrate': 800000, 'max_bitrate': 1000000}

    def renew_session(self, grant):
        self.renewed.append(grant.token)

    def whip_endpoint(self, grant):
        return 'https://site.example/robots/rosy_01/front/whip'


class Publisher:
    def __init__(self, endpoint, token):
        self.endpoint, self.token, self.pushed, self.rates = endpoint, token, [], []
        self.started = self.stopped = False
        self.queue_ms, self.fail_push = 10, False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def push_rgb(self, rgb, **identity):
        if self.fail_push:
            raise RuntimeError('media pipeline error')
        self.pushed.append(identity['sequence'])
        return True

    def stats(self):
        return {'encoded_queue_ms': self.queue_ms, 'loss_fraction': None, 'encoded_queue_overrun': False}

    def set_rate(self, *, fps, bitrate):
        self.rates.append((fps, bitrate))


class Reader:
    def __init__(self):
        self.sequence = 0

    def latest(self):
        self.sequence += 1
        return Frame(7, self.sequence, 1000, b'\0')

    def close(self):
        pass


@pytest.fixture
def rig():
    client, publishers = Client(), []

    def make(endpoint, token):
        publishers.append(Publisher(endpoint, token))
        return publishers[-1]

    worker = implementation().MediaWorker(client=client, open_reader=Reader, make_publisher=make,
                                          rng=lambda: 0.0, log=lambda line: None)

    def step(now):
        client.now = 1_000_000 + now
        worker.step(now=now, wall=client.now)

    return worker, client, publishers, step


def test_no_viewer_demand_never_starts_the_encoder(rig):
    worker, client, publishers, step = rig
    client.active = False
    for now in range(5):
        step(now)
    assert publishers == []


def test_demand_starts_one_publisher_with_scoped_grant_and_pushes_frames(rig):
    _, client, publishers, step = rig
    step(0)
    step(0.1)
    assert len(publishers) == 1 and publishers[0].started
    assert publishers[0].token == 'publish-1'
    assert publishers[0].endpoint.endswith('/robots/rosy_01/front/whip')
    assert publishers[0].pushed == [1, 2]


def test_last_viewer_leaving_stops_the_publisher(rig):
    _, client, publishers, step = rig
    step(0)
    client.active = False
    step(1)
    assert publishers[0].stopped


def test_stale_demand_stops_publishing_within_five_seconds(rig):
    _, client, publishers, step = rig
    step(0)
    client.fail = implementation().MediaHTTPError('media control unavailable')
    for now in range(1, 6):
        step(now)
    assert not publishers[0].stopped
    step(6)
    assert publishers[0].stopped


def test_revoked_source_scope_stops_at_once(rig):
    _, client, publishers, step = rig
    step(0)
    client.fail = implementation().MediaHTTPError(status=403)
    step(1)
    assert publishers[0].stopped


def test_grant_renewal_keeps_jti_and_renews_the_bound_session(rig):
    _, client, publishers, step = rig
    for now in range(0, 22):
        step(now)
    assert client.grants == [None, 'a' * 32]
    assert client.renewed == ['publish-2']
    assert len(publishers) == 1 and not publishers[0].stopped


def test_feedback_applies_rate_and_old_encoded_queue_restarts_with_backoff(rig):
    _, _, publishers, step = rig
    step(0)
    step(1)
    assert publishers[0].rates[-1] == (15, 800000)
    publishers[0].queue_ms = 250
    step(2)
    assert publishers[0].stopped
    step(2.1)
    assert len(publishers) == 1          # bounded backoff before the IDR restart
    step(3)
    step(3.1)
    assert len(publishers) == 2 and publishers[1].started


def test_pipeline_failure_stops_the_session(rig):
    _, _, publishers, step = rig
    step(0)
    publishers[0].fail_push = True
    step(0.1)
    assert publishers[0].stopped


def test_start_failures_back_off_with_a_five_second_cap():
    client, attempts = Client(), []

    def broken(endpoint, token):
        attempts.append(client.now)
        raise RuntimeError('media signaling unavailable')

    worker = implementation().MediaWorker(client=client, open_reader=Reader, make_publisher=broken,
                                          rng=lambda: 0.98, log=lambda line: None)
    for tick in range(400):
        client.now = 1_000_000 + tick / 10
        worker.step(now=tick / 10, wall=1_000_000 + tick / 10)
    gaps = [later - earlier for earlier, later in zip(attempts, attempts[1:])]
    assert len(attempts) >= 6
    assert gaps[0] < gaps[-1] <= 5.0 + 1e-6
