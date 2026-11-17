"""Shared compositions: real keyboard/form/selection behavior on the served gallery."""

import json
import os
from pathlib import Path
import re

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


@pytest.mark.parametrize("control", ["open", "select"])
def test_table_refresh_preserves_focus_only_inside_its_own_rows(gallery, control):
    from playwright.sync_api import expect
    page = gallery
    page.evaluate("""async () => {
      const {createDataTable} = await import('/common/collection-controls.js');
      window.focusTables = ['first-table', 'second-table'].map(id => {
        const table = createDataTable({id, columns: [{label: '이름', text: item => item.label}],
          onOpen: () => {}});
        table.set([{id: 'shared-row', label: id}]);
        document.body.append(table.element);
        return table;
      });
    }""")
    first = page.locator(f'#first-table [data-{control}="shared-row"]')
    second = page.locator(f'#second-table [data-{control}="shared-row"]')
    second.focus()
    page.evaluate("focusTables[0].set([{id: 'shared-row', label: '갱신된 첫째'}])")
    expect(second).to_be_focused()
    page.evaluate("focusTables[1].set([{id: 'shared-row', label: '갱신된 둘째'}])")
    expect(second).to_be_focused()
    first.focus()
    page.evaluate("focusTables[1].clearSelection()")
    expect(first).to_be_focused()
    page.evaluate("focusTables[0].selectPage(true)")
    expect(first).to_be_focused()
    expect(page.locator('#first-table [data-select="shared-row"]')).to_be_checked()


def test_list_toolbar_uses_owner_sort_choices_and_reports_selected_value(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.evaluate("""async () => {
      const {createListToolbar} = await import('/common/collection-controls.js');
      window.sortChanges = [];
      const toolbar = createListToolbar({id: 'history-list',
        sortLabel: '등록 시각 정렬',
        sortOptions: [{value: 'recent', label: '최근 등록 먼저'},
                      {value: 'oldest', label: '오래된 등록 먼저'}],
        onChange: change => window.sortChanges.push(change)});
      document.body.append(toolbar.element);
    }""")
    sort = page.get_by_role("combobox", name="등록 시각 정렬", exact=True)
    expect(sort).to_have_value("recent")
    expect(sort.locator("option")).to_have_text(["최근 등록 먼저", "오래된 등록 먼저"])
    sort.select_option("oldest")
    page.locator("#history-list-search").fill("작업")
    assert page.evaluate("window.sortChanges") == [
        {"query": "", "filter": "", "sort": "oldest"},
        {"query": "작업", "filter": "", "sort": "oldest"},
    ]


@pytest.mark.parametrize("document,table_id", [
    ("cell/cell.html", "catalog-table"), ("index.html", "tracking-positions"),
])
def test_product_table_fragments_load_shared_table_styles(gallery, document, table_id):
    page = gallery
    source = (WEB.parents[1] / "applications/fleet/web" / document).read_text(encoding="utf-8")
    links = "".join(link for link in re.findall(r"<link\b[^>]*>", source)
                    if 'href="/common/' in link)
    table = re.search(rf'<table\b[^>]*id="{table_id}"[^>]*>.*?</table>', source, re.S).group()
    table = table.replace(" hidden", "")
    table = re.sub(r"(<tbody[^>]*>).*?(</tbody>)",
                   lambda match: match[1] + "<tr><td>" + "긴출처" * 80 + "</td></tr>" + match[2], table, flags=re.S)
    for theme in ("dark", "light"):
        for width in (1366, 390):
            page.set_viewport_size({"width": width, "height": 844})
            page.set_content(f'<html data-theme="{theme}"><head>{links}</head><body>{table}</body></html>')
            assert page.locator(f"#{table_id}").evaluate("el => getComputedStyle(el).borderCollapse") == "collapse"
            assert page.locator(f"#{table_id} td").evaluate("el => getComputedStyle(el).overflowWrap") == "anywhere"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


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


def test_file_errors_block_native_form_until_corrected_or_cleared(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.evaluate("""() => {
      const component = document.getElementById('file-example').closest('.ui-control-stack');
      const form = document.createElement('form'); form.id = 'file-validation-form';
      component.before(form); form.append(component);
    }""")
    field = page.locator("#file-example")
    form = page.locator("#file-validation-form")
    field.set_input_files({"name": "notes.txt", "mimeType": "text/plain", "buffer": b"x"})
    expect(page.locator("#file-result")).to_contain_text("JSON 파일")
    assert not form.evaluate("el => el.checkValidity()")
    field.set_input_files({"name": "large.json", "mimeType": "application/json", "buffer": b"x" * (1024 * 1024 + 1)})
    expect(page.locator("#file-result")).to_contain_text("파일 크기")
    assert not form.evaluate("el => el.checkValidity()")
    field.set_input_files({"name": "recipe.json", "mimeType": "application/json", "buffer": b"{}"})
    assert form.evaluate("el => el.checkValidity()")
    field.set_input_files({"name": "notes.txt", "mimeType": "text/plain", "buffer": b"x"})
    assert not form.evaluate("el => el.checkValidity()")
    field.set_input_files([])
    assert form.evaluate("el => el.checkValidity()")
    expect(page.locator("#file-result")).to_contain_text("선택한 파일 없음")
    field.set_input_files({"name": "notes.txt", "mimeType": "text/plain", "buffer": b"x"})
    form.evaluate("el => el.addEventListener('reset', event => event.preventDefault(), {once:true})")
    form.evaluate("el => el.reset()")
    page.evaluate("() => new Promise(resolve => setTimeout(resolve, 0))")
    assert not form.evaluate("el => el.checkValidity()")
    assert field.evaluate("el => el.files[0].name") == "notes.txt"
    form.evaluate("el => el.reset()")
    expect(page.locator("#file-result")).to_contain_text("선택한 파일 없음")
    assert form.evaluate("el => el.checkValidity()")


def test_native_form_reset_clears_choice_and_date_validation(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.evaluate("""() => {
      const form = document.createElement('form'); form.id = 'reset-controls';
      document.body.append(form);
      form.append(document.getElementById('choice-options').closest('.ui-control-stack'),
                  document.getElementById('period-start').closest('fieldset'));
    }""")
    page.locator("#choice-search").fill("카메라 20")
    page.locator("#choice-options").select_option("camera-20")
    page.locator("#period-start").fill("2026-11-04")
    page.locator("#period-end").fill("2026-11-03")
    assert not page.locator("#reset-controls").evaluate("el => el.checkValidity()")
    page.locator("#reset-controls").evaluate("el => el.reset()")
    expect(page.locator("#choice-options")).to_have_value("")
    expect(page.locator("#choice-result")).to_have_text("")
    expect(page.locator("#period-end")).to_have_attribute("aria-invalid", "false")
    assert page.locator("#reset-controls").evaluate("el => el.checkValidity()")


def test_file_picker_disposal_ignores_pending_form_reset(gallery):
    page = gallery
    page.evaluate("""async () => {
      const {createFilePicker} = await import('/common/form-controls.js');
      window.resetEvents = 0;
      window.resetPicker = createFilePicker({id:'reset-file',label:'파일',onChange:() => resetEvents++});
      const form = document.createElement('form'); form.id = 'disposed-file-form';
      form.append(resetPicker.element); document.body.append(form);
    }""")
    page.locator("#reset-file").set_input_files({"name": "notes.txt", "mimeType": "text/plain", "buffer": b"x"})
    assert page.evaluate("resetEvents") == 1
    page.evaluate("() => { document.getElementById('disposed-file-form').reset(); resetPicker.dispose(); }")
    page.evaluate("() => new Promise(resolve => setTimeout(resolve, 0))")
    assert page.evaluate("resetEvents") == 1


def test_native_reset_keeps_a_newer_explicit_choice(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.evaluate("""() => {
      const form = document.createElement('form'); form.id = 'newer-choice-form';
      form.append(document.getElementById('choice-options').closest('.ui-control-stack'));
      document.body.append(form);
      form.reset();
      const select = document.getElementById('choice-options');
      select.value = 'camera-20'; select.dispatchEvent(new Event('change', {bubbles:true}));
    }""")
    page.evaluate("() => new Promise(resolve => setTimeout(resolve, 0))")
    expect(page.locator("#choice-options")).to_have_value("camera-20")
    expect(page.locator("#choice-result")).to_have_text("camera-20")


def test_searchable_choice_and_date_validation(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#choice-search").fill("카메라 20")
    expect(page.locator("#choice-options option")).to_have_count(2)
    expect(page.locator('#choice-options option[value=""]')).to_have_text("선택하세요")
    expect(page.locator('#choice-options option[value="camera-20"]')).to_have_count(1)
    page.locator("#choice-options").select_option("camera-20")
    expect(page.locator("#choice-result")).to_have_text("camera-20")
    page.locator("#period-start").fill("2026-10-23")
    page.locator("#period-end").fill("2026-10-22")
    expect(page.locator("#period-result")).to_contain_text("종료일")
    page.locator("#period-end").fill("2026-10-24")
    expect(page.locator("#period-result")).to_contain_text("2026-10-24")


def test_search_choice_keeps_owner_and_visible_selection_in_sync(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.evaluate("""async () => {
      const {createSearchSelect} = await import('/common/form-controls.js');
      window.choiceEvents = [];
      window.dynamicChoice = createSearchSelect({id:'dynamic-choice',label:'대상 선택',
        choices:[{value:'a',label:'대상 A'},{value:'b',label:'대상 B'}],
        onChange:value => window.choiceEvents.push(value)});
      document.body.append(window.dynamicChoice.element);
    }""")
    select = page.locator("#dynamic-choice-options")
    select.select_option("b")
    page.evaluate("dynamicChoice.update([{value:'b',label:'새 대상 B'},{value:'a',label:'대상 A'}])")
    expect(select).to_have_value("b")
    assert page.evaluate("choiceEvents") == ["b"]
    page.locator("#dynamic-choice-search").fill("대상 A")
    expect(select).to_have_value("")
    assert page.evaluate("choiceEvents") == ["b", ""]
    page.locator("#dynamic-choice-search").fill("")
    expect(select).to_have_value("")
    select.select_option("a")
    page.evaluate("dynamicChoice.update([{value:'b',label:'대상 B'}])")
    expect(select).to_have_value("")
    assert page.evaluate("choiceEvents") == ["b", "", "a", ""]
    page.evaluate("dynamicChoice.update([{value:'b',label:'대상 B'}])")
    assert page.evaluate("choiceEvents") == ["b", "", "a", ""]


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
    assert page.locator('#tabs-mount [role="tab"]').evaluate_all("nodes => nodes.map(node => node.tabIndex)") == [0, -1]
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
          summaryRole:summary.getAttribute('role'), summaryText:summary.textContent,
          said:document.querySelector('[role=alert][aria-live=assertive]')?.textContent || '',
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
    # one voice (C25): the visible summary carries no role; the shared announcer reads it once, urgent.
    assert result["summaryRole"] is None and "하나를 선택하세요" in result["summaryText"]
    assert "하나를 선택하세요" in result["said"]
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


def test_stop_stays_live_refusal_is_text_and_accept_is_not_a_stop(gallery):
    from playwright.sync_api import expect
    page, stop, result = gallery, gallery.locator("#gallery-stop"), gallery.locator("#stop-result")
    # Nothing repairs a hidden stop (no observer): the control is live from creation and the owners never touch it.
    expect(stop).to_be_visible()
    expect(stop).to_be_enabled()
    expect(stop).to_have_attribute("aria-disabled", "false")
    page.locator("#stop-refuse").check()
    stop.click()
    expect(result).to_contain_text("정지 요청 거절 · 운용 권한")
    page.locator("#stop-refuse").uncheck()
    stop.click()  # a second press sends again
    expect(result).to_contain_text("정지 요청 접수 · 실제 정지 확인 중")
    assert "정지됨" not in result.inner_text() and "정지 완료" not in result.inner_text()


def test_a_note_never_discards_a_stop_answer_still_in_flight(gallery):
    from playwright.sync_api import expect
    page, result = gallery, gallery.locator("#stop-result")
    page.locator("#stop-refuse").check()
    page.locator("#stop-slow").check()
    page.locator("#gallery-stop").click()
    page.locator("#stop-note").click()  # a logout/reload note lands before the refusal arrives
    expect(result).to_contain_text("합성 안내")
    expect(result).to_contain_text("정지 요청 거절 · 운용 권한")  # the refusal is still shown when it arrives


def test_account_states_and_connection_notice_keep_unknown_separate(gallery):
    from playwright.sync_api import expect
    page = gallery
    expect(page.locator("#gate-unavailable")).to_have_text("계정 확인 불가 · 권한 없음 아님")
    expect(page.locator("#gate-view")).to_have_text("로그인 안 됨 · 조회만")
    crit = page.locator("#stop-account-connection ui-tag[status='crit']")
    expect(crit).to_have_count(1)  # only the caller-raised danger sample is a fill (2026-11-14: a plain disconnect is a warning)
    expect(crit).to_have_text("연결 끊김 · 주행 중")
    assert page.locator("#notice-disconnected-danger").get_attribute("data-evidence") == "disconnected"
    plain = page.locator("#notice-disconnected ui-tag")
    expect(plain).to_have_count(1)
    expect(plain).to_have_attribute("status", "warn")
    expect(plain).to_have_text("연결 끊김")
    expect(plain.locator("svg.ui-icon")).to_have_count(1)
    for state in ("fresh", "delayed", "auth-wait", "unavailable"):
        expect(page.locator(f"#notice-{state} ui-tag")).to_have_count(0)
        expect(page.locator(f"#notice-{state}")).to_have_attribute("data-evidence", state)


def test_a_stop_answer_the_caller_does_not_accept_is_never_shown_as_sent(gallery):
    from playwright.sync_api import expect
    page, result = gallery, gallery.locator("#stop-result")
    page.locator("#stop-no-estop").check()  # 200 OK, but the body does not say estop === true
    page.locator("#gallery-stop").click()
    expect(result).to_contain_text("정지 요청 실패")
    assert "접수" not in result.inner_text()
    page.locator("#stop-no-estop").uncheck()
    page.locator("#gallery-stop").click()
    expect(result).to_contain_text("정지 요청 접수 · 실제 정지 확인 중")


def test_status_table_maps_eight_states_to_icon_and_tone(gallery):
    from playwright.sync_api import expect
    tags = gallery.locator("#status-tags ui-tag")
    expect(tags).to_have_count(8)
    got = {tag.get_attribute("data-state"): (tag.get_attribute("status"), tag.locator("svg.ui-icon").count()) for tag in tags.all()}
    assert got == {"fresh": ("neutral", 0), "progress": ("active", 0), "delayed": ("warn", 1), "disconnected": ("warn", 1),
                   "unknown": ("neutral", 1), "caution": ("warn", 1), "danger": ("crit", 1), "locked": ("neutral", 1)}, got
    for tag in tags.all():
        assert tag.inner_text().strip(), "the text always stays beside the icon"
    expect(gallery.locator("#status-tags ui-tag[data-state=unknown]")).to_have_text("정보 없음")
    border = lambda state: gallery.locator(f"#status-tags ui-tag[data-state={state}]").evaluate("el => getComputedStyle(el).borderStyle")
    assert border("unknown") == "dashed" and border("fresh") == "solid"
    fill = lambda state: gallery.locator(f"#status-tags ui-tag[data-state={state}]").evaluate("el => getComputedStyle(el).backgroundColor")
    assert fill("danger") != "rgba(0, 0, 0, 0)" and fill("fresh") == "rgba(0, 0, 0, 0)" and fill("disconnected") == "rgba(0, 0, 0, 0)"


def test_ui_panel_surfaces_and_density_follow_the_width(gallery):
    from playwright.sync_api import expect
    page = gallery
    panels = page.locator("#panel-stand .ui-panel")
    expect(panels).to_have_count(4)
    style = lambda sel, prop: page.locator(sel).evaluate(f"el => getComputedStyle(el).{prop}")
    assert style("[aria-labelledby=pn-1]", "backgroundColor") != style("[aria-labelledby=pn-2]", "backgroundColor")
    value = "#panel-stand [data-surface=flat][data-density=standard] > [data-slot=value]"
    assert "tabular-nums" in style(value, "fontVariantNumeric")
    pad = lambda density: float(style(f"#panel-stand [data-surface=flat][data-density={density}]", "paddingTop").removesuffix("px"))
    assert pad("compact") < pad("standard")  # 1366 px wide mouse surface
    page.set_viewport_size({"width": 600, "height": 800})
    assert pad("compact") == pad("standard"), "below 64rem compact falls back to standard (D-976)"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for state in ("pending", "empty", "error"):
        expect(page.locator(f"#panel-state-{state}")).to_be_visible()
    assert page.locator("#strip-example > div").count() == 4


def test_icon_sheet_lists_every_glyph_and_tooltip_rules_hold(gallery):
    from playwright.sync_api import expect
    page = gallery
    names = page.evaluate("import('/common/ui.js').then(m => m.actionIconNames())")
    assert len(names) >= 93 and "arm" in names and "cpu" in names
    expect(page.locator("#icon-sheet li")).to_have_count(len(names))
    # Hover shows the accessible name; the pointer may rest on the tooltip (WCAG 1.4.13); Escape dismisses.
    page.hover("#tip-icon-only")
    expect(page.locator(".ui-tooltip")).to_have_text("주소 복사")
    box = page.locator(".ui-tooltip").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.locator(".ui-tooltip")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(".ui-tooltip")).to_be_hidden()
    # Keyboard focus shows it as well.
    page.mouse.move(0, 0)
    page.focus("#tip-icon-label")
    page.focus("#tip-icon-only")
    expect(page.locator(".ui-tooltip")).to_have_text("주소 복사")


def test_toggletip_opens_on_click_and_closes_on_escape_or_outside_click(gallery):
    from playwright.sync_api import expect
    page = gallery
    note = page.locator("#toggletip-mount .ui-toggletip-note")
    expect(note).to_have_attribute("role", "status")
    expect(note).to_be_hidden()
    page.click("#toggletip-button")
    expect(note).to_contain_text("Fleet 직접 조회")
    page.keyboard.press("Escape")
    expect(note).to_be_hidden()
    page.click("#toggletip-button")
    page.mouse.click(5, 5)
    expect(note).to_be_hidden()


def test_robot_rows_show_arms_and_mobile_robots_in_one_quiet_row_form(gallery):
    from playwright.sync_api import expect
    page = gallery
    expect(page.locator("#robot-roster-mount .robot-group-title")).to_have_text(["로봇암 (3)", "이동로봇 (6)"])
    rows = page.locator("#robot-roster-mount .robot-row")
    expect(rows).to_have_count(9)
    # one form: every row, arm or mobile, has the same seven columns in the same order
    cols = [[c.get_attribute("data-col") for c in row.locator(":scope > .robot-cell").all()] for row in rows.all()]
    assert all(c == ["name", "link", "power", "task", "place", "alarm", "actions"] for c in cols), cols
    row = lambda robot_id: page.locator(f'#robot-roster-mount [data-robot-id="{robot_id}"]')
    # normal is quiet: a fresh link and no alarm draw no tag
    assert row("arm_a").locator("ui-tag").count() == 0 and row("rosy_40").locator("ui-tag").count() == 0
    # freshness and severity are different columns and different tags
    expect(row("arm_s").locator('[data-col=link] ui-tag')).to_have_attribute("data-state", "delayed")
    expect(row("rosy_43").locator('[data-col=link] ui-tag')).to_have_attribute("data-state", "disconnected")
    expect(row("rosy_44").locator('[data-col=power] .robot-value')).to_have_text("정보 없음")
    expect(row("rosy_44").locator('[data-col=link] ui-tag')).to_have_attribute("data-state", "unknown")
    page.set_viewport_size({"width": 1440, "height": 900})
    heights = {row(i).evaluate("el => Math.round(el.getBoundingClientRect().height)") for i in ("arm_a", "arm_b", "rosy_40", "rosy_41")}
    assert len(heights) == 1, f"rows with and without 자세히 differ in height at 1440: {heights}"
    expect(row("rosy_41").locator('[data-col=alarm] ui-tag')).to_have_attribute("data-state", "caution")
    expect(row("rosy_45").locator('[data-col=alarm] ui-tag')).to_have_attribute("data-state", "danger")
    expect(row("arm_b").locator('[data-col=power] .robot-value')).to_contain_text("토크 꺼짐")
    # the selection toggle keeps the pinned markup and the toggletip carries the secondary text
    expect(row("rosy_40").locator("ui-button[data-select-robot-id=rosy_40]")).to_have_attribute("aria-pressed", "true")
    expect(row("arm_a").locator(".ui-toggletip ui-button")).to_contain_text("자세히")
    row("arm_a").locator(".ui-toggletip ui-button").click()
    expect(row("arm_a").locator(".ui-toggletip-note")).to_contain_text("서보 12.0 V")
    # a repeated target is a row: no box around it, only the line between rows
    assert row("arm_a").evaluate("el => getComputedStyle(el).borderLeftWidth") == "0px"
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        if output := os.environ.get("ROSY_SHOT_DIR"):
            Path(output).mkdir(parents=True, exist_ok=True)
            page.locator("#robot-rows").screenshot(path=str(Path(output) / f"robot-rows-{width}.png"))
    labels = page.locator("#robot-roster-mount .robot-row-head").first
    assert labels.evaluate("el => getComputedStyle(el).display") == "none"  # 390: the cell labels show instead
    assert row("arm_a").locator("[data-col=power] .robot-cell-label").is_visible()
    assert not row("arm_a").locator("[data-col=link]").is_visible(), "a calm row shows no bare 연결 label at 390"
    assert row("arm_s").locator("[data-col=link]").is_visible()
