"""D-874: 「승격 요청」 opens only for a human-truth candidate and shows the sealed hash for Fleet."""
from urllib.parse import urlsplit

import pytest

from browser_harness import browser_tests_enabled
from learning_workspace import Workspace
from test_promotion_request import candidate
from test_review_app import open_store
from test_review_flow_browser import serve

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('width', [1440, 390])
def test_request_button_follows_server_qualification(tmp_path, width):
    store = open_store(tmp_path)
    links = Workspace(store.db)
    links.register({'kind': 'perception', 'name': '자동 평가', 'path': str(candidate(tmp_path, 'auto', sources=['lidar']))})
    with serve(store) as (page, _, expect):
        url = '{0.scheme}://{0.netloc}/learning/evaluate'.format(urlsplit(page.url))
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(url, wait_until='networkidle')
        expect(page.locator('#promote-request')).to_be_disabled()
        expect(page.locator('#promote-status')).to_contain_text('확정 정답 평가를 통과한 후보가 없습니다')
        expect(page.locator('#promote-candidates li')).to_contain_text('자동 라벨(LiDAR·궤적)')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        links.register({'kind': 'perception', 'name': '사람 평가', 'path': str(candidate(tmp_path))})
        page.goto(url, wait_until='networkidle')
        expect(page.locator('#promote-request')).to_be_enabled()
        expect(page.locator('#promote-candidate option')).to_have_count(1)
        page.locator('#promote-request').click()
        expect(page.locator('#promote-result')).to_contain_text('Fleet에서 승인권자가 이 해시로 제안을 만든다(D-793)')
        sha = page.locator('#promote-result').inner_text().split()[2]
        assert len(sha) == 64 and (store.state / 'promotion-requests' / f'{sha}.json').is_file()
        expect(page.locator('#promote-requests li')).to_contain_text(sha)
        assert page.locator('#promote-request').bounding_box()['height'] >= 44
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
