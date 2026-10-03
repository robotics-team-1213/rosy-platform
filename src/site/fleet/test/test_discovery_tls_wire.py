"""A real TLS handshake precedes HTTP headers and WebSocket credentials."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ssl
import threading

import httpx
import pytest
import websockets

from fleet.swarm.discovery_transport import DiscoveryTransport
from fleet.swarm.robots import RobotEndpoint


@pytest.fixture
def certificates(tmp_path):
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location('development_wire', root / 'tools/development_link.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = module.provision(tmp_path / 'scope', site='lab', robots=[('rosy_01', 'robot-a.local')])
    return output


def server_context(certificates, name):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificates / name / 'chain.pem', certificates / name / 'key.pem')
    return context


@pytest.mark.parametrize('valid', [True, False])
def test_http_keeps_sni_and_wrong_name_never_receives_bearer(certificates, monkeypatch, valid):
    received = []
    names = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.headers.get('Host'), self.headers.get('Authorization')))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')

        def log_message(self, *args):
            pass

    context = server_context(certificates, 'rosy_01')
    context.set_servername_callback(lambda sock, name, ctx: names.append(name))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = 'robot-a.local' if valid else 'foreign.local'
    endpoint = RobotEndpoint('rosy_01', f'https://{host}:8080', 'fixture',
                             tls_ca_file=str(certificates / 'ca.pem'), discovery=True)

    async def resolve(*args, **kwargs):
        return '127.0.0.1', server.server_port

    monkeypatch.setattr('fleet.swarm.discovery_transport.resolve_robot', resolve)

    async def run():
        async with httpx.AsyncClient(transport=DiscoveryTransport(endpoint), trust_env=False) as client:
            request = client.get(endpoint.base_url + '/api/v1/system/info',
                                 headers={'Authorization': 'Bearer fixture'})
            if valid:
                assert (await request).status_code == 200
            else:
                with pytest.raises(httpx.ConnectError):
                    await request

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert names == [host]
    assert received == [(f'{host}:8080', 'Bearer fixture')] if valid else not received


@pytest.mark.parametrize('valid', [True, False])
def test_websocket_checks_expected_name_before_auth_frame(certificates, valid):
    received = []

    async def run():
        async def handler(socket):
            received.append(await socket.recv())
            await socket.send('{"ready":true}')

        async with websockets.serve(handler, '127.0.0.1', 0,
                                    ssl=server_context(certificates, 'rosy_01')) as server:
            context = ssl.create_default_context(cafile=str(certificates / 'ca.pem'))
            host = 'robot-a.local' if valid else 'foreign.local'
            port = server.sockets[0].getsockname()[1]
            connection = websockets.connect(f'wss://{host}:8080/ws/state', host='127.0.0.1', port=port,
                                            server_hostname=host, ssl=context, proxy=None)
            if valid:
                async with connection as socket:
                    await socket.send('{"type":"auth","token":"fixture"}')
                    assert await socket.recv() == '{"ready":true}'
            else:
                with pytest.raises(ssl.SSLCertVerificationError):
                    async with connection:
                        pytest.fail('untrusted socket opened')

    asyncio.run(run())
    assert len(received) == (1 if valid else 0)
