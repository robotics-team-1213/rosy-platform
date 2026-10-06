"""Opt-in real browser regressions; no robot or OMX transport is connected.

Run with ROSY_BROWSER_TESTS=1 and installed Playwright Chromium.
"""

import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest
import uvicorn
import yaml

from test_cell_job_api import _setup
from fleet.server.cell_compiler import PalletizingCellJobCompiler

pytestmark = pytest.mark.skipif(os.environ.get("ROSY_BROWSER_TESTS") != "1",
                                reason="opt-in real Chromium browser scenario")
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def browser_site(tmp_path):
    from playwright.sync_api import sync_playwright

    client, tasks, _ = _setup(
        tmp_path, compiler=PalletizingCellJobCompiler(tol_m=0.001),
        cell_app_service_id="cell-service", web_common=ROOT / "shared/web", start_task_dispatcher=False)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(
        client.app, log_level="error", timeout_graceful_shutdown=3,
        timeout_keep_alive=1))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "test Fleet failed to start"
        control = tasks.store.dispatch_control()
        if not control["dispatch_enabled"]:
            tasks.store.rearm_dispatch(expected_generation=control["generation"], actor_id="operator-1")
        with sync_playwright() as toolkit:
            browser = toolkit.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(origin + "/console/cell")
                page.wait_for_load_state("networkidle")
                yield page, tasks, origin
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        assert not worker.is_alive(), "test Fleet worker did not stop"


def _prepare(page):
    from playwright.sync_api import expect

    page.locator("#credential input").fill("operator-secret")
    page.locator("#connect").click()
    expect(page.locator("#session")).to_contain_text("operator-1")
    for kind in ("recipe", "cell"):
        path = ROOT / f"operations/processes/cell/examples/omx_sim/{kind}.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if kind == "recipe":
            page.locator("summary").filter(has_text="레시피 문서 편집").click()
        else:
            page.locator("summary").filter(has_text="셀 티칭 문서 편집").click()
        page.locator(f"#{kind}-document").fill(json.dumps(document))
        page.locator(f"#{kind}-save").click()
        expect(page.locator(f"#{kind}-revision")).to_contain_text("저장된 버전")
    page.locator("#compile").click()
    expect(page.locator("#summary")).to_contain_text("18회 전송")


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_cell_page_keeps_emergency_stop_in_first_view(browser_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    page.set_viewport_size({"width": width, "height": height})
    if output := os.environ.get("ROSY_SHOT_DIR"):
        Path(output).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(output) / f"fleet-cell-initial-{width}x{height}.png"))
    stop = page.locator("#estop")
    expect(stop).to_be_visible()
    box = stop.bounding_box()
    assert box["y"] + box["height"] <= height
    if width < 480:
        brand = page.locator("ui-topbar ui-brand b").bounding_box()
        assert brand["x"] + brand["width"] <= box["x"] + 1, (brand, box)
        assert page.locator("ui-topbar ui-brand b").evaluate("node => node.scrollWidth <= node.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_cell_emergency_stop_uses_console_session_and_reports_uncertainty(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    page.evaluate("sessionStorage.setItem('rosy-console-token', 'operator-secret')")
    page.reload()
    page.set_viewport_size({"width": 320, "height": 568})
    assert page.locator("#credential input").input_value() == "operator-secret"
    replies = {"status": 200}
    sent = []

    def stop(route):
        sent.append(route.request)
        if replies["status"] == 200:
            route.fulfill(json={"total": 3, "stopped": 1, "robots": []})
        else:
            route.fulfill(status=503, json={"detail": {"code": "UNAVAILABLE"}})

    page.route("**/api/fleet/estop", stop)
    page.locator("#estop").click()
    expect(page.locator("#estop-feedback")).to_contain_text("정지 요청 응답: 1/3 · 물리 정지 미확인")
    assert page.locator("#estop-feedback").get_attribute("state") == "error"
    feedback = page.locator("#estop-feedback").bounding_box()
    content = page.locator("main > ui-section").first.bounding_box()
    assert abs(feedback["x"] - content["x"]) <= 1
    assert abs(feedback["width"] - content["width"]) <= 1
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / "fleet-cell-estop-partial-320x568.png"))
    replies["status"] = 503
    page.locator("#estop").click()
    expect(page.locator("#estop-feedback")).to_contain_text("비상 정지 결과 확인 불가")
    if output:
        page.screenshot(path=str(Path(output) / "fleet-cell-estop-unknown-320x568.png"))
    assert len(sent) == 2
    assert all(request.headers.get("authorization") == "Bearer operator-secret" for request in sent)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_cell_saved_documents_explains_first_and_empty_states(browser_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    page.set_viewport_size({"width": width, "height": height})
    status = page.locator("#saved-status")
    expect(status).to_contain_text("접속하면 저장된 문서를 확인할 수 있습니다")
    page.locator("#credential input").fill("operator-secret")
    page.locator("#connect").click()
    expect(status).to_contain_text("저장된 문서가 없습니다")
    expect(status).to_contain_text("레시피와 셀 문서를 작성하고 저장하세요")
    assert page.locator("#saved").is_hidden()
    page.locator("#compile").click()
    expect(page.locator("#summary")).to_contain_text("두 문서를 저장하거나 불러오세요")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        status.scroll_into_view_if_needed()
        page.screenshot(path=str(Path(output) / f"fleet-cell-empty-{width}x{height}.png"))


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_cell_panels_and_compact_actions_use_uniform_width(browser_site, width, height):
    page, _, _ = browser_site
    page.set_viewport_size({"width": width, "height": height})
    panels = [panel.bounding_box() for panel in page.locator(".documents > ui-section").all()]
    assert len(panels) == 2 and abs(panels[0]["width"] - panels[1]["width"]) <= 1
    if width < 480:
        assert abs(panels[0]["x"] - panels[1]["x"]) <= 1
        preview_head = page.locator("#compile").locator("..").bounding_box()
        preview_action = page.locator("#compile").bounding_box()
        assert abs(preview_action["x"] - preview_head["x"]) <= 1
        assert abs(preview_action["width"] - preview_head["width"]) <= 1
        for group in page.locator("main .actions").all():
            row = group.bounding_box()
            for action in group.locator("ui-button, a").all():
                box = action.bounding_box()
                assert abs(box["x"] - row["x"]) <= 1
                assert abs(box["width"] - row["width"]) <= 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"fleet-cell-widths-{width}x{height}.png"), full_page=True)


def test_cell_saved_documents_failure_retry_and_credential_change(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    page.set_viewport_size({"width": 320, "height": 568})
    page.route("**/api/fleet/cell-app/documents", lambda route: route.fulfill(status=503, body="unavailable"))
    page.locator("#credential input").fill("operator-secret")
    page.locator("#connect").click()
    status = page.locator("#saved-status")
    expect(status).to_have_attribute("state", "error")
    expect(status).to_contain_text("접속 상태를 확인하고 다시 시도하세요")
    assert page.locator("#saved").is_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        status.scroll_into_view_if_needed()
        page.screenshot(path=str(Path(output) / "fleet-cell-list-error-320x568.png"))
    page.unroute("**/api/fleet/cell-app/documents")
    page.locator("#connect").click()
    expect(status).to_have_attribute("state", "empty")
    _prepare(page)
    expect(page.locator("#saved li")).to_have_count(2)
    expect(status).to_be_hidden()
    page.locator("#credential input").fill("different-token")
    expect(status).to_have_attribute("state", "unavailable")
    assert page.locator("#saved").is_hidden()
    expect(page.locator("#session")).to_have_text("접속 전")
    expect(page.locator("#notice")).to_contain_text("운영자 계정으로 접속해")


@pytest.mark.parametrize("denial,notice", [(401, "토큰"), (403, "운영자 토큰을 확인하고 다시 접속하세요")])
def test_cell_auth_denial_clears_previous_session(browser_site, denial, notice):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    page.set_viewport_size({"width": 320, "height": 568})
    _prepare(page)
    expect(page.locator("#saved li")).to_have_count(2)
    page.route("**/api/fleet/session", lambda route: route.fulfill(status=denial, body="unauthorized"))
    page.locator("#connect").click()
    expect(page.locator("#notice")).to_contain_text(notice)
    expect(page.locator("#session")).to_have_text("접속 전")
    expect(page.locator("#saved-status")).to_contain_text("접속하면")
    assert page.locator("#saved").is_hidden()
    assert page.locator("#propose").is_disabled()
    assert page.locator("#recipe-save").is_disabled()
    expect(page.locator("#recipe-revision")).to_have_text("저장 전")
    expect(page.locator("#summary")).not_to_contain_text("18회 전송")
    notice_box = page.locator("#notice").bounding_box()
    assert notice_box and 0 <= notice_box["y"] < 568
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"fleet-cell-auth-{denial}-320x568.png"))


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_cell_save_conflict_marks_draft_and_recovers(browser_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    page.set_viewport_size({"width": width, "height": height})
    _prepare(page)
    recipe = json.loads(page.locator("#recipe-document").input_value())
    recipe["box"]["mass_kg"] = 0.04
    page.locator("#recipe-document").fill(json.dumps(recipe))
    revision = page.locator("#recipe-revision")
    expect(revision).to_contain_text("저장 전")
    page.route("**/api/fleet/cell-app/documents/recipe/*",
               lambda route: route.fulfill(status=409, body='{"detail":{"code":"revision_conflict"}}'))
    page.locator("#recipe-save").click()
    expect(revision).to_contain_text("저장 충돌")
    expect(revision).to_contain_text("작성 내용을 복사")
    panel = page.locator(".documents > ui-section").first.bounding_box()
    status_box = revision.bounding_box()
    assert abs(panel["x"] - status_box["x"]) <= 1
    assert abs(panel["width"] - status_box["width"]) <= 1
    assert page.locator("#propose").is_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        revision.scroll_into_view_if_needed()
        page.screenshot(path=str(Path(output) / f"fleet-cell-save-conflict-{width}x{height}.png"))
    page.unroute("**/api/fleet/cell-app/documents/recipe/*")
    page.locator("#recipe-load").click()
    expect(revision).to_contain_text("저장된 버전")
    page.locator("#recipe-document").fill(json.dumps(recipe))
    expect(revision).to_contain_text("저장 전")
    page.locator("#recipe-save").click()
    expect(revision).to_contain_text("저장된 버전")


def test_cell_save_unavailable_does_not_claim_success(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    page.set_viewport_size({"width": 320, "height": 568})
    _prepare(page)
    recipe = json.loads(page.locator("#recipe-document").input_value())
    recipe["box"]["mass_kg"] = 0.04
    page.locator("#recipe-document").fill(json.dumps(recipe))
    page.route("**/api/fleet/cell-app/documents/recipe/*",
               lambda route: route.fulfill(status=503, body="unavailable"))
    page.locator("#recipe-save").click()
    revision = page.locator("#recipe-revision")
    expect(revision).to_contain_text("저장 결과 확인 불가")
    expect(revision).to_contain_text("최신 버전")
    assert page.locator("#propose").is_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        revision.scroll_into_view_if_needed()
        page.screenshot(path=str(Path(output) / "fleet-cell-save-unavailable-320x568.png"))


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_cell_preview_unavailable_clears_old_result_and_recovers(browser_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    page.set_viewport_size({"width": width, "height": height})
    _prepare(page)
    expect(page.locator("#summary")).to_contain_text("18회 전송")
    page.route("**/api/fleet/cell-app/compile",
               lambda route: route.fulfill(status=503, body="unavailable"))
    page.locator("#compile").click()
    summary = page.locator("#summary")
    expect(summary).to_contain_text("미리보기 결과 확인 불가")
    expect(summary).to_contain_text("다시 확인")
    panel = page.locator("main > ui-section").first.bounding_box()
    status_box = summary.bounding_box()
    assert abs(panel["x"] - status_box["x"]) <= 1
    assert abs(panel["width"] - status_box["width"]) <= 1
    assert page.locator("#propose").is_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        summary.scroll_into_view_if_needed()
        page.screenshot(path=str(Path(output) / f"fleet-cell-preview-unavailable-{width}x{height}.png"))
    page.unroute("**/api/fleet/cell-app/compile")
    page.locator("#compile").click()
    expect(summary).to_contain_text("18회 전송")


def test_delayed_compile_cannot_restore_preview_for_changed_document(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    _prepare(page)

    def delayed(route):
        response = route.fetch()
        page.evaluate("""() => {
            const field = document.getElementById('recipe-document');
            field.value = '{}'; field.dispatchEvent(new Event('input', {bubbles:true}));
        }""")
        route.fulfill(response=response)

    page.route("**/api/fleet/cell-app/compile", delayed)
    page.locator("#compile").click()
    expect(page.locator("#notice")).to_contain_text("입력 또는 계정이 바뀌었습니다")
    assert page.locator("#propose").get_attribute("disabled") is not None
    assert page.locator("#layout rect").count() == 0


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_reviewed_generation_conflict_and_cancel_are_explicit(browser_site, width, height):
    from playwright.sync_api import expect

    page, tasks, origin = browser_site
    page.set_viewport_size({"width": width, "height": height})
    _prepare(page)
    expect(page.locator("#layout rect")).to_have_count(4)
    expect(page.locator("#layout-layer option")).to_have_count(4)
    page.locator("#workcell").fill("omx_sim")
    page.locator("#instance").fill("omx_sim_01")
    page.locator("#propose").click()
    expect(page.locator("#proposal")).to_contain_text("승인 대기")
    assert "PROPOSED" not in page.locator("#proposal").inner_text()
    page.locator("#read-job").click()
    expect(page.locator("#job-summary")).to_contain_text("제안됨")
    expect(page.locator("#notice")).to_contain_text("확인한 정지 세대")
    reviewed = tasks.store.dispatch_control()["generation"]
    stopped = tasks.store.trip_stop_latch(actor_id="operator-1")
    sent = []
    page.on("request", lambda request: sent.append(request.post_data_json)
            if request.url.endswith("/admit") else None)
    page.locator("#admit").click()
    expect(page.locator("#notice")).to_contain_text("stop generation is closed or changed")
    assert sent[0]["expected_generation"] == reviewed
    assert page.locator("#admit").get_attribute("disabled") is not None
    tasks.store.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator-1")
    page.locator("#read-job").click()
    expect(page.locator("#notice")).to_contain_text("확인한 정지 세대")
    page.locator("#admit").click()
    expect(page.locator("#notice")).to_contain_text("작업 실행 대기")
    cancelled = []
    page.on("request", lambda request: cancelled.append(request)
            if request.url.endswith("/cancel") else None)
    page.locator("#cancel").click()
    dialog = page.locator("dialog.ui-confirm")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("실행 중인 장치를 정지하지 않습니다")
    assert page.locator("#estop").is_visible()
    title = page.locator("ui-topbar ui-brand b").bounding_box()
    stop = page.locator("#estop").bounding_box()
    assert title["x"] + title["width"] <= stop["x"] + 1, (title, stop)
    assert page.locator("#estop").evaluate("node => node.scrollWidth <= node.clientWidth")
    if width < 480:
        connect = page.locator("#connect").bounding_box()
        session = page.locator("#session").bounding_box()
        assert connect["x"] + connect["width"] <= width, connect
        assert session["x"] + session["width"] <= stop["x"] + 1, session
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"fleet-cell-cancel-confirm-{width}x{height}.png"))
    dialog.locator("ui-button[kind='quiet']").click()
    expect(dialog).to_have_count(0)
    assert cancelled == []
    page.route("**/api/fleet/estop", lambda route: route.fulfill(json={"total": 0, "stopped": 0, "robots": []}))
    page.locator("#cancel").click()
    expect(dialog).to_be_visible()
    page.locator("#estop").click()
    expect(dialog).to_have_count(0)
    assert cancelled == []
    page.locator("#cancel").click()
    dialog.locator("ui-button[kind='irreversible']").click()
    expect(page.locator("#notice")).to_contain_text("운영자가 취소함")
    assert "CANCELLED_BY_OPERATOR" not in page.locator("#job-summary").inner_text()
    assert len(cancelled) == 1
    assert page.locator("#resume").get_attribute("disabled") is not None
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_failed_job_read_clears_actionable_snapshot(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    _prepare(page)
    page.locator("#workcell").fill("omx_sim")
    page.locator("#instance").fill("omx_sim_01")
    page.locator("#propose").click()
    expect(page.locator("#proposal")).to_contain_text("승인 대기")
    page.locator("#read-job").click()
    expect(page.locator("#notice")).to_contain_text("확인한 정지 세대")
    page.route("**/api/fleet/cell-jobs/*", lambda route: route.fulfill(
        status=503, content_type="application/json", body='{"detail":{"code":"TEST_READ_UNAVAILABLE"}}'))
    page.locator("#read-job").click()
    expect(page.locator("#notice")).to_contain_text("TEST_READ_UNAVAILABLE")
    assert page.locator("#admit").get_attribute("disabled") is not None


def test_import_updates_existing_revision_and_guided_fields(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    _prepare(page)
    recipe = json.loads(page.locator("#recipe-document").input_value())
    recipe["box"]["mass_kg"] = 0.03
    page.locator("#recipe-file").set_input_files({
        "name": "recipe.json", "mimeType": "application/json", "buffer": json.dumps(recipe).encode()})
    expect(page.locator("#notice")).to_contain_text("파일을 불러왔습니다")
    assert page.locator("#propose").get_attribute("disabled") is not None
    assert page.locator("#recipe-fields input").count() == 6
    assert page.locator("#cell-fields input").count() == 7
    page.locator("#recipe-save").click()
    expect(page.locator("#notice")).to_contain_text("문서 저장 완료")
    page.locator("#recipe-fields input").first.fill("0.041")
    assert json.loads(page.locator("#recipe-document").input_value())["box"]["length"] == 0.041
    page.locator("#recipe-save").click()
    expect(page.locator("#notice")).to_contain_text("문서 저장 완료")
    page.locator("#compile").click()
    expect(page.locator("#summary")).to_contain_text("18회 전송")


def test_manual_sheet_choice_preserves_thickness_and_requires_operator_barrier(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    _prepare(page)
    page.locator("#recipe-sheet-handling").select_option("operator")
    draft = json.loads(page.locator("#recipe-document").input_value())
    assert draft["schema"] == "rosy_cell.recipe/2"
    assert draft["slip_sheet"] == {"handling": "operator", "thickness": 0.002}
    expect(page.locator("#propose")).to_have_attribute("disabled", "")
    page.locator("#recipe-save").click()
    expect(page.locator("#notice")).to_contain_text("저장 완료")
    page.locator("#compile").click()
    expect(page.locator("#summary")).to_contain_text("16회 전송")
    preview = json.loads(page.locator("#preview").text_content())
    assert len([step for step in preview["steps"]
                if step["kind"] == "operator_sheet"]) == 2


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_sheet_access_unavailable_is_visible_and_generic_resume_is_disabled(browser_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    page.set_viewport_size({"width": width, "height": height})
    page.locator("#credential input").fill("operator-secret")
    page.locator("#connect").click()
    expect(page.locator("#session")).to_contain_text("operator-1")
    job = {"mission_id": "sheet-held", "status": "HOLD", "current_step_index": 0,
           "reason": "OPERATOR_SHEET_ACCESS_UNAVAILABLE", "steps": [
               {"step_index": 0, "status": "HOLD", "step": {"inputs": {
                   "pallet_id": "A", "layer_index": 1, "item": "box"}}}],
           "operator_checkpoints": [{"checkpoint_id": "a" * 64, "status": "WAITING_ACCESS",
                                     "pallet_id": "A", "layer_index": 1, "thickness_m": 0.002}]}
    page.route("**/api/fleet/cell-jobs/sheet-held", lambda route: route.fulfill(json={"job": job}))
    page.locator("#mission-id").fill("sheet-held")
    page.locator("#read-job").click()
    expect(page.locator("#job-summary")).to_contain_text("작업 보류")
    expect(page.locator("#job-summary")).to_contain_text("간지")
    assert "OPERATOR_SHEET_ACCESS_UNAVAILABLE" not in page.locator("#job-summary").inner_text()
    assert "HOLD" not in page.locator("#step-progress").inner_text()
    expect(page.locator("#job-state")).to_contain_text("OPERATOR_SHEET_ACCESS_UNAVAILABLE")
    expect(page.locator("#sheet-progress")).to_contain_text("A · 2층")
    expect(page.locator("#sheet-progress")).to_contain_text("2 mm")
    expect(page.locator("#sheet-progress")).to_contain_text("삽입 확인 대기")
    expect(page.locator("#resume")).to_have_attribute("disabled", "")
    expect(page.locator("#resume")).to_have_attribute("reason", "작업자 간지 삽입 확인 대기")
    expect(page.locator("#sheet-progress")).to_contain_text("아직 진행할 수 없습니다")
    stop = page.locator("#estop").bounding_box()
    assert stop and stop["y"] + stop["height"] <= height
    if width < 480:
        header = page.locator("ui-topbar").bounding_box()
        assert header and header["height"] <= height * 0.2, header
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.locator("#job-summary").scroll_into_view_if_needed()
        page.screenshot(path=str(Path(output) / f"fleet-cell-held-sheet-{width}x{height}.png"))


def test_structured_drafts_compile_box_only_and_survive_reload(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    _prepare(page)
    page.locator('#recipe-structure [data-path="layers.1.slip_sheet_below"]').uncheck()
    page.locator("#recipe-sheet-enabled").uncheck()
    page.locator('#recipe-structure [data-path="pallets.0.id"]').fill("A-review")
    page.locator("#cell-structure summary").filter(has_text="프레임 pallet_a").click()
    page.locator('#cell-structure [data-path="frames.pallet_a.origin.1"]').fill("0.012")
    assert page.locator("#propose").get_attribute("disabled") is not None
    for kind in ("recipe", "cell"):
        page.locator(f"#{kind}-save").click()
        expect(page.locator("#notice")).to_contain_text("문서 저장 완료")
    page.locator("#compile").click()
    expect(page.locator("#summary")).to_contain_text("16회 전송")
    assert "slip_sheet" not in json.loads(page.locator("#recipe-document").input_value())
    page.reload()
    page.locator("#credential input").fill("operator-secret")
    page.locator("#connect").click()
    expect(page.locator("#session")).to_contain_text("operator-1")
    for kind in ("recipe", "cell"):
        page.locator(f"#{kind}-load").click()
        expect(page.locator("#notice")).to_contain_text("저장된 문서를 불러왔습니다")
    expect(page.locator('#recipe-structure [data-path="pallets.0.id"]')).to_have_value("A-review")
    expect(page.locator('#cell-structure [data-path="frames.pallet_a.origin.1"]')).to_have_value("0.012")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_structured_layer_edit_retains_canonical_errors_and_has_no_dispatch(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    _prepare(page)
    execution_requests = []
    page.on("request", lambda request: execution_requests.append(request.url)
            if request.url.endswith(("/proposals", "/admit")) else None)
    page.locator("#recipe-layer-add").click()
    expect(page.locator('#recipe-structure [data-path="layers.2.pattern"]')).to_have_value("grid")
    page.locator("#recipe-save").click()
    expect(page.locator("#notice")).to_contain_text("문서 저장 완료")
    page.locator("#compile").click()
    expect(page.locator("#notice")).to_contain_text("stack")
    assert page.locator("#propose").get_attribute("disabled") is not None
    assert not execution_requests
    page.locator('[data-remove-layer="2"]').click()
    page.locator("#recipe-save").click()
    expect(page.locator("#notice")).to_contain_text("문서 저장 완료")
    page.locator("#compile").click()
    expect(page.locator("#summary")).to_contain_text("18회 전송")


def test_saved_structured_controls_stay_locked_until_list_read_finishes(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    _prepare(page)
    locked = []

    def delayed_list(route):
        response = route.fetch()
        assert page.locator("#saved-status").get_attribute("state") == "pending"
        locked.append(page.evaluate("""() => {
            const fields = [...document.querySelectorAll('#recipe-structure input, #recipe-structure select')];
            const before = document.getElementById('recipe-document').value;
            const add = document.getElementById('recipe-layer-add');
            const disabled = add.hasAttribute('disabled') && fields.every(field => field.disabled);
            add.click();
            return disabled && document.getElementById('recipe-document').value === before;
        }"""))
        route.fulfill(response=response)

    page.route("**/api/fleet/cell-app/documents", delayed_list)
    page.locator("#recipe-save").click()
    expect(page.locator("#notice")).to_contain_text("문서 저장 완료")
    assert locked == [True]
    expect(page.locator("#saved li")).to_have_count(2)
    expect(page.locator("#saved-status")).to_be_hidden()
