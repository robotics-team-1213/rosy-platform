"""D-987: the common service catalog stays true to the manifest and the site stack."""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'docs/reference/common-services.md'


def _rows(heading):
    section = CATALOG.read_text(encoding='utf-8').split(f'## {heading}\n', 1)[1].split('\n## ', 1)[0]
    lines = [line for line in section.splitlines() if line.startswith('|')][2:]
    return [[cell.strip() for cell in line.strip('|').split('|')] for line in lines]


def _ticks(cell):
    return re.findall(r'`([^`]+)`', cell)


def _compose_services():
    return {name for path in (ROOT / 'deploy/site').glob('compose*.yaml')
            for name in yaml.safe_load(path.read_text(encoding='utf-8'))['services']}


def _sources():
    return [row[1].strip('`') for heading in ('실행 서비스', '공용 코드') for row in _rows(heading)]


def test_catalog_sources_exist_under_manifest_roots():
    manifest = yaml.safe_load((ROOT / 'tools/harness/platform_parts.yaml').read_text(encoding='utf-8'))
    roots = [root['path'] for root in manifest['roots']]
    for source in _sources():
        assert (ROOT / source).is_dir(), source
        assert any(source == root or source.startswith(root + '/') for root in roots), source


def test_every_site_service_is_classified_exactly_once():
    common = [name for row in _rows('실행 서비스') for name in _ticks(row[2])]
    other = [name for row in _rows('공통 서비스가 아닌 현장 서비스') for name in _ticks(row[0])]
    assert len(common + other) == len(set(common + other)), 'a service is listed twice'
    assert set(common + other) == _compose_services()


def test_catalog_links_and_decisions_resolve():
    text = CATALOG.read_text(encoding='utf-8')
    for target in re.findall(r'\]\(([^)#]+)\)', text):
        assert (CATALOG.parent / target).exists(), target
    for decision in set(re.findall(r'D-\d+', text)):
        assert list((ROOT / 'docs/adr').glob(f'{decision}-*.md')), decision


def _capabilities():
    source = (ROOT / 'contracts/foundation/core_common/protocol/account_access.py').read_text(encoding='utf-8')
    return {kind: set(re.findall(r"'([a-z]+\.[a-z]+)'", re.search(rf"'{kind}': frozenset\(\{{(.*?)\}}\)", source, re.S)[1]))
            for kind in ('site', 'robot', 'project')}


def test_android_capability_copy_equals_the_foundation_lists():
    # Kotlin cannot import the Python contract, so a new capability would otherwise reject tokens only on Android.
    source = (ROOT / 'shared/android/account/io/github/livsbittt/rosy/account/AccountSession.kt').read_text(encoding='utf-8')
    site, robot = re.search(r'val allowed = if .*?setOf\((.*?)\)\s+else setOf\((.*?)\)', source, re.S).groups()
    capabilities = _capabilities()
    assert set(re.findall(r'"([a-z.]+)"', site)) == capabilities['site']
    assert set(re.findall(r'"([a-z.]+)"', robot)) == capabilities['robot']


def test_fleet_role_bundles_name_only_real_capabilities():
    source = (ROOT / 'applications/fleet/web/shared/account-permissions.js').read_text(encoding='utf-8')
    named = set(re.findall(r"'((?:accounts|fleet|camera|games|vault|robot|learning)\.[a-z]+)'", source))
    assert named and named <= set().union(*_capabilities().values())


TARGET_MARK = '(목표, 미생성)'
D997_FUNCTIONS = {'계정·권한', '등록·앱 목록', '설정', '알림', '감사', '백업·복원', '업데이트'}


def test_d997_function_rows_pin_existing_sources():
    rows = {row[0]: row for row in _rows('기능별 공통화 결정')}
    assert set(rows) == D997_FUNCTIONS
    for name, row in rows.items():
        sources = row[2]
        paths = _ticks(sources)
        assert paths, f'{name} row names no source path'
        for path in paths:
            if f'`{path}`{TARGET_MARK}' in sources:
                assert not (ROOT / path).exists(), f'{path} is marked {TARGET_MARK} but exists'
            else:
                assert (ROOT / path).exists(), f'{name} row pins missing path {path}'


def test_notification_delivery_stays_pre_cutover():
    sources = next(row[2] for row in _rows('기능별 공통화 결정') if row[0] == '알림')
    # Fleet stays the sending owner until the D-997 cutover is verified.
    assert '`operations/fleet/fleet/incidents/notifications.py`(현재 발송 owner: Fleet)' in sources
    assert '`operations/notifications`(전달 서비스, 전환 전·미배포, D-998)' in sources
