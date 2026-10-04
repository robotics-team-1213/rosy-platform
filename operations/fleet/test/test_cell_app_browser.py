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


def test_reviewed_generation_conflict_and_cancel_are_explicit(browser_site):
    from playwright.sync_api import expect

    page, tasks, origin = browser_site
    _prepare(page)
    expect(page.locator("#layout rect")).to_have_count(4)
    expect(page.locator("#layout-layer option")).to_have_count(4)
    page.locator("#workcell").fill("omx_sim")
    page.locator("#instance").fill("omx_sim_01")
    page.locator("#propose").click()
    expect(page.locator("#proposal")).to_contain_text("PROPOSED")
    page.locator("#read-job").click()
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
    expect(page.locator("#notice")).to_contain_text("작업 READY")
    page.locator("#cancel").click()
    expect(page.locator("#notice")).to_contain_text("CANCELLED_BY_OPERATOR")
    assert page.locator("#resume").get_attribute("disabled") is not None
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_failed_job_read_clears_actionable_snapshot(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
    _prepare(page)
    page.locator("#workcell").fill("omx_sim")
    page.locator("#instance").fill("omx_sim_01")
    page.locator("#propose").click()
    expect(page.locator("#proposal")).to_contain_text("PROPOSED")
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


def test_sheet_access_unavailable_is_visible_and_generic_resume_is_disabled(browser_site):
    from playwright.sync_api import expect

    page, _, _ = browser_site
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
    expect(page.locator("#sheet-progress")).to_contain_text("A · 2층")
    expect(page.locator("#sheet-progress")).to_contain_text("2 mm")
    expect(page.locator("#sheet-progress")).to_contain_text("삽입 확인 대기")
    expect(page.locator("#resume")).to_have_attribute("disabled", "")
    expect(page.locator("#resume")).to_have_attribute("reason", "작업자 간지 삽입 확인 대기")
    expect(page.locator("#sheet-progress")).to_contain_text("아직 진행할 수 없습니다")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


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
