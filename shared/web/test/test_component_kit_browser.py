"""Shared compositions: real keyboard/form/selection behavior on the served gallery."""

import json
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
WEB = Path(__file__).resolve().parents[1]
HOST = "http://rosy.test"


@pytest.fixture
def gallery():
    from playwright.sync_api import sync_playwright, expect

    assets = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]

    def serve(route):
        name = route.request.url.split("/common/", 1)[-1].split("?", 1)[0]
        if name not in assets:
            return route.fulfill(status=404, body="not registered")
        route.fulfill(path=str(WEB / name), content_type=assets[name])

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(HOST + "/**", serve)
        response = page.goto(HOST + "/common/component-gallery.html")
        assert response.status == 200, "component gallery must be an installed shared asset"
        expect(page.locator("#kit-ready")).to_have_text("견본 준비 완료")
        yield page
        assert not errors, errors
        browser.close()


def test_form_errors_and_failed_save_keep_input(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#example-save").click()
    expect(page.locator("#example-name")).to_be_focused()
    expect(page.locator("#example-name")).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#example-errors")).to_contain_text("이름을 입력하세요")
    page.locator("#example-name").fill("긴 작업 이름")
    page.locator("#example-fail-save").check()
    page.locator("#example-save").click()
    expect(page.locator("#example-result")).to_contain_text("저장하지 못했습니다")
    expect(page.locator("#example-name")).to_have_value("긴 작업 이름")
    page.locator("#example-fail-save").uncheck()
    page.locator("#example-save").click()
    expect(page.locator("#example-result")).to_contain_text("다시 조회해 확인")


def test_list_search_selection_and_return_keep_identity(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#list-search").fill("장비 12")
    expect(page.locator("#list-count")).to_have_text("1개")
    page.locator("#device-list [data-open]").click()
    expect(page.locator("#device-detail")).to_contain_text("장비 12")
    page.get_by_role("button", name="목록으로 돌아가기", exact=True).click()
    expect(page.locator("#device-list [data-open]")).to_be_focused()
    page.locator("#list-search").fill("일치 없음")
    expect(page.locator("#device-list")).to_contain_text("검색 결과가 없습니다")
    page.get_by_role("button", name="검색·필터 초기화").click()
    expect(page.locator("#list-count")).to_have_text("24개")


def test_bulk_selection_is_explicit_and_survives_sort(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#device-list input[data-select]").first.check()
    expect(page.locator("#list-selection")).to_contain_text("1개 선택")
    page.locator("#list-sort").select_option("descending")
    expect(page.locator("#list-selection")).to_contain_text("1개 선택")
    expect(page.locator("#select-page")).not_to_be_checked()
    page.locator("#select-page").check()
    expect(page.locator("#list-selection")).to_contain_text("9개 선택")
    expect(page.locator("#list-selection")).to_contain_text("불러온 전체 목록")
    page.locator("#list-next").click()
    page.locator("#list-next").click()
    expect(page.locator('#device-list input[data-select="device-1"]')).to_be_checked()
    page.get_by_role("button", name="선택 해제", exact=True).click()
    expect(page.locator("#select-page")).not_to_be_checked()


def test_pagination_and_no_invented_total(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#list-next").click()
    expect(page.locator("#list-page")).to_have_text("2 / 3")
    expect(page.locator('#device-list [data-open="device-9"]')).to_be_visible()
    page.locator("#more-items").click()
    expect(page.locator("#cursor-count")).to_have_text("6개 표시 · 전체 개수 미확인")


def test_bulk_action_uses_selected_ids_and_reports_partial_failure(gallery):
    from playwright.sync_api import expect
    page = gallery
    bulk = page.get_by_role("button", name="선택 자료 보류 견본", exact=True)
    expect(bulk).to_be_disabled()
    page.locator("#select-page").check()
    expect(bulk).to_be_enabled()
    bulk.click()
    expect(page.locator("#bulk-result")).to_contain_text("7개 적용 · 1개 실패")
    expect(page.locator("#list-selection")).to_contain_text("8개 선택")


def test_bulk_change_clamps_a_filtered_page_when_its_rows_leave(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#list-filter").select_option("ready")
    page.locator("#select-page").check()
    page.locator("#list-next").click()
    page.locator("#select-page").check()
    page.get_by_role("button", name="선택 자료 보류 견본", exact=True).click()
    expect(page.locator("#list-count")).to_have_text("1개")
    expect(page.locator("#list-page")).to_have_text("1 / 1")
    expect(page.locator("#device-list [data-open]")).to_have_count(1)


def test_async_states_retry_and_result_are_distinct(gallery):
    from playwright.sync_api import expect
    page = gallery
    for state, message in [("pending", "불러오는 중"), ("empty", "아직 자료가 없습니다"),
                           ("forbidden", "권한이 필요합니다"), ("error", "조회하지 못했습니다")]:
        page.locator("#state-choice").select_option(state)
        expect(page.locator("#state-example")).to_contain_text(message)
    page.get_by_role("button", name="자료 다시 조회", exact=True).click()
    expect(page.locator("#state-example")).to_contain_text("조회한 자료")
    page.locator("#operation-start").click()
    expect(page.locator("#operation-result")).to_contain_text("접수")
    expect(page.locator("#operation-result")).to_have_attribute("data-state", "accepted")
    expect(page.locator("#operation-result")).to_contain_text("실제 완료 미확인")
    page.locator("#operation-readback").click()
    expect(page.locator("#operation-result")).to_contain_text("실제 완료")


def test_file_validation_and_cancel_do_not_drop_name(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#file-example").set_input_files({"name": "notes.txt", "mimeType": "text/plain", "buffer": b"x"})
    expect(page.locator("#file-result")).to_contain_text("JSON 파일")
    page.locator("#file-example").set_input_files({"name": "recipe.json", "mimeType": "application/json", "buffer": b"{}"})
    expect(page.locator("#file-result")).to_contain_text("recipe.json")
    page.locator("#file-example").set_input_files([])
    expect(page.locator("#file-result")).to_contain_text("선택한 파일 없음")


def test_searchable_choice_and_date_validation(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#choice-search").fill("카메라 20")
    expect(page.locator("#choice-options option")).to_have_count(1)
    page.locator("#choice-options").select_option("camera-20")
    expect(page.locator("#choice-result")).to_have_text("camera-20")
    page.locator("#period-start").fill("2026-10-23")
    page.locator("#period-end").fill("2026-10-22")
    expect(page.locator("#period-result")).to_contain_text("종료일")
    page.locator("#period-end").fill("2026-10-24")
    expect(page.locator("#period-result")).to_contain_text("2026-10-24")


def test_keyboard_tabs_menu_and_panel_restore_focus(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.get_by_role("tab", name="근거 견본", exact=True).focus()
    page.keyboard.press("ArrowLeft")
    expect(page.get_by_role("tab", name="상태 견본", exact=True)).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("#tab-state")).to_be_visible()
    page.locator("#menu-open").click()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Escape")
    expect(page.locator("#menu-open")).to_be_focused()
    page.locator("#panel-open").click()
    expect(page.locator("#supplement-title")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator("#panel-open")).to_be_focused()


def test_initial_tab_order_skips_inactive_tab_after_custom_elements_connect(gallery):
    page = gallery
    assert page.locator('[role="tab"]').evaluate_all("nodes => nodes.map(node => node.tabIndex)") == [0, -1]
    page.locator("#context-tab-0").focus()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.id") != "context-tab-1"


def test_menu_navigation_preserves_the_destination_focus(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#menu-open").click()
    page.get_by_role("button", name="목록 견본으로 이동", exact=True).click()
    expect(page.locator("#collections")).to_be_focused()
    expect(page.locator("#collections-title")).to_be_in_viewport()
    expect(page.locator("#menu-open")).to_have_attribute("aria-expanded", "false")


def test_dirty_guard_cancel_preserves_edit(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#draft-name").fill("미저장 작업")
    page.locator("#draft-leave").click()
    expect(page.locator("dialog")).to_be_visible()
    page.get_by_role("button", name="취소", exact=True).click()
    expect(page.locator("#draft-name")).to_have_value("미저장 작업")
    expect(page.locator("#draft-result")).to_have_text("편집 유지")
    page.locator("#draft-leave").click()
    page.get_by_role("button", name="변경 버리기", exact=True).click()
    expect(page.locator("#draft-result")).to_have_text("이동 확인")


def test_timeline_steps_and_unknown_progress(gallery):
    from playwright.sync_api import expect
    page = gallery
    expect(page.locator("#progress-example")).to_contain_text("전체 진행률 미확인")
    expect(page.locator("#progress-example progress")).not_to_have_attribute("value", "0")
    page.locator("#progress-known").click()
    expect(page.locator("#progress-example progress")).to_have_attribute("value", "40")
    page.locator("#step-next").click()
    expect(page.locator('#steps-example [aria-current="step"]')).to_have_text("검증")
    expect(page.locator("#timeline-example")).to_contain_text("접수")
    expect(page.locator("#timeline-example")).to_contain_text("완료 미확인")


def test_unchanged_empty_file_is_not_a_dirty_edit(gallery):
    result = gallery.evaluate("""async () => {
      const {createDirtyGuard} = await import('/common/form-controls.js');
      const form = document.createElement('form');
      form.innerHTML = '<input type="file" name="file">';
      document.body.append(form);
      const guard = createDirtyGuard(form);
      await new Promise(resolve => setTimeout(resolve, 30));
      const dirty = guard.dirty;
      guard.dispose(); form.remove();
      return dirty;
    }""")
    assert result is False


def test_table_rejects_duplicate_visible_rows_even_with_unique_owner_ids(gallery):
    result = gallery.evaluate("""async () => {
      const {createDataTable} = await import('/common/collection-controls.js');
      const table = createDataTable({id:'bad-rows', columns:[], onOpen() {}});
      try {
        table.set([{id:'same',label:'A'}, {id:'same',label:'B'}], {allIds:['same']});
        return false;
      } catch (error) { return error instanceof TypeError; }
    }""")
    assert result is True


def test_group_errors_describe_all_radios_and_focus_enabled_member(gallery):
    result = gallery.evaluate("""async () => {
      const {createFormErrors} = await import('/common/form-controls.js');
      const form = document.createElement('form'), summary = document.createElement('div');
      form.innerHTML = '<fieldset><legend>모드</legend>' +
        '<label><input id="radio-a" name="mode" type="radio" value="a" disabled>A</label>' +
        '<label><input id="radio-b" name="mode" type="radio" value="b" aria-describedby="radio-help">B</label>' +
        '</fieldset><small id="radio-help">도움말 유지</small>';
      document.body.append(form, summary);
      const errors = createFormErrors(form, summary);
      try {
        errors.show({mode:'하나를 선택하세요'});
        const fields = [...form.querySelectorAll('input')];
        const result = {threw:false, focused:document.activeElement.id,
          invalid:fields.map(field => field.getAttribute('aria-invalid')),
          descriptions:fields.map(field => (field.getAttribute('aria-describedby') || '').split(/\\s+/)
            .map(id => document.getElementById(id)?.textContent || '').join(' '))};
        errors.clear(); result.help = fields[1].getAttribute('aria-describedby');
        return result;
      } catch (error) {return {threw:true, error:String(error)};}
      finally {form.remove(); summary.remove();}
    }""")
    assert not result["threw"], result
    assert result["focused"] == "radio-b"
    assert result["invalid"] == ["true", "true"]
    assert all("하나를 선택하세요" in value for value in result["descriptions"])
    assert result["help"] == "radio-help"


def test_removed_detail_target_is_explicit_and_back_has_focus_fallback(gallery):
    result = gallery.evaluate("""async () => {
      const {createDataTable,createPrimaryDetail} = await import('/common/collection-controls.js');
      let detail;
      const table = createDataTable({id:'refresh-list', columns:[],
        onOpen:(item,opener) => detail.open({title:item.label,body:document.createElement('p')},opener),
        onActiveRemoved:() => detail.unavailable('선택한 자료가 목록에서 없어졌습니다')});
      detail = createPrimaryDetail({id:'refresh-detail',label:'대상 상세',list:table.element});
      table.set([{id:'gone',label:'이전 대상'}]); document.body.append(detail.element);
      table.element.querySelector('[data-open]').click();
      table.set([], {allIds:[]});
      const message = detail.detail.textContent;
      detail.detail.querySelector('ui-button').click();
      const focused = document.activeElement === detail.element.firstElementChild;
      detail.element.remove();
      return {message, focused};
    }""")
    assert "선택한 자료가 목록에서 없어졌습니다" in result["message"]
    assert "이전 대상" not in result["message"]
    assert result["focused"]


def test_clipboard_retry_clears_prior_error_status(gallery):
    result = gallery.evaluate("""async () => {
      const {createLogView} = await import('/common/workflow-controls.js');
      let calls = 0;
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:{async writeText() {
        if (++calls === 1) throw new Error('refused');
      }}});
      const log = createLogView({label:'복사 시험',text:'공개 기록'});
      document.body.append(log.element); log.element.open = true;
      const copy = log.element.querySelector('ui-button'), status = log.element.querySelector('ui-status');
      copy.click(); await new Promise(resolve => setTimeout(resolve,0));
      const first = status.getAttribute('state');
      copy.click(); await new Promise(resolve => setTimeout(resolve,0));
      const second = status.getAttribute('state');
      log.set('새 기록'); const reset = status.getAttribute('state');
      log.element.remove(); return {first,second,reset};
    }""")
    assert result == {"first":"error", "second":"ready", "reset":"ready"}


@pytest.mark.parametrize("width,height", [(320, 568), (390, 844), (1366, 768), (1920, 1080)])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_gallery_responsive_actions_and_safety(gallery, width, height, theme):
    from playwright.sync_api import expect
    page = gallery
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for button in page.locator("#action-example ui-button").all():
        assert button.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / f"component-gallery-{theme}-{width}x{height}.png"), full_page=True)
    page.locator("#danger-example").click()
    expect(page.locator("dialog")).to_be_visible()
    stop = page.locator("#gallery-stop")
    assert stop.evaluate("node => !node.closest('[inert]')")
    box = stop.bounding_box()
    assert box["y"] >= 0 and box["y"] + box["height"] <= height
    assert stop.evaluate("node => { const r = node.getBoundingClientRect(); return node.contains(document.elementFromPoint(r.x + r.width/2, r.y + r.height/2)); }")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"component-confirm-{theme}-{width}x{height}.png"))
    stop.click()
    expect(page.locator("dialog")).not_to_be_visible()
