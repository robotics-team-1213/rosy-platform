"""Real media test helpers; never installed on a robot."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen

import yaml


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@contextmanager
def authority(app=None):
    if app is not None:
        import uvicorn
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
                                               log_level='error', access_log=False))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        until = time.monotonic() + 5
        while not server.started:
            assert thread.is_alive() and time.monotonic() < until, 'media authority startup failed'
            time.sleep(.02)
        try:
            yield port
        finally:
            server.should_exit = True
            thread.join(timeout=5)
        return
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            allowed = data.get('token') == 'loopback-scoped-token'
            self.send_response(200 if allowed else 403)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


SENDER = '''
import os,sys,time,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from rosy_media_edge.pipeline import MediaPublisher
publisher=MediaPublisher(sys.argv[2], os.environ.get('ROSY_TEST_MEDIA_TOKEN','loopback-scoped-token'),allow_loopback_http=True)
try:
    publisher.start()
    for sequence in range(1,450):
        publisher.push_rgb(bytes([sequence%200])*640*480*3,epoch=17,
                           sequence=sequence,captured_ms=int(time.time()*1000))
        if sequence==30:
            publisher.wait_connected()
            Path(sys.argv[3]).write_text('ready')
        if sequence==55:
            publisher.set_rate(fps=5, bitrate=300000)
        if sequence==60:
            Path(sys.argv[3]).with_name('publisher-stats.json').write_text(json.dumps(publisher.stats()))
        time.sleep(1/15)
finally:
    publisher.stop()
'''


BROWSER = '''async ({url,token='loopback-scoped-token'}) => {
  const pc = new RTCPeerConnection({iceServers: []});
  window.mediaPeer = pc;
  const video = document.createElement('video');
  video.muted = true; video.autoplay = true; video.playsInline = true;
  document.body.append(video); window.mediaVideo = video;
  pc.ontrack = event => {video.srcObject = event.streams[0] || new MediaStream([event.track]);};
  pc.addTransceiver('video', {direction: 'recvonly'});
  await pc.setLocalDescription(await pc.createOffer());
  if (pc.iceGatheringState !== 'complete') await new Promise((resolve,reject) => {
    const timer=setTimeout(()=>reject(new Error('ICE timeout')),8000);
    pc.addEventListener('icegatheringstatechange',()=>{
      if(pc.iceGatheringState==='complete'){clearTimeout(timer);resolve();}
    });
  });
  const response = await fetch(url, {method:'POST', headers:{
    'Authorization':'Bearer '+token,'Content-Type':'application/sdp'},
    body:pc.localDescription.sdp});
  if(response.status!==201) throw new Error('WHEP refused '+response.status);
  window.mediaSession = new URL(response.headers.get('Location'),url).href;
  await pc.setRemoteDescription({type:'answer',sdp:await response.text()});
  await video.play();
  return true;
}'''


SHARED_BROWSER = '''async ({grant}) => {
  const {openCamera} = await import('/common/webrtc.js');
  const video = document.createElement('video');
  Object.assign(video, {muted: true, autoplay: true, playsInline: true, hidden: true});
  document.body.append(video); window.mediaVideo = video;
  window.mediaRevoked = [];
  window.mediaView = await openCamera({grant, video,
    Peer: class extends RTCPeerConnection {
      constructor(...args) {super(...args); window.mediaPeer = this;}
    },
    renewGrant: async () => grant,
    revokeGrant: async id => {window.mediaRevoked.push(id);},
    onState: state => {video.hidden = !['live', 'stale'].includes(state.state);},
  });
}'''


def run_loopback(root, tmp_path, *, secure=False, shared_client=False):
    from playwright.sync_api import sync_playwright
    runtime = Path.home() / 'rosy-test/media-runtime-d789'
    binary = runtime / 'amd64/mediamtx'
    assert binary.is_file(), 'prepared remote MediaMTX runtime missing'
    env = os.environ.copy()
    env.update(json.loads((runtime / 'environment.json').read_text()))
    env['PYTHONPATH'] = str(root / 'middleware/media/src') + os.pathsep + env['PYTHONPATH']
    port, udp = free_port(), free_port(socket.SOCK_DGRAM)
    api_port = free_port()
    app, delegated, original, admin = None, None, None, None
    media_path = 'robots/rosy_01/front' if shared_client else 'camera'
    if secure:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        sys.path.insert(0, str(root / 'operations/site_ui/media/src'))
        sys.path.insert(0, str(root / 'middleware/core/services'))
        from core_features.vision.media_grants import MediaGrantService
        from rosy_media.authority import MediaAuthority
        from rosy_media.backend import MediaMTXClient
        from rosy_media.server import create_app
        import secrets
        admin = secrets.token_urlsafe(32)
        key = Ed25519PrivateKey.generate()
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
        public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
        original = {'read': True, 'publish': True}
        grants = MediaGrantService(robot_id='rosy_01', audience='site:bench', private_key=private,
            key_id='test-media-1', owner_allowed=lambda owner, action: original.get(action) is True)
        read = grants.issue('viewer', 'rosy_01', 'read', now=time.time())
        publish = grants.issue('source', 'rosy_01', 'publish', now=time.time())
        backend = MediaMTXClient(f'http://127.0.0.1:{api_port}', admin)
        delegated = MediaAuthority(audience='site:bench', public_keys={'rosy_01': {'test-media-1': public}},
            validate_online=lambda robot, token, now: grants.check(token, now=now), kick=backend.kick)
        app = create_app(delegated, admin_token=admin)
        assert delegated.intent(read.token, now=time.time())
        env['ROSY_TEST_MEDIA_TOKEN'] = publish.token
        media_path = read.path
    config = yaml.safe_load((root / 'deploy/site/mediamtx.yaml').read_text())
    config.update({'webrtcAddress': f'127.0.0.1:{port}', 'api': secure, 'moq': False,
                   'apiAddress': f'127.0.0.1:{api_port}',
                   'webrtcLocalUDPAddress': f'127.0.0.1:{udp}',
                   'webrtcIPsFromInterfaces': False, 'webrtcAdditionalHosts': ['127.0.0.1'],
                   'webrtcAllowOrigins': ['*'], 'paths': {media_path: {}}})
    with authority(app) as auth_port:
        config['authHTTPAddress'] = f'http://127.0.0.1:{auth_port}/auth'
        config_path = tmp_path / 'mediamtx.yaml'
        config_path.write_text(yaml.safe_dump(config))
        with (tmp_path / 'server.log').open('w') as server_log, (tmp_path / 'sender.log').open('w') as sender_log:
            server = subprocess.Popen([str(binary), str(config_path)], stdout=server_log, stderr=server_log)
            sender = None
            try:
                deadline = time.monotonic() + 5
                while True:
                    assert server.poll() is None, (tmp_path / 'server.log').read_text()
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                            break
                    except OSError:
                        assert time.monotonic() < deadline, 'media listener startup timeout'
                        time.sleep(.05)
                ready = tmp_path / 'ready'
                sender = subprocess.Popen(['/usr/bin/python3', '-c', SENDER,
                    str(root / 'middleware/media/src'),
                    f'http://127.0.0.1:{port}/{media_path}/whip', str(ready)],
                    env=env, stdout=sender_log, stderr=sender_log)
                deadline = time.monotonic() + 20
                while not ready.exists():
                    assert sender.poll() is None, (tmp_path / 'sender.log').read_text()
                    assert time.monotonic() < deadline, (tmp_path / 'sender.log').read_text()
                    time.sleep(.1)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True,
                        args=[] if shared_client else ['--autoplay-policy=no-user-gesture-required'])
                    try:
                        page = browser.new_page()
                        page.goto(f'http://127.0.0.1:{port}/{media_path}')
                        browser_config = {'url': f'http://127.0.0.1:{port}/{media_path}/whep'}
                        if secure:
                            browser_config['token'] = read.token
                        if shared_client:
                            page.route('**/common/webrtc.js', lambda route: route.fulfill(
                                content_type='text/javascript', body=(root / 'shared/web/webrtc.js').read_text()))

                            def signaling(route):
                                path = route.request.url.removeprefix('https://media.site.example')
                                headers = {'Access-Control-Allow-Origin': '*',
                                    'Access-Control-Allow-Headers': 'Authorization,Content-Type',
                                    'Access-Control-Allow-Methods': 'POST,DELETE,OPTIONS',
                                    'Access-Control-Expose-Headers': 'Location'}
                                if route.request.method == 'OPTIONS':
                                    route.fulfill(status=204, headers=headers)
                                elif path in ('/v1/intents', '/v1/session/renew'):
                                    route.fulfill(status=201, headers=headers)
                                else:
                                    response = route.fetch(url=f'http://127.0.0.1:{port}{path}')
                                    route.fulfill(response=response, headers={**response.headers, **headers})

                            page.route('https://media.site.example/**', signaling)
                            page.evaluate(SHARED_BROWSER, {'grant': {
                                'grant_id': 'a' * 32, 'token': 'loopback-scoped-token',
                                'site_url': 'https://media.site.example', 'path': media_path}})
                            page.wait_for_function('!window.mediaVideo.hidden && !window.mediaVideo.paused')
                        else:
                            page.evaluate(BROWSER, browser_config)
                        page.wait_for_function('window.mediaVideo.videoWidth === 640', timeout=12000)
                        read = runpy.run_path(str(root / 'middleware/media/src/rosy_media_edge/watermark.py'))['read_rgb']
                        identities = []
                        for _ in range(2):
                            rgba = page.evaluate('''() => {
                              const canvas=document.createElement('canvas');canvas.width=128;canvas.height=24;
                              const ctx=canvas.getContext('2d');ctx.drawImage(window.mediaVideo,0,0);
                              return Array.from(ctx.getImageData(0,0,128,24).data);
                            }''')
                            rgb = bytearray(value for index, value in enumerate(rgba) if index % 4 != 3)
                            identity = read(rgb, 128, 24)
                            assert identity is not None, 'capture watermark did not survive real H.264/WebRTC rendering'
                            assert identity[0] == 17
                            assert abs(time.time() * 1000 - identity[2]) < 2000
                            identities.append(identity)
                            page.wait_for_timeout(250)
                        assert identities[1][1] > identities[0][1]
                        stats_file = tmp_path / 'publisher-stats.json'
                        until = time.monotonic() + 8
                        while not stats_file.exists():
                            assert sender.poll() is None, (tmp_path / 'sender.log').read_text()
                            assert time.monotonic() < until, 'publisher telemetry was not recorded'
                            page.wait_for_timeout(100)
                        stats = json.loads(stats_file.read_text())
                        assert stats['encoder_bitrate'] == 300000
                        assert stats['encoder_key_interval'] == 5
                        assert stats['rtp_bytes_sent'] > 0
                        assert stats['rtp_packets_sent'] > 0
                        if shared_client:
                            with page.expect_response(lambda response: response.request.method == 'DELETE'
                                    and response.url.startswith('https://media.site.example/')) as deleted:
                                page.evaluate('window.mediaView.close()')
                            assert deleted.value.status == 204, (deleted.value.status, deleted.value.text())
                            assert page.evaluate('window.mediaVideo.srcObject === null')
                            assert page.evaluate('window.mediaPeer.connectionState') == 'closed'
                            assert page.evaluate('window.mediaRevoked') == ['a' * 32]
                        print(json.dumps({'schema': 'rosy-media-loopback/1', 'identities': identities,
                                          'native_arm64': False, 'real_camera': False, 'field_accepted': False}))
                        if secure:
                            original['read'] = False
                            until = time.monotonic() + 5
                            request = Request(f'http://127.0.0.1:{api_port}/v3/webrtc/sessions/list',
                                              headers={'Authorization': 'Bearer ' + admin})
                            while True:
                                with urlopen(request, timeout=1) as result:
                                    live = json.load(result)['items']
                                if not live:
                                    break
                                assert time.monotonic() < until, 'original CORE revocation left real media sessions alive'
                                page.wait_for_timeout(100)
                            page.wait_for_timeout(500)
                            stopped = page.evaluate('window.mediaVideo.getVideoPlaybackQuality().totalVideoFrames')
                            page.wait_for_timeout(500)
                            assert page.evaluate('window.mediaVideo.getVideoPlaybackQuality().totalVideoFrames') == stopped
                            print('CORE revocation: actual MediaMTX sessions removed and browser video stopped')
                    finally:
                        browser.close()
            finally:
                for child in (sender, server):
                    if child is not None and child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(timeout=2)


def run_secure_loopback(root, tmp_path):
    run_loopback(root, tmp_path, secure=True)
