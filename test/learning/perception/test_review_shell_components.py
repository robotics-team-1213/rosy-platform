"""All Learning review pages compile their own static header and global rail."""
from pathlib import Path
import runpy
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[3]
OWNER = ROOT / 'learning/curation/perception'
WEB = OWNER / 'review_app_web'


def api():
    return runpy.run_path(str(OWNER / 'review_shell.py'))


def test_every_review_document_matches_its_canonical_shell():
    shell = api()
    assert set(shell['PAGES']) == {path.name for path in WEB.glob('*.html')}
    assert shell['check'](WEB) == []


def test_header_changes_reach_every_page_and_preserve_local_workspaces(tmp_path):
    shell = api()
    shutil.copytree(WEB, tmp_path / 'web')
    root = tmp_path / 'web'
    header = root / 'components/header.html.inc'
    header.write_text(header.read_text(encoding='utf-8').replace('테마 변경', '테마 변경 fixture'), encoding='utf-8')
    assert set(shell['check'](root)) == set(shell['PAGES'])
    for name in shell['PAGES']:
        rendered = shell['render'](root, name)
        assert '테마 변경 fixture' in rendered
        assert rendered.count('class="ui-rail-item"') == 5
    assert 'id="task-participants"' in shell['render'](root, 'tasks.html')
    assert 'aria-current="page" title="로그인·계정"' in shell['render'](root, 'accounts.html')


@pytest.mark.parametrize('component', ['header', 'rail'])
def test_shell_drift_or_missing_slots_is_rejected(tmp_path, component):
    shell = api()
    shutil.copytree(WEB, tmp_path / 'web')
    root = tmp_path / 'web'
    path = root / 'tasks.html'
    text = path.read_text(encoding='utf-8')
    path.write_text(text.replace(f'<!-- review:{component}:start -->', ''), encoding='utf-8')
    with pytest.raises(ValueError, match='slot'):
        shell['render'](root, 'tasks.html')
