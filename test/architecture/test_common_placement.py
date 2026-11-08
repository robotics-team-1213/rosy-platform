"""D-1001: common services run as their own hardened containers; Fleet keeps machine credentials."""
import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / 'deploy/site'
# Long-running common services of the R stack (docs/reference/common-services.md, 「배치와 장애 격리」).
COMMON = {'account', 'monitoring', 'media', 'media-gateway'}
# D-1001 debt lists. Entries leave when the cause is fixed; a new entry needs an ADR.
FLEET_IMAGE_USERS = {'fleet', 'fleet-backup', 'monitoring'}  # monitoring: until its own image (D-1001 step 2)
NO_MEM_LIMIT = {'fleet', 'vision', 'postgres', 'fleet-backup', 'proxy', 'control-unit-peer',
                'media-gateway', 'account-backup', 'account-backup-check'}  # sizes follow the D-994 24 h run
FORBIDDEN_MOUNTS = ('docker.sock', '/etc/rosy/fleet', 'host-control', 'sighting_data', 'vision_state', 'pg_data')
# 4-line re-exports of rosy_account; the implementation lives in Account (D-962).
FLEET_ACCOUNT_SHELLS = ('account_authority', 'account_authority_routes', 'account_config', 'account_ledger',
                        'account_routes', 'password_routes', 'password_session', 'site_users')
FLEET_AUTH = ROOT / 'operations/fleet/fleet/server/auth'


def _services():
    found = {}
    for path in sorted(SITE.glob('compose*.yaml')):
        for name, spec in yaml.safe_load(path.read_text(encoding='utf-8'))['services'].items():
            if 'image' in spec:
                found[name] = (path.name, spec)
    return found


def _sources(spec):
    return [item if isinstance(item, str) else str(item.get('source', '')) for item in spec.get('volumes', [])]


def _imports(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def _py(folder):
    return [path for path in folder.rglob('*.py') if '__pycache__' not in path.parts]


def test_common_services_are_hardened_and_isolated_from_fleet_state():
    services = _services()
    assert COMMON <= set(services)
    for name in sorted(COMMON):
        spec = services[name][1]
        assert spec.get('read_only') is True, name
        assert spec.get('cap_drop') == ['ALL'], name
        assert 'no-new-privileges:true' in spec.get('security_opt', []), name
        for source in _sources(spec):
            assert not any(bad in source for bad in FORBIDDEN_MOUNTS), (name, source)


def test_common_services_do_not_borrow_the_fleet_image_without_a_listed_reason():
    users = {name for name, (_, spec) in _services().items() if str(spec['image']).startswith('rosy-site-fleet:')}
    assert users == FLEET_IMAGE_USERS


def test_memory_limit_debt_only_shrinks():
    for name, (_, spec) in _services().items():
        if name in NO_MEM_LIMIT:
            assert 'mem_limit' not in spec, f'{name} has a limit now: remove it from NO_MEM_LIMIT'
        else:
            assert 'mem_limit' in spec, f'{name} needs mem_limit (D-994 §5 sizes come from the 24 h run)'


def test_media_project_stays_off_the_site_networks():
    spec = _services()['media'][1]
    assert not {'site_backend', 'site_edge'} & set(spec['networks'])


def test_fleet_account_files_are_reexport_shells():
    for name in FLEET_ACCOUNT_SHELLS:
        text = (FLEET_AUTH / f'{name}.py').read_text(encoding='utf-8')
        assert 'sys.modules[__name__]' in text and len(text.splitlines()) <= 6, name


def test_machine_credential_code_never_imports_the_human_account_service():
    for path in sorted(FLEET_AUTH.glob('pairing*.py')) + sorted(FLEET_AUTH.glob('enrollment*.py')):
        assert not any(m.split('.')[0] == 'rosy_account' for m in _imports(path)), path.name


def test_common_service_sources_do_not_import_fleet():
    for folder in (ROOT / 'operations/account/rosy_account', ROOT / 'operations/monitoring/src'):
        for path in _py(folder):
            assert not any(m == 'fleet' or m.startswith('fleet.') for m in _imports(path)), path
