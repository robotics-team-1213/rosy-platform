"""Approved public keys preserve key-only SSH and the existing operator roster."""

import base64
import asyncio
import os
import struct

import pytest
from ssh_pairing import public_key, register_operator_key
from host_agent import HostAgent
from types import SimpleNamespace


def key(seed=1):
    raw = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32) + bytes([seed]) * 32
    return 'ssh-ed25519 ' + base64.b64encode(raw).decode()


def test_registry_preserves_existing_key_and_returns_pinnable_host_identity(tmp_path):
    (tmp_path / 'etc/ssh').mkdir(parents=True)
    (tmp_path / 'home/rosy/.ssh').mkdir(parents=True)
    (tmp_path / 'etc/ssh/ssh_host_ed25519_key.pub').write_text(key(3))
    path = tmp_path / 'home/rosy/.ssh/authorized_keys'
    path.write_text(key(2) + '\n')
    owner = (os.getuid(), os.getgid()) if os.name == 'posix' else (0, 0)
    result = register_operator_key(key(), root=tmp_path, owner=owner)
    assert result['account'] == 'rosy' and result['port'] == 22
    assert result['host_public_key'] == key(3)
    assert result['host_key_fingerprint'].startswith('SHA256:')
    assert path.read_text().splitlines() == [key(2), key()]
    assert register_operator_key(key(), root=tmp_path, owner=owner)['already_registered']
    assert path.read_text().splitlines() == [key(2), key()]


@pytest.mark.parametrize('value', ['command="reboot" ssh-ed25519 x', 'ssh-rsa x',
                                   'ssh-ed25519 invalid', 'ssh-ed25519 x\n', key() + '\n'])
def test_options_other_key_types_and_injection_are_refused(value):
    with pytest.raises(ValueError):
        public_key(value)


def test_unconfirmed_or_unprivileged_request_never_installs_key():
    class Commands:
        def register_ssh_key(self, value):
            pytest.fail('refused key must not reach privileged action')
    agent = HostAgent(Commands(), allowed_profiles=[], allowed_units=[], audit=lambda item: None)
    for actor, confirmed in [('viewer', True), ('administrator', False)]:
        request = {'schema_version': 1, 'request_id': actor, 'command': 'ssh.register_key',
                   'actor': {'role': actor, 'user_id': 'operator'}, 'confirmed': confirmed,
                   'params': {'public_key': key()}}
        result = agent.handle(request)
        assert not result['ok']


def test_ssh_only_service_refuses_other_privileged_commands():
    class Commands:
        def reboot(self):
            pytest.fail('SSH-only daemon must not reboot')
    agent = HostAgent(Commands(), allowed_profiles=[], allowed_units=[], allowed_commands=['ssh.register_key'])
    result = agent.handle({'schema_version': 1, 'request_id': 'restricted', 'command': 'system.reboot',
                           'actor': {'role': 'administrator', 'user_id': 'operator'},
                           'confirmed': True, 'params': {}})
    assert not result['ok']


@pytest.mark.parametrize('role,readback_valid,logout_status,accepted', [
    ('administrator', True, 204, True), ('operator', True, 204, False),
    ('administrator', False, 204, False), ('administrator', True, 500, False),
])
def test_ssh_code_approval_requires_role_readback_and_confirmed_revocation(
        role, readback_valid, logout_status, accepted):
    import httpx
    from tools.pair_ssh import approve
    from ssh_pairing import fingerprint
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/auth/pair'):
            return httpx.Response(201, json={'token': 'temporary-approval-session', 'role': role})
        if request.url.path.endswith('/system/info'):
            return httpx.Response(200, json={'robot_id': 'rosy_01'})
        if request.url.path.endswith('/ssh/pair'):
            return httpx.Response(200, json={'available': True, 'ok': True, 'data': {
                'account': 'rosy', 'port': 22,
                'public_key_fingerprint': fingerprint(key()) if readback_valid else 'wrong',
                'host_public_key': key(3), 'host_key_fingerprint': fingerprint(key(3)),
            }})
        return httpx.Response(logout_status)

    async def run():
        async with httpx.AsyncClient(base_url='https://robot.local', transport=httpx.MockTransport(handler)) as client:
            return await approve(SimpleNamespace(robot_id='rosy_01'), '7KXM', key(), client=client)

    if accepted:
        assert asyncio.run(run())['account'] == 'rosy'
    else:
        with pytest.raises(ValueError):
            asyncio.run(run())
    assert calls[-1] == '/api/v1/auth/logout'
