"""Sample devices use the same UI seams without real microphones, packs or peers."""
import pytest
from browser_harness import browser_tests_enabled
from test_sample_browser import sample_site

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')


def test_sample_voice_and_video_need_no_browser_devices_or_external_network(sample_site):
    from playwright.sync_api import sync_playwright
    _, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            external = []
            page.on('request', lambda request: external.append(request.url)
                    if request.url.startswith('http') and not request.url.startswith(origin + '/') else None)
            page.goto(origin + '/console/login')
            for asset in ('app-runtime.js', 'assistant-voice.js'):
                resource = page.request.get(origin + '/console/assets/' + asset)
                assert resource.status == 200, (asset, resource.status, resource.text())
            for asset in ('browser-platform.js', 'media-session.js'):
                resource = page.request.get(origin + '/__dev/assets/' + asset)
                assert resource.status == 200, (asset, resource.status, resource.text())
            result = page.evaluate('''async () => {
              const {voicePlatform, openRobotCamera} = await import('/console/assets/app-runtime.js');
              const {createVoice} = await import('/console/assets/assistant-voice.js');
              const states = [], texts = [];
              const voice = createVoice({platform: voicePlatform, onText: t => texts.push(t), onState: s => states.push(s)});
              if (!await voice.prepare() || !await voice.start()) throw Error('sample voice unavailable');
              dispatchEvent(new CustomEvent('rosy-sample-voice', {detail: {text: '샘플 로봇 상태'}}));
              voice.cancel();
              await voice.start();
              dispatchEvent(new CustomEvent('rosy-sample-voice', {detail: {error: 'not-allowed'}}));
              const video = document.createElement('video'); video.muted = true; document.body.append(video);
              const cameraStates = []; let revoked = 0, renewed = 0;
              const camera = await openRobotCamera({video, grant: {grant_id:'sample-grant'},
                onState: s => cameraStates.push(s.state), renewGrant: async () => {renewed++; return {};},
                revokeGrant: async () => {revoked++;}});
              dispatchEvent(new CustomEvent('rosy-sample-media', {detail:{state:'stale'}}));
              dispatchEvent(new CustomEvent('rosy-sample-media', {detail:{state:'renew'}}));
              await new Promise(resolve => setTimeout(resolve, 30));
              camera.close('stopped');
              await new Promise(resolve => setTimeout(resolve, 30));
              return {texts, states, cameraStates, revoked, renewed, detached:video.srcObject === null};
            }''')
            assert result['texts'] == ['샘플 로봇 상태']
            assert 'ready' in result['states'] and 'denied' in result['states']
            assert 'live' in result['cameraStates'] and 'stale' in result['cameraStates']
            assert result['revoked'] == result['renewed'] == 1 and result['detached']
            assert not external, external
        finally:
            browser.close()
