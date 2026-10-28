"""Canonical Fleet chrome compiles to complete first-response static documents."""
import runpy
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / 'applications/fleet/web'


def component_api():
    return runpy.run_path(str(WEB / 'shared/fleet_components.py'))


def test_four_static_documents_match_canonical_components():
    assert component_api()['check'](WEB) == []


def test_component_change_propagates_without_changing_page_task_content(tmp_path):
    api = component_api()
    shutil.copytree(WEB, tmp_path/'web')
    root = tmp_path/'web'
    source = root/'shared/fleet-header.html'
    source.write_text(source.read_text(encoding='utf-8').replace('계정과 접속 상세', '계정 상세 fixture'), encoding='utf-8')
    assert set(api['check'](root)) == set(api['PAGES'])
    for name in api['PAGES']:
        rendered = api['render'](root, name)
        assert '계정 상세 fixture' in rendered
        assert rendered.count('id="estop"') == 1
        assert 'data-always-live' in rendered
        assert rendered.count('aria-current="page"') >= 1
        assert '<!-- fleet:header:start -->' in rendered


@pytest.mark.parametrize('marker', ['header', 'nav'])
def test_missing_or_duplicate_component_slot_is_rejected(tmp_path, marker):
    api = component_api()
    shutil.copytree(WEB, tmp_path/'web')
    root = tmp_path/'web'
    page = root/'index.html'
    text = page.read_text(encoding='utf-8')
    page.write_text(text.replace(f'<!-- fleet:{marker}:start -->', ''), encoding='utf-8')
    with pytest.raises(ValueError, match='slot'):
        api['render'](root, 'index.html')
    page.write_text(text+f'<!-- fleet:{marker}:start -->', encoding='utf-8')
    with pytest.raises(ValueError, match='slot'):
        api['render'](root, 'index.html')


def test_layout_values_have_one_role_owner_and_no_per_page_duplicates():
    tokens = (ROOT/'shared/web/tokens.css').read_text(encoding='utf-8')
    common = (WEB/'shared/doc-tabs.css').read_text(encoding='utf-8')
    for name in ['content-task-max', 'inset-task-page', 'gap-task-page', 'gap-task-actions', 'size-rail-item']:
        assert f'--{name}:' in tokens
        assert f'var(--{name})' in common
    for name in ['cell/cell.css', 'sitemap/site-map.css']:
        source = (WEB/name).read_text(encoding='utf-8')
        assert 'max-width: 90rem' not in source
        assert '\n.actions { display: flex;' not in source
        assert '#estop-feedback' not in source
