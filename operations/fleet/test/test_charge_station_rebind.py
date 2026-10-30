"""ChargeRobotHttp.read_station's target rebind against an owner generation that a native run moves meanwhile."""
import asyncio
from types import SimpleNamespace

import pytest

from fleet.server import charge_robot_http
from fleet.swarm.api.ports import RobotApiError

SCOPE = dict(session_id='charge-1', robot_id='rosy_01', station_id='charger-1', battery_id='bat-1', boot_id='boot-1',
             map_id='floor', map_revision='map-1', pose_revision=1, attempt_id='a-1')


class Model:
    """Stands in for the pydantic records: read_station only dumps, compares and re-validates them."""

    def __init__(self, **data):
        self.__dict__['data'] = data

    def __getattr__(self, key):
        return self.data[key]

    def __eq__(self, other):
        return isinstance(other, Model) and self.data == other.data

    def model_dump(self, exclude=()):
        return {k: v for k, v in self.data.items() if k not in exclude}

    @classmethod
    def model_validate(cls, data, context=None):
        return cls(**data)


class Client:
    robot_id = 'rosy_01'

    def __init__(self, errors):
        self.errors, self.sent, self.generation = list(errors), [], 3

    async def docking_status(self):
        return {'owner': {'boot_id': 'boot-1', 'owner_generation': self.generation, 'owner_run_id': 'run-1'}}

    async def station_target(self):
        return {}

    async def station_bind(self, binding):
        self.sent.append(binding['expected_owner_generation'])
        if self.errors:
            self.generation += 1  # the undock run moved on between the read and CORE's compare-and-set
            raise self.errors.pop(0)


def read(monkeypatch, errors):
    for name in ('StationPoseRecord', 'StationTargetStatus', 'StationObservation'):
        monkeypatch.setattr(charge_robot_http, name, Model)
    monkeypatch.setattr(charge_robot_http, 'StationTargetBinding', lambda **kw: kw)
    session = SimpleNamespace(**SCOPE)
    target = Model(status='VALID', captured_at=2., pose='new')
    client = Client(errors)

    async def scope(_session, _target):
        return Model(source='global')
    http = charge_robot_http.ChargeRobotHttp(
        clients=lambda: {'rosy_01': client}, clock=lambda: 2.,
        store=SimpleNamespace(admitted_session=lambda _id, states: session),
        stations=SimpleNamespace(store=SimpleNamespace(get=lambda _id: target)), returns=None,
        return_http=SimpleNamespace(_live=lambda s, t, body, boundary: Model(target=Model(captured_at=1., pose='old'))),
        snapshot=None, observation_scope=scope)
    return client, asyncio.run(http.read_station(session))


def changed(code='OWNER_GENERATION_CHANGED'):
    return RobotApiError('rosy_01', 409, code, code)


def test_a_generation_moved_by_the_native_run_is_read_again_and_bound_once_more(monkeypatch):
    client, live = read(monkeypatch, [changed()])
    assert client.sent == [3, 4] and live.target.pose == 'old'


def test_a_second_generation_refusal_still_propagates(monkeypatch):
    sent = []
    monkeypatch.setattr(Client, 'station_bind', record(Client.station_bind, sent))
    with pytest.raises(RobotApiError):
        read(monkeypatch, [changed(), changed()])
    assert sent == [3, 4]  # each try read the generation again; no third send


def record(bind, sent):
    async def recorded(self, binding):
        sent.append(binding['expected_owner_generation'])
        return await bind(self, binding)
    return recorded


@pytest.mark.parametrize('error', [changed('OWNER_BOOT_CHANGED'), RobotApiError('rosy_01', 500, 'HTTP_500', 'x'),
                                   ValueError('STATION_TARGET_STALE')])
def test_any_other_bind_refusal_is_not_retried(monkeypatch, error):
    errors = [error]
    with pytest.raises(type(error)):
        read(monkeypatch, errors)
