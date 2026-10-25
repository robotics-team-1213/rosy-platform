"""Real Chromium mixed-work view over fixture APIs; never dispatches to devices."""

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, ON_TOP, _open, _shot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")


@pytest.mark.parametrize("size", [(1366, 768), (320, 568)])
def test_discord_current_incident_requires_separate_named_confirmation(site, size):
    from playwright.sync_api import expect, sync_playwright
    request_id, digest, revision = 'a' * 24, 'b' * 64, 'c' * 64
    path = f'/api/fleet/channel-requests/{request_id}'
    receipt = {'request_id': request_id, 'content_hash': digest, 'content': 'inspect current risk',
               'received_at': '2026-10-12T00:00:00+00:00'}
    view = {'request_id': request_id, 'content_hash': digest, 'revision': 0, 'state': 'REQUESTED',
            'candidate': None, 'reason': None, 'work_id': None, 'work_kind': None, 'work_status': None,
            'request_key': 'discord-' + request_id, 'incident': None}
    report = {'id': 'line_stuck:rosy_03:stuck-abc', 'classification': 'line_stuck',
        'robot_ids': ['rosy_03'], 'stuck_id': 'stuck-abc', 'judgment_revision': revision, 'handoff': None,
        'opened_at': receipt['received_at'], 'closed_at': None, 'actions': [], 'reviews': [],
        'evidence': {'core': {}, 'fleet': {}, 'rosy_cam': None, 'ai_facts': [],
                     'front_image': {'status': 'not_retained'}}}
    api = {**API, path + '/review': view, '/api/fleet/channel-requests': {'rows': [receipt]},
           '/api/fleet/incidents': {'reports': [report], 'traffic_reports': []},
           '/api/fleet/work': {'rows': [], 'observed_at': receipt['received_at'],
               'tasks_available': True, 'missions_available': True, 'truncated_sources': []}}
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            page.goto(site + '/console?view=work')
            page.clock.run_for(2000)
            page.locator('#channel-requests ui-button').click()
            page.locator('#channel-review-incident').select_option('rosy_03/stuck-abc')
            page.locator('#channel-review-reason').fill('current risk review')
            claim = page.locator('#channel-review-incident-claim')
            claim.click()
            page.locator('dialog.ui-confirm ui-button[kind="quiet"]').click()
            assert not posts

            claim.click()
            api['/api/fleet/session'] = {'principal_id': 'alice', 'role': 'operator'}
            page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true})); dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
            expect(page.locator('dialog.ui-confirm')).to_have_count(0)
            expect(page.locator('#channel-review')).to_be_hidden()
            assert not posts
            api['/api/fleet/session'] = {'principal_id': 'bob', 'role': 'operator'}
            page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true})); dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
            page.clock.run_for(2000)
            page.locator('#channel-requests ui-button').click()
            page.locator('#channel-review-incident').select_option('rosy_03/stuck-abc')
            page.locator('#channel-review-reason').fill('current risk review')

            def accept(route):
                body = route.request.post_data_json
                assert body == {'expected_hash': digest, 'expected_revision': 0, 'robot_id': 'rosy_03',
                    'stuck_id': 'stuck-abc', 'judgment_revision': revision, 'reason': 'current risk review'}
                posts.append((path + '/incident', body))
                view.update(state='LINKED', revision=1, work_kind='incident', work_id=request_id,
                    work_status='CLAIMED', incident={key: body[key] for key in ('robot_id', 'stuck_id', 'judgment_revision')})
                route.fulfill(json=view)
            page.route('**' + path + '/incident', accept)
            claim.click()
            page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
            expect(page.locator('#channel-review-state')).to_contain_text('사건 인수')
            expect(claim).to_be_disabled()
            expect(claim).to_have_attribute('reason', '이미 작업과 연결된 요청입니다')
            expect(claim).to_have_attribute('aria-describedby', 'channel-review-state')
            expect(page.locator('#channel-review-incident-link')).to_have_attribute('href',
                '/console?inbox=1&robot=rosy_03&incident=stuck-abc')
            assert len(posts) == 1 and not errors
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()


@pytest.mark.parametrize("size", [(1366, 768), (320, 568)])
def test_discord_mission_uses_owned_candidate_and_separate_admission(site, size):
    from playwright.sync_api import expect, sync_playwright
    request_id, digest = 'a' * 24, 'b' * 64
    path = f'/api/fleet/channel-requests/{request_id}'
    receipt = {'request_id': request_id, 'content_hash': digest, 'content': 'prepare arm work',
               'received_at': '2026-10-12T00:00:00+00:00'}
    view = {'request_id': request_id, 'content_hash': digest, 'revision': 0, 'state': 'REQUESTED',
            'candidate': None, 'reason': None, 'work_id': None, 'work_kind': None, 'work_status': None,
            'request_key': 'discord-' + request_id}
    api = {**API, path + '/review': view, '/api/fleet/channel-requests': {'rows': [receipt]},
           '/api/fleet/work': {'rows': [{'source': 'mission', 'source_id': 'owned-source', 'status': 'PROPOSED',
               'action_kind': 'PICK_PLACE', 'device_id': 'omx', 'workcell_id': 'cell', 'reason': None,
               'updated_at': receipt['received_at']}], 'observed_at': receipt['received_at'],
               'tasks_available': True, 'missions_available': True, 'truncated_sources': []},
           '/api/fleet/proposals/owned-source': {'proposal': {'proposal_id': 'owned-source'},
               'mission': {'workcell_id': 'cell', 'instance_id': 'omx'}},
           '/api/fleet/dispatch-control': {'dispatch_enabled': True, 'generation': 7}}
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            page.goto(site + '/console?view=work')
            page.clock.run_for(2000)
            page.locator('#channel-requests ui-button').click()
            expect(page.locator('#channel-review-cell')).to_have_attribute('href', '/console/cell?channel_request=' + request_id)
            page.locator('#channel-review-mission').select_option('owned-source')
            page.locator('#channel-review-reason').fill('verified current source candidate')

            def prepare(route):
                body = route.request.post_data_json
                assert body == {'kind': 'mission', 'source_proposal_id': 'owned-source', 'workcell_id': 'cell',
                    'instance_id': 'omx', 'reason': 'verified current source candidate',
                    'expected_hash': digest, 'expected_revision': 0}
                posts.append(('prepare', body))
                view.update(state='LINKED', work_kind='mission', work_id='mission-new', work_status='PROPOSED', revision=1)
                route.fulfill(json=view)
            page.route('**' + path + '/prepare', prepare)
            page.locator('#channel-review-mission-prepare').click()
            expect(page.locator('#channel-review-state')).to_contain_text('승인 전')
            assert len(posts) == 1
            button = page.locator('#channel-review-mission-admit')
            button.click()
            page.locator('dialog.ui-confirm ui-button[kind="quiet"]').click()
            assert len(posts) == 1

            def admit(route):
                body = route.request.post_data_json
                assert body == {'expected_hash': digest, 'expected_revision': 1, 'expected_generation': 7}
                posts.append(('admit', body))
                view.update(work_status='READY')
                route.fulfill(json=view)
            page.route('**' + path + '/admit', admit)
            button.click()
            page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
            expect(page.locator('#channel-review-state')).to_contain_text('실행 준비')
            expect(button).not_to_be_visible()
            assert len(posts) == 2 and not errors
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()


@pytest.mark.parametrize("size", [(1366, 768), (320, 568)])
def test_channel_review_keeps_candidate_separate_from_execution(site, size):
    from playwright.sync_api import expect, sync_playwright

    request_id, digest = "a" * 24, "b" * 64
    path = f"/api/fleet/channel-requests/{request_id}/review"
    receipt = {"content": "<script>unsafe()</script> 이동 요청", "request_id": request_id,
               "content_hash": digest, "received_at": "2026-10-12T00:00:00+00:00"}
    review = {"request_id": request_id, "content_hash": digest, "revision": 0, "state": "REQUESTED",
              "candidate": None, "reason": None, "work_id": None, "work_kind": None, "work_status": None,
              "request_key": "discord-" + request_id}
    api = {**API, "/api/fleet/work": {"rows": [], "observed_at": receipt["received_at"],
           "tasks_available": True, "missions_available": True, "truncated_sources": []},
           "/api/fleet/channel-requests": {"rows": [receipt]}, path: review}
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            page.goto(site + "/console?view=work")
            page.clock.run_for(2000)
            page.locator("#channel-requests ui-button").click()
            expect(page.locator("#channel-review")).to_be_visible()
            page.locator("#channel-review-reason").fill("목표 위치 확인 필요")

            def save(route):
                body = route.request.post_data_json
                posts.append((path, body))
                assert body["expected_hash"] == digest and body["expected_revision"] == review["revision"]
                review.update(state=body["state"], reason=body["reason"], candidate=body["candidate"],
                              revision=review["revision"] + 1)
                route.fulfill(json=review)

            page.route("**" + path, lambda route: save(route) if route.request.method == "PUT"
                       else route.fulfill(json=review))
            page.locator("#channel-review-hold").click()
            expect(page.locator("#channel-review-state")).to_contain_text("보류")
            assert review["candidate"] is None and posts[-1][1]["state"] == "HOLD"
            page.locator("#channel-review-robot").select_option("rosy_03")
            page.locator("#channel-review-x").fill("1.25")
            page.locator("#channel-review-y").fill("2.5")
            page.locator("#channel-review-ready").click()
            expect(page.locator("#channel-review-state")).to_contain_text("이동 후보 준비")
            page.locator("#channel-review-reason").fill("unsaved operator note")
            page.locator("#work-refresh").click()
            expect(page.locator("#channel-review-reason")).to_have_value("unsaved operator note")
            assert review["candidate"] == {"robot_id": "rosy_03", "x": 1.25, "y": 2.5, "yaw": 0}
            assert all(item[0] == path for item in posts)
            submit = page.locator("#channel-review-submit")
            submit.click()
            page.locator('dialog.ui-confirm ui-button[kind="quiet"]').click()
            assert all(item[0] == path for item in posts)

            def submit_request(route):
                body = route.request.post_data_json
                assert body == {"expected_hash": digest, "expected_revision": 2}
                posts.append(("submit", body))
                review.update(state="LINKED", work_id="task-one", work_kind="task", work_status="QUEUED", revision=3)
                route.fulfill(json=review)

            page.route(f"**/api/fleet/channel-requests/{request_id}/submit", submit_request)
            submit.click()
            page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
            expect(page.locator("#channel-review-state")).to_contain_text("작업 연결")
            assert [item[0] for item in posts] == [path, path, "submit"]
            expect(submit).not_to_be_visible()
            review.update(work_status="COMPLETED")
            page.locator("#work-refresh").click()
            expect(page.locator("#channel-review-state")).to_contain_text("주행 완료")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            _shot(page, f"channel-review-{size[0]}.png", full_page=True)
            page.route("**/api/fleet/channel-requests", lambda route: route.fulfill(status=403, json={"detail": "revoked"}))
            page.locator("#work-refresh").click()
            expect(page.locator("#channel-review")).not_to_be_visible()
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize("size", [(1366, 768), (320, 568)])
@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_mixed_work_selection_filter_refresh_failure_and_accessibility(site, size, role):
    from playwright.sync_api import sync_playwright

    rows = [{"source": source, "source_id": "same", "action_kind": kind,
             "status": state, "device_id": device, "workcell_id": cell, "reason": None,
             "updated_at": "2026-10-11T12:00:00+00:00"}
            for source, kind, state, device, cell in (
                ("task", "navigate", "RUNNING", "rosy_01", None),
                ("mission", "PICK_PLACE", "ACTION_SUCCEEDED", "omx_control", "packing"))]
    api = {**API, "/api/fleet/session": {"principal_id": "bob", "role": role},
           "/api/fleet/work": {"rows": rows, "observed_at": "2026-10-11T12:00:01+00:00",
                               "tasks_available": True, "missions_available": True, "truncated_sources": []},
           "/api/fleet/tasks/same": {"task": {**rows[0], "source": "console", "task_id": "same"}, "history": []},
           "/api/fleet/missions/same": {"mission": rows[1], "history": []}}
    if role == "operator":
        api["/api/fleet/channel-requests"] = {"rows": [{"content": "<script>window.intakeXss=true</script>" + "x" * 1000,
            "received_at": "2026-10-12T00:00:00+00:00", "request_id": "request-1"}]}
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            # D-741 7: 끝난 작업·승인 대기는 같은 조회 결과를 상태로 거른다. 걸러진 줄은 있고 나머지는 없어야 한다.
            extra = [{**rows[0], "source_id": "done-1", "status": "COMPLETED", "device_id": "rosy_09", "visible_state": "ended"},
                     {**rows[1], "source_id": "wait-1", "visible_state": "approval_pending", "status": "PROPOSED", "device_id": "omx_wait",
                      "visible_state": "approval_pending"}]
            api["/api/fleet/work"] = {**api["/api/fleet/work"], "rows": rows + extra, "truncated_sources": ["task"]}
            for show, label, device in (("done", "끝난 작업", "rosy_09"), ("pending", "승인 대기", "omx_wait"), ("nonsense", "전체 작업", None)):
                page.goto(site + "/console?view=work&show=" + show)
                page.clock.run_for(2000)
                page.wait_for_function("count => document.querySelectorAll('#work-list ui-button').length === count", arg=1 if device else 4)
                if device:
                    assert device in page.locator("#work-list ui-button").inner_text()
                    assert "최근 4건 중 1건" in page.locator("#work-state").inner_text()
                else:
                    assert "건 중" not in page.locator("#work-state").inner_text()
                assert page.get_by_role("navigation", name="작업 화면", exact=True).locator(
                    'a[aria-current="page"]').all_inner_texts() == [label]
            api["/api/fleet/work"] = {**api["/api/fleet/work"], "rows": rows, "truncated_sources": []}
            page.goto(site + "/console?view=work")
            page.clock.run_for(2000)
            page.wait_for_function("() => document.querySelectorAll('#work-list ui-button').length === 2")
            assert page.locator("#work-overview").is_visible()
            assert not page.locator('[aria-labelledby="map-heading"]').is_visible()
            assert page.locator('.doc-tabs a[href="/console?view=work"]').get_attribute("aria-current") == "page"
            assert page.locator('.doc-tabs a[aria-current="page"]').count() == 1
            screens = page.get_by_role("navigation", name="작업 화면", exact=True)
            assert screens.locator("a").all_inner_texts() == ["전체 작업", "승인 대기", "끝난 작업", "새 작업", "학습"]
            assert screens.locator('a[aria-current="page"]').all_inner_texts() == ["전체 작업"]
            assert screens.get_by_role("link", name="새 작업", exact=True).get_attribute("href") == "/console?view=work&show=new"
            assert screens.get_by_role("link", name="학습", exact=True).get_attribute("href") == "/console/learning"
            seat, work = page.locator('.ui-subnav[data-area="work"]').bounding_box(), page.locator("#work-overview").bounding_box()
            if size[0] >= 1024:
                assert seat["width"] == 232 and seat["x"] + seat["width"] <= work["x"], (seat, work)
            else:
                assert seat["y"] + seat["height"] <= work["y"], (seat, work)
            assert page.evaluate("() => document.querySelector('.console-context').compareDocumentPosition(document.querySelector('.queues-panel')) & Node.DOCUMENT_POSITION_FOLLOWING")
            if size[0] < 1024:
                assert page.locator("#work-overview").bounding_box()["y"] < page.locator(".console-context").bounding_box()["y"] < page.locator(".queues-panel").bounding_box()["y"]
            page.locator("#work-list ui-button").filter(has_text="팔 작업").click()
            assert page.locator("#work-detail").inner_text().find("packing") >= 0
            assert page.locator("#work-detail").inner_text().find("목표 확인 대기") >= 0
            page.locator("#work-filter").select_option("task")
            assert page.locator("#work-list ui-button").count() == 1
            page.locator("#work-list ui-button").click()
            assert "CORE" in page.locator("#work-detail").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if role == "operator":
                assert page.locator("#channel-requests").inner_text().find("<script>") >= 0
                assert page.evaluate("window.intakeXss === undefined")
                page.route("**/api/fleet/channel-requests", lambda route: route.fulfill(status=403, json={"detail": "revoked"}))
                page.locator("#work-refresh").click()
                page.wait_for_function("() => document.getElementById('channel-requests').childElementCount === 0")
                assert "기명 운영자" in page.locator("#channel-requests-state").inner_text()
            page.locator("#work-filter").select_option("all")
            _shot(page, f"mixed-work-{role}-{size[0]}.png", full_page=True)
            page.route("**/api/fleet/work", lambda route: route.fulfill(status=503, json={"detail": "offline"}))
            page.locator("#work-refresh").click()
            page.wait_for_function("() => document.getElementById('work-list').childElementCount === 0")
            assert "조회 실패" in page.locator("#work-state").inner_text()
            assert not posts and not errors
        finally:
            browser.close()


@pytest.mark.parametrize("size", [(1366, 768), (390, 844)])
def test_trip_and_cell_job_rows_read_their_visible_state_and_filters(site, size):
    """D-763 4 (v1.237): trip and Cell Job rows stand beside Task/Mission with the server's visible state; a wait
    reads as 대기 and past its bound as a warning, not 개입. 승인 대기·끝난 작업 filter the same answer. Placeholder
    identities only (rev 2 Q6)."""
    from playwright.sync_api import sync_playwright

    def row(source, source_id, kind, status, device, visible, **extra):
        return {"source": source, "source_id": source_id, "action_kind": kind, "status": status, "device_id": device,
                "workcell_id": extra.pop("workcell_id", None), "reason": extra.pop("reason", None),
                "updated_at": "2026-10-15T00:00:00+00:00", "visible_state": visible, "approval": None,
                "wait": None, **extra}
    wait = {"reason": "signal", "waiting": True, "bound_s": 20.0, "over_bound": False}
    rows = [row("trip", "t-wait", "trip", "running", "rosy_01", "waiting", wait=wait),
            row("trip", "t-over", "trip", "running", "rosy_02", "in_progress",
                wait={**wait, "waiting": False, "over_bound": True}),
            row("trip", "t-done", "trip", "arrived", "rosy_03", "ended"),
            row("cell_job", "job-1", "CELL_TRANSFER", "PROPOSED", "omx_control", "approval_pending",
                workcell_id="packing", approval="two_person"),
            row("task", "task-1", "navigate", "FAILED", "rosy_04", "intervention")]
    work = {"rows": rows, "observed_at": "2026-10-15T00:00:01+00:00", "tasks_available": True,
            "missions_available": True, "cell_jobs_available": True, "truncated_sources": [], "kinds": ["trip"]}
    api = {**API, "/api/fleet/session": {"principal_id": "operator-1", "role": "operator"}, "/api/fleet/work": work,
           "/api/fleet/trips/t-done": {**rows[2], "trip_id": "t-done", "state": "arrived"},
           "/api/fleet/cell-jobs/job-1": {"proposal_id": "job-1", "proposal_state": "RESOLVED",
                                          "job": {"status": "PROPOSED", "workcell_id": "packing"}}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [], size=size)
        try:
            for show, expected in (("pending", ["Cell 적재 · omx_control · 승인 대기"]),
                                   ("done", ["운행 · rosy_03 · 끝남"])):  # 개입 필요 is not 끝남 (D-763 8)
                page.goto(site + "/console?view=work&show=" + show)
                page.clock.run_for(2000)
                page.wait_for_function("count => document.querySelectorAll('#work-list ui-button').length === count",
                                       arg=len(expected))
                assert page.locator("#work-list ui-button").all_inner_texts() == expected, show
            page.goto(site + "/console?view=work")
            page.clock.run_for(2000)
            page.wait_for_function("() => document.querySelectorAll('#work-list ui-button').length === 5")
            texts = page.locator("#work-list ui-button").all_inner_texts()
            assert texts[:2] == ["운행 · rosy_01 · 대기 · 신호", "운행 · rosy_02 · 대기 상한 넘음 · 신호"], texts
            assert "개입" not in texts[1]  # past its bound: a warning (rev 2 Q7)
            assert "Cell 작업 원장" in page.locator("#work-sources").inner_text()
            page.locator("#work-filter").select_option("trip")
            assert page.locator("#work-list ui-button").count() == 3
            page.locator("#work-list ui-button").filter(has_text="rosy_03").click()
            page.wait_for_function("() => document.getElementById('work-evidence').textContent.includes('도착')")
            assert "CORE" in page.locator("#work-detail").inner_text()
            # The chosen row is drawn as chosen, with the toggle's existing pressed fill.
            fills = page.locator("#work-list ui-button").evaluate_all(
                "nodes => nodes.map(node => [node.getAttribute('aria-pressed'), getComputedStyle(node).backgroundColor])")
            chosen = {fill for pressed, fill in fills if pressed == "true"}
            assert len(chosen) == 1 and chosen.isdisjoint(fill for pressed, fill in fills if pressed != "true"), fills
            page.locator("#work-filter").select_option("cell_job")
            page.locator("#work-list ui-button").click()
            page.wait_for_function("() => document.getElementById('work-detail').textContent.includes('Cell 적재')")
            assert "packing" in page.locator("#work-detail").inner_text()
            terms = page.locator("#work-detail dt").all_inner_texts()  # D-763 7: the rule is shown, read-only
            assert page.locator("#work-detail dd").nth(terms.index("승인 조건")).inner_text().startswith("두 사람"), terms
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.evaluate("window.scrollTo(0, 0); document.querySelector('.console-secondary')?.scrollTo(0, 0)")
            stop = page.locator("#estop").bounding_box()
            assert stop and 0 <= stop["y"] and stop["y"] + stop["height"] <= size[1]
            _shot(page, f"work-sources-{size[0]}.png", full_page=True)
            assert not errors
        finally:
            browser.close()


NAMED = "이름 있는 운영자 로그인이 필요합니다"


def test_late_approval_failure_does_not_disable_a_new_selection(site):
    from playwright.sync_api import expect, sync_playwright
    rows = [{"source": "mission", "source_id": key, "visible_state": "approval_pending",
             "action_kind": "PICK_PLACE", "status": "PROPOSED", "device_id": key,
             "workcell_id": "packing", "reason": None, "updated_at": "2026-10-15T00:00:00+00:00"}
            for key in ("first", "second")]
    work = {"rows": rows, "observed_at": rows[0]["updated_at"], "tasks_available": True,
            "missions_available": True, "truncated_sources": []}
    api = {**API, "/api/fleet/session": {"principal_id": "bob", "role": "operator"},
           "/api/fleet/work": work, "/api/fleet/dispatch-control": {"dispatch_enabled": True, "generation": 7},
           **{f'/api/fleet/missions/{row["source_id"]}': {"mission": row, "history": []} for row in rows}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [], size=(1366, 768))
        pending = []
        try:
            page.route("**/api/fleet/missions/first/admit", lambda route: pending.append(route))
            page.goto(site + "/console?view=work&show=pending")
            page.clock.run_for(2000)
            page.locator("#work-list ui-button").filter(has_text="first").click()
            page.locator("#work-admit").click()
            for _ in range(50):
                page.wait_for_timeout(100)
                if pending:
                    break
            assert pending, "approval request was not issued"
            page.locator("#work-list ui-button").filter(has_text="second").click()
            pending[0].fulfill(status=409, json={"detail": {"code": "FIRST_ONLY"}})
            expect(page.locator("#work-admit")).to_be_enabled()
            expect(page.locator("#work-admit")).not_to_have_attribute("reason", "FIRST_ONLY")
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize("size", [(1366, 768), (390, 844)])
@pytest.mark.parametrize("case", ["approve", "viewer", "shared-token", "refused", "unknown"])
@pytest.mark.parametrize("source", ["mission", "cell_job"])
def test_pending_seat_approves_through_the_existing_admit_route(site, size, case, source):
    """D-741 7: 승인 대기에서 고른 팔 작업은 오른쪽 칸에서 기존 admit 경로로 승인한다. 막힌 단추는 이유를 적는다."""
    from playwright.sync_api import expect, sync_playwright

    width, height = size
    row = {"source": source, "source_id": "wait-1", "visible_state": "approval_pending", "action_kind": "PICK_PLACE", "status": "PROPOSED",
           "device_id": "omx_wait", "workcell_id": "packing", "reason": None, "updated_at": "2026-10-14T01:00:00+00:00"}
    work = {"rows": [row], "observed_at": "2026-10-14T01:00:01+00:00", "tasks_available": True,
            "missions_available": True, "truncated_sources": []}
    session = {"viewer": ("eve", "viewer"), "shared-token": ("site-console", "operator")}.get(case, ("bob", "operator"))
    api = {**API, "/api/fleet/session": {"principal_id": session[0], "role": session[1]}, "/api/fleet/work": work,
           "/api/fleet/missions/wait-1": {"mission": row, "history": []},
           "/api/fleet/cell-jobs/wait-1": {"job": row, "history": []},
           "/api/fleet/dispatch-control": {"dispatch_enabled": True, "generation": 7}}
    answer = {"approve": (200, {"mission": {**row, "status": "READY"}}),
              "refused": (403, {"detail": {"code": "CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER"}}),
              "unknown": (503, {"detail": "down"})}.get(case)
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            def admit(route):
                posts.append(("admit", route.request.post_data_json))
                if case == "approve":
                    work["rows"] = []
                route.fulfill(status=answer[0], json=answer[1])
            page.route("**/api/fleet/missions/wait-1/admit", admit)
            page.goto(site + "/console?view=work&show=pending")
            page.clock.run_for(2000)
            expect(page.locator("#work-admit")).to_be_hidden()  # nothing chosen, nothing to approve
            page.locator("#work-list ui-button").filter(has_text="omx_wait").click()
            button = page.locator("#work-admit")
            expect(button).to_be_visible()
            expect(button).to_contain_text("실행 승인")
            if case in ("viewer", "shared-token"):
                expect(button).to_be_disabled()
                reason = "운영자 권한이 필요합니다" if case == "viewer" else NAMED
                expect(button).to_have_attribute("reason", reason)
                described = button.get_attribute("aria-describedby")
                assert page.locator(f"#{described}").inner_text() == reason
                button.click(force=True)
                assert not posts
            else:
                expect(button).to_be_enabled()
                button.click()
                for _ in range(50):
                    page.clock.run_for(100)
                    if posts:
                        break
                assert posts == [("admit", {"expected_generation": 7})], posts
                if case == "approve":
                    page.clock.run_for(2000)  # a poll in flight skips the refresh; the next one shows it
                    page.wait_for_function("() => document.querySelectorAll('#work-list ui-button').length === 0")
                    expect(button).to_be_hidden()
                    assert "omx_wait" not in page.locator("#work-detail").inner_text()
                else:
                    text = ("승인이 거절됐습니다 · CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER" if case == "refused"
                            else "승인 결과 미확인 · 다시 보내지 않았습니다. 원장을 확인하세요.")
                    expect(button).to_have_attribute("reason", text)
                    expect(button).to_be_disabled()
                    described = button.get_attribute("aria-describedby")
                    assert page.locator(f"#{described}").inner_text() == text
                    assert page.locator("#work-list ui-button").count() == 1
            if case != "approve":
                button.scroll_into_view_if_needed()
                box = button.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= width, box
                assert button.evaluate("node => node.scrollWidth <= node.clientWidth + 1"), box
            stop = page.locator("#estop")
            page.evaluate("window.scrollTo(0, 0)")
            box = stop.bounding_box()
            assert box["y"] >= 0 and box["y"] + box["height"] <= height, box
            assert box["x"] >= 0 and box["x"] + box["width"] <= width and stop.evaluate(ON_TOP), box
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            _shot(page, f"work-approve-{case}-{width}.png", full_page=True)
            assert not errors
        finally:
            browser.close()
