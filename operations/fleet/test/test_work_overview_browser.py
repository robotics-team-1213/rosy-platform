"""Real Chromium mixed-work view over fixture APIs; never dispatches to devices."""

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, _shot, site  # noqa: F401

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
            # D-741 7: 끝난 작업·승인 대기는 같은 조회 결과를 상태로 거른다. 두 건 모두 진행 중이라 빈 목록이다.
            page.goto(site + "/console?view=work&show=done")
            page.clock.run_for(2000)
            page.wait_for_function("() => document.getElementById('work-state').textContent.includes('0건')")
            assert page.locator("#work-list ui-button").count() == 0 and page.locator("#work-empty").is_visible()
            assert page.get_by_role("navigation", name="작업 화면", exact=True).locator(
                'a[aria-current="page"]').all_inner_texts() == ["끝난 작업"]
            page.goto(site + "/console?view=work")
            page.clock.run_for(2000)
            page.wait_for_function("() => document.querySelectorAll('#work-list ui-button').length === 2")
            assert page.locator("#work-overview").is_visible()
            assert not page.locator('[aria-labelledby="map-heading"]').is_visible()
            assert page.locator('.doc-tabs a[href="/console?view=work"]').get_attribute("aria-current") == "page"
            assert page.locator('.doc-tabs a[aria-current="page"]').count() == 1
            screens = page.get_by_role("navigation", name="작업 화면", exact=True)
            assert screens.locator("a").all_inner_texts() == ["전체 작업", "승인 대기", "끝난 작업", "새 작업"]
            assert screens.locator('a[aria-current="page"]').all_inner_texts() == ["전체 작업"]
            assert screens.get_by_role("link", name="새 작업", exact=True).get_attribute("href") == "/console/cell"
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
