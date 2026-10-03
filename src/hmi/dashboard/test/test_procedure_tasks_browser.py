"""D-439 procedure navigation: retained drafts, guarded selection and live stop."""
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[4]
COMMON = REPO / 'src/hmi/web_common'
pytestmark = pytest.mark.skipif(os.environ.get('ROSY_RUN_BROWSER_TESTS') != '1', reason='optional Chromium')


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO), **kwargs)

    def translate_path(self, path):
        if path.startswith('/common/'):
            return str(COMMON / path.removeprefix('/common/'))
        return super().translate_path(path)

    def do_GET(self):
        if self.path == '/fixture':
            body = """<!doctype html><html lang='ko'><head><meta charset='utf-8'>
            <link rel='stylesheet' href='/common/tokens.css'>
            <link rel='stylesheet' href='/common/components.css'>
            <link rel='stylesheet' href='/src/hmi/dashboard/shell/shell.css'></head>
            <body data-surface='setup'><ui-shell grammar='procedure'><ui-topbar>
            <ui-brand>ROSY</ui-brand><ui-text id='shell-notice'></ui-text>
            <ui-button id='shell-estop' kind='irreversible' data-always-live>비상 정지</ui-button></ui-topbar>
            <main class='surface-main'><div class='surface-slot' data-slot='main'></div></main></ui-shell>
            <script type='module'>
            import '/common/ui.js';
            import { mountPanels } from '/src/hmi/dashboard/shell/mount.js';
            window.counts={mount:0,unmount:0,stop:0,scope:0};
            document.getElementById('shell-estop').onclick=()=>window.counts.stop++;
            const panels=['first','second','broken'].map(id=>({id:'setup.'+id,title:{first:'첫 작업',second:'다음 작업',broken:'실패 작업'}[id],slot:'main',state:'available',css:[],module:'/stub.js'}));
            window.mounted=await mountPanels(document,panels,()=>({store:{stopAll(){window.counts.scope++}}}));
            </script></body></html>"""
        elif self.path == '/stub.js':
            body = """export function mount(root) {
              if(root.dataset.panel==='setup.broken') throw new Error('fixture mount failure');
              window.counts.mount++;
              const input=document.createElement('input'); input.setAttribute('aria-label','작업 초안');
              root.replaceChildren(input);
              return {beforeHide(){
                if(window.trackedGuards) {
                  window.trackedGuards.push(root.dataset.panel);
                  return new Promise(resolve => window.guardResolvers.push(resolve));
                }
                if(window.defer) return new Promise(resolve=>window.release=resolve);
                if(window.reject) throw new Error('unconfirmed');
                return window.blocked ? {message:'진행 중인 작업을 끝내세요.'}:true;
              },unmount(){window.counts.unmount++}};
            }"""
        else:
            return super().do_GET()
        data = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/javascript' if self.path.endswith('.js') else 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


@pytest.fixture
def page():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width':1366,'height':768})
            page.goto(f'http://127.0.0.1:{server.server_port}/fixture')
            page.wait_for_function('window.mounted')
            yield page
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_selection_retains_all_panels_drafts_and_failure_isolation(page):
    assert page.get_by_role('tab').count() == 3
    assert page.get_by_role('tabpanel').count() == 1
    page.get_by_role('textbox', name='작업 초안', exact=True).fill('보존할 초안')
    page.get_by_role('tab', name='다음 작업').click()
    expect(page.get_by_role('tab', name='다음 작업')).to_have_attribute('aria-selected','true')
    page.get_by_role('tab', name='실패 작업').click()
    expect(page.get_by_text('fixture mount failure', exact=False)).to_be_visible()
    page.get_by_role('tab', name='첫 작업').click()
    expect(page.get_by_role('textbox', name='작업 초안', exact=True)).to_have_value('보존할 초안')
    assert page.locator('.procedure-panel').count() == 3
    assert page.evaluate('window.counts.mount') == 2
    assert page.evaluate('window.counts.unmount') == 0


def test_guard_veto_rejection_and_pending_switch_leave_stop_live(page):
    page.evaluate('window.blocked=true')
    page.get_by_role('tab', name='다음 작업').click()
    expect(page.get_by_role('tab', name='첫 작업')).to_have_attribute('aria-selected','true')
    expect(page.get_by_text('진행 중인 작업을 끝내세요.')).to_be_visible()
    page.evaluate('window.blocked=false;window.reject=true')
    page.get_by_role('tab', name='다음 작업').click()
    expect(page.get_by_role('tab', name='첫 작업')).to_have_attribute('aria-selected','true')
    page.evaluate('window.reject=false;window.defer=true')
    page.get_by_role('tab', name='다음 작업').click()
    expect(page.get_by_role('tab', name='다음 작업')).to_be_disabled()
    page.get_by_role('button', name='비상 정지').click()
    assert page.evaluate('window.counts.stop') == 1
    page.evaluate('window.release(false)')
    expect(page.get_by_role('tab', name='다음 작업')).to_be_enabled()
    expect(page.get_by_role('tab', name='첫 작업')).to_have_attribute('aria-selected','true')


def test_keyboard_compact_chooser_and_teardown(page):
    first = page.get_by_role('tab', name='첫 작업')
    first.focus()
    page.keyboard.press('End')
    expect(page.get_by_role('tab', name='실패 작업')).to_have_attribute('aria-selected','true')
    page.keyboard.press('Home')
    expect(first).to_be_focused()
    page.keyboard.press('ArrowDown')
    expect(page.get_by_role('tab', name='다음 작업')).to_be_focused()
    expect(page.get_by_role('tab', name='다음 작업')).to_have_attribute('aria-selected','true')
    page.set_viewport_size({'width':320,'height':844})
    chooser = page.get_by_role('combobox', name='작업 선택', exact=True)
    expect(chooser).to_be_visible()
    chooser.focus()
    chooser.select_option('setup.first')
    expect(page.get_by_role('textbox', name='작업 초안', exact=True)).to_be_visible()
    expect(chooser).to_be_focused()
    page.evaluate('window.blocked=true')
    chooser.select_option('setup.second')
    expect(chooser).to_have_value('setup.first')
    expect(chooser).to_be_focused()
    page.evaluate('window.blocked=false')
    assert page.evaluate('document.documentElement.scrollWidth-innerWidth') == 0
    page.evaluate('window.mounted.unmountAll()')
    assert page.locator('.procedure-panel').count() == 0
    assert page.locator('.ui-task-chooser').count() == 0
    assert page.evaluate('window.counts.unmount') == 2
    assert page.evaluate('window.counts.scope') == 4


def test_shared_chooser_bounds_wait_and_discards_late_confirmation(page):
    page.evaluate("""async () => {
      const {createTaskChooser} = await import('/common/task-chooser.js');
      const panels = ['bounded-a','bounded-b'].map(id => {
        const panel = document.createElement('div'); panel.id = id; document.body.append(panel); return panel;
      });
      window.bounded = createTaskChooser({
        tasks: panels.map((panel, index) => ({id:panel.id, title:'시간 제한 '+index, panel})),
        timeoutMs: 30, beforeSelect: () => new Promise(resolve => window.confirmLate = resolve),
      });
      document.body.append(window.bounded.element); window.bounded.setReady();
      window.pendingChoice = window.bounded.choose('bounded-b');
    }""")
    page.wait_for_function("window.bounded.element.querySelector('ui-status').getAttribute('state') === 'warning'")
    assert page.evaluate('window.bounded.selectedId') == 'bounded-a'
    page.evaluate('window.confirmLate(true)')
    assert page.evaluate('window.bounded.selectedId') == 'bounded-a'
    assert page.evaluate('window.pendingChoice') is False
    # Removing a chooser detaches handlers even if another caller retains its element.
    page.evaluate("""() => {
      window.detachedTab = window.bounded.element.querySelectorAll('[role=tab]')[1];
      window.bounded.destroy(); window.detachedTab.click();
    }""")
    assert page.evaluate('window.bounded.selectedId') == 'bounded-a'


def test_teardown_freezes_pending_selection_and_honors_current_task_guard(page):
    page.evaluate('window.trackedGuards=[];window.guardResolvers=[]')
    page.get_by_role('tab', name='다음 작업').click()
    page.wait_for_function('window.guardResolvers.length === 1')
    page.evaluate("""() => {
      const first = window.mounted.unmountAll();
      window.sameTeardown = first === window.mounted.unmountAll();
      window.closing = first.then(() => 'closed', () => 'blocked');
    }""")
    page.wait_for_function('window.guardResolvers.length === 2')
    assert page.evaluate('window.sameTeardown') is True
    expect(page.get_by_role('tab', name='첫 작업')).to_be_disabled()
    page.evaluate('window.guardResolvers[0](true)')
    expect(page.get_by_role('tab', name='첫 작업')).to_have_attribute('aria-selected', 'true')
    page.evaluate('window.guardResolvers[1](false)')
    assert page.evaluate('window.closing') == 'blocked'
    expect(page.get_by_role('tab', name='첫 작업')).to_be_enabled()
    assert page.evaluate('window.counts.unmount') == 0
    page.get_by_role('tab', name='다음 작업').click()
    page.wait_for_function('window.guardResolvers.length === 3')
    page.evaluate('window.guardResolvers[2](true)')
    expect(page.get_by_role('tab', name='다음 작업')).to_have_attribute('aria-selected', 'true')
    page.evaluate("""() => {
      window.closing = window.mounted.unmountAll().then(() => 'closed', () => 'blocked');
    }""")
    page.wait_for_function('window.guardResolvers.length === 4')
    assert page.evaluate('window.trackedGuards') == ['setup.first'] * 3 + ['setup.second']
    page.evaluate('window.guardResolvers[3](false)')
    assert page.evaluate('window.closing') == 'blocked'
    expect(page.get_by_role('tab', name='다음 작업')).to_be_enabled()
    assert page.locator('.procedure-panel').count() == 3


def test_teardown_timeout_and_rejection_preserve_panels_and_release_navigation(page):
    page.clock.install()
    page.evaluate('window.defer=true')
    page.evaluate("""() => {
      window.closing = window.mounted.unmountAll().then(() => 'closed', error => error.message);
    }""")
    page.wait_for_function('Boolean(window.release)')
    page.get_by_role('button', name='비상 정지').click()
    assert page.evaluate('window.counts.stop') == 1
    page.clock.fast_forward(10_001)
    assert '시간' in page.evaluate('window.closing')
    expect(page.get_by_role('tab', name='첫 작업')).to_be_enabled()
    page.evaluate('window.release(true);window.defer=false;window.reject=true')
    result = page.evaluate('window.mounted.unmountAll().then(() => "closed", () => "rejected")')
    assert result == 'rejected'
    assert page.locator('.procedure-panel').count() == 3
    expect(page.get_by_role('tab', name='첫 작업')).to_be_enabled()
    assert page.evaluate('window.counts.unmount') == 0
