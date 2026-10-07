"""Traffic review actions preserve drafts, server truth and recoverable results."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from browser_harness import browser_tests_enabled, free_port
from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                              reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium")


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO), **kwargs)

    def translate_path(self, path):
        if path.startswith("/common/"):
            path = "/shared/web/" + path[len("/common/"):]
        return super().translate_path(path)

    def log_message(self, *_args):
        pass


@pytest.fixture
def panel():
    server = ThreadingHTTPServer(("127.0.0.1", free_port()), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.evaluate("""async () => {
              document.body.replaceChildren();
              for (const file of ['tokens.css', 'components.css']) {
                const link=document.createElement('link'); link.rel='stylesheet';
                link.href='/common/'+file; document.head.append(link);
              }
              await import('/common/ui.js');
              const {mount}=await import('/middleware/ui/robot/panels/setup/traffic-policy.js');
              const root=document.createElement('main'); document.body.append(root);
              window.calls=[]; window.requests=[]; window.pollStopped=false;
              window.unmount=mount(root, {role:'operator', store:{poll(_path,_ms,data,error) {
                window.emit=data; window.pollError=error;
                return () => {window.pollStopped=true;};
              }}, api:(path,options={}) => {
                window.calls.push({path,method:options.method,body:options.body&&JSON.parse(options.body)});
                return new Promise((resolve,reject) => window.requests.push({resolve,reject}));
              }});
              window.initial={active:{mode:'MONITOR_ONLY',junction_rule:'signal_controlled',
                policy_revision:'active-a',approach_distance_m:1,stop_distance_m:.3,
                stop_dwell_s:1,min_confidence:.8},staged:null,
                simulation_signal:{available:false,colour:'RED'},status:{state:'FOLLOW',
                reason:'clear_road',signal_colour:'GREEN',signal_source_kind:'camera',
                junction_rule:'signal_controlled',stop_line_distance_m:null}};
              window.emit(window.initial); window.confirm=()=>true;
            }""")
            yield page
            page.evaluate("window.unmount()")
            assert page.evaluate("window.pollStopped")
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _response(page, *, revision="review-a", applied=False, error=None):
    page.wait_for_function("() => window.requests.length > 0")
    page.evaluate("""({revision,applied,error}) => {
      const request=window.requests.shift();
      if(error) {request.reject(new Error(error)); return;}
      const candidate={...window.initial.active,policy_revision:revision};
      request.resolve({...window.initial,active:applied?candidate:window.initial.active,
        staged:applied?null:candidate});
    }""", {"revision": revision, "applied": applied, "error": error})


def test_stage_can_repeat_and_terminal_results_survive_poll(panel):
    page = panel
    revision = page.locator('[name="policy_revision"]')
    stage = page.get_by_text("정책 검토본 저장", exact=True)
    revision.fill("review-a")
    stage.click()
    _response(page)
    expect(stage).to_be_enabled()
    expect(page.get_by_text("검토본 저장됨: review-a", exact=True)).to_be_visible()
    page.evaluate("window.emit(window.initial)")
    expect(page.get_by_text("검토본 저장됨: review-a", exact=True)).to_be_visible()
    revision.fill("review-b")
    stage.click()
    _response(page, error="검증 거부")
    expect(stage).to_be_enabled()
    page.evaluate("window.emit(window.initial)")
    expect(page.get_by_text("정책 검증 실패: 검증 거부", exact=True)).to_be_visible()
    expect(revision).to_have_value("review-b")
    stage.click()
    _response(page, revision="review-b")
    expect(page.get_by_text("검토본 저장됨: review-b", exact=True)).to_be_visible()
    assert page.evaluate("window.calls.length") == 3


def test_pending_is_atomic_and_dirty_draft_cannot_apply_old_review(panel):
    page = panel
    revision = page.locator('[name="policy_revision"]')
    stage = page.get_by_text("정책 검토본 저장", exact=True)
    apply = page.get_by_role("button", name="정지 상태에서 적용", exact=True)
    revision.fill("review-a")
    stage.click()
    page.evaluate("window.emit({...window.initial,staged:{...window.initial.active,policy_revision:'external'}})")
    expect(revision).to_have_value("review-a")
    expect(revision).to_be_disabled()
    expect(stage).to_be_disabled()
    expect(apply).to_be_disabled()
    assert stage.get_attribute("reason") is None
    _response(page)
    expect(apply).to_be_enabled()
    revision.fill("review-b")
    page.evaluate("window.emit({...window.initial,staged:{...window.initial.active,policy_revision:'review-a'}})")
    expect(revision).to_have_value("review-b")
    expect(apply).to_be_disabled()
    assert apply.get_attribute("reason") == "입력 변경: 검토본을 다시 저장하세요"
    apply.dispatch_event("click")
    assert page.evaluate("window.calls.length") == 1
    stage.click()
    _response(page, revision="review-b")
    expect(apply).to_be_enabled()
    assert page.evaluate("window.calls[1].body.mode") == "MONITOR_ONLY"


def test_readback_missing_and_unknown_values_never_invent_evidence(panel):
    page = panel
    facts = page.locator(".traffic-policy-facts")
    assert "0.000 m" not in facts.inner_text()
    expect(facts).to_contain_text("주행")
    expect(facts).to_contain_text("카메라")
    page.evaluate("window.emit({})")
    assert set(facts.locator("dd").all_text_contents()) == {"—"}
    page.evaluate("window.emit({...window.initial,status:{state:'FUTURE_STATE',reason:'future_reason',signal_colour:'BLUE',signal_source_kind:'sensor-x',junction_rule:'future_rule',stop_line_distance_m:0}})")
    for value in ["FUTURE_STATE", "future_reason", "BLUE", "sensor-x", "future_rule", "0.000 m"]:
        expect(facts).to_contain_text(value)
    assert page.locator('[name="mode"] option[value="MONITOR_ONLY"]').inner_text() == "관찰만"
    assert page.locator('[name="mode"] option[value="ADVISORY"]').count() == 0


def test_apply_confirmation_rejection_retry_and_simulation_permission(panel):
    page = panel
    page.evaluate("window.emit({...window.initial,staged:{...window.initial.active,policy_revision:'review-a'}})")
    apply = page.get_by_role("button", name="정지 상태에서 적용", exact=True)
    apply.click()
    page.locator("dialog.ui-confirm ui-button[kind=quiet]").click()
    assert page.evaluate("window.calls.length") == 0
    apply.click()
    page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
    _response(page, error="ROBOT_MUST_BE_STOPPED")
    expect(apply).to_be_disabled()
    page.evaluate("window.emit({...window.initial,staged:{...window.initial.active,policy_revision:'review-a'}})")
    expect(apply).to_be_enabled()
    expect(page.get_by_text("정책 적용 실패: ROBOT_MUST_BE_STOPPED", exact=True)).to_be_visible()
    signal = page.locator('[data-signal="GREEN"]')
    expect(signal).to_be_disabled()
    signal.dispatch_event("click")
    assert page.evaluate("window.calls.length") == 1
    apply.click()
    page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
    _response(page, applied=True)
    expect(apply).to_be_disabled()
    expect(page.get_by_text("정지 상태에서 정책 적용을 요청했습니다.", exact=True)).to_be_visible()
    page.evaluate("window.emit({...window.initial,active:{...window.initial.active,policy_revision:'review-a'}})")
    expect(page.get_by_text("정지 상태에서 정책 적용을 요청했습니다.", exact=True)).to_be_visible()
    assert page.evaluate("window.calls.map(c=>c.path)") == ["/api/v1/traffic/policy/apply"] * 2


def test_poll_failure_retains_draft_and_result_but_revokes_old_availability(panel):
    page = panel
    revision = page.locator('[name="policy_revision"]')
    stage = page.get_by_text("정책 검토본 저장", exact=True)
    apply = page.get_by_role("button", name="정지 상태에서 적용", exact=True)
    revision.fill("review-a")
    stage.click()
    _response(page)
    expect(stage).to_be_enabled()
    page.evaluate("window.emit({...window.initial,staged:{...window.initial.active,policy_revision:'review-a'},simulation_signal:{available:true}})")
    signal = page.locator('[data-signal="GREEN"]')
    expect(signal).to_be_enabled()
    page.evaluate("window.pollError(new Error('연결 끊김'))")
    expect(apply).to_be_disabled()
    expect(signal).to_be_disabled()
    assert apply.get_attribute("reason") == "현재 정책 정보를 확인할 수 없습니다"
    expect(stage).to_be_enabled()
    expect(revision).to_have_value("review-a")
    expect(page.get_by_text("검토본 저장됨: review-a", exact=True)).to_be_visible()
    apply.dispatch_event("click")
    signal.dispatch_event("click")
    assert page.evaluate("window.calls.length") == 1
    revision.fill("local-draft")
    page.evaluate("window.emit({...window.initial,staged:{...window.initial.active,policy_revision:'review-a'},simulation_signal:{available:true}})")
    expect(signal).to_be_enabled()
    expect(revision).to_have_value("local-draft")
    assert apply.get_attribute("reason") == "입력 변경: 검토본을 다시 저장하세요"


def test_closed_poll_cannot_revert_mutation_and_unmount_prevents_restart(panel):
    page = panel
    page.evaluate("""() => {
      window.oldData=window.emit; window.oldError=window.pollError;
      window.oldSnapshot={...window.initial,staged:{...window.initial.active,policy_revision:'old-review'}};
      window.emit(window.oldSnapshot);
    }""")
    revision = page.locator('[name="policy_revision"]')
    revision.fill("new-review")
    page.get_by_text("정책 검토본 저장", exact=True).click()
    _response(page, revision="new-review")
    apply = page.get_by_role("button", name="정지 상태에서 적용", exact=True)
    expect(apply).to_be_enabled()
    page.evaluate("window.oldData(window.oldSnapshot); window.oldError(new Error('old poll failed'))")
    expect(revision).to_have_value("new-review")
    expect(page.locator(".traffic-policy-review")).to_contain_text("검토본: new-review")
    expect(apply).to_be_enabled()
    page.evaluate("() => { window.beforeApply=window.emit; }")
    apply.click()
    page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
    _response(page, revision="new-review", applied=True)
    expect(apply).to_be_disabled()
    page.evaluate("window.beforeApply(window.oldSnapshot)")
    expect(revision).to_have_value("new-review")
    expect(page.locator(".traffic-policy-review")).to_contain_text("저장된 검토본 없음")
    expect(apply).to_be_disabled()
    page.evaluate("() => { window.beforeClose=window.emit; }")
    revision.fill("closing-draft")
    page.get_by_text("정책 검토본 저장", exact=True).click()
    page.evaluate("() => { window.unmount(); window.savedDOM=document.body.innerHTML; window.savedPoll=window.emit; }")
    _response(page, revision="closing-draft")
    page.evaluate("window.beforeClose(window.oldSnapshot); window.oldError(new Error('late close'))")
    assert page.evaluate("document.body.innerHTML===window.savedDOM && window.emit===window.savedPoll")
    before = page.evaluate("window.calls.length")
    page.get_by_text("정책 검토본 저장", exact=True).dispatch_event("click")
    assert page.evaluate("window.calls.length") == before
