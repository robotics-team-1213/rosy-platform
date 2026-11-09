"""The site Account TLS renewer takes its folder and hostname as arguments, never a baked-in site."""
import configparser
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'deploy/site/account_tls_renew.py'


def load():
    spec = importlib.util.spec_from_file_location('account_tls_renew', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_site_hostname_or_preparation_folder_is_written_in_the_public_source():
    text = SCRIPT.read_text(encoding='utf-8')
    assert '.ts.net' not in text and 'rosy-account-preparation' not in text
    assert "domain = os.environ['ROSY_TLS_DOMAIN']" in load().HELPER


def test_refuses_root_or_relative_certificate_folder(monkeypatch):
    module = load()
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: pytest.fail('docker reached'))
    for certs in ('/', '', 'relative'):
        monkeypatch.setattr('sys.argv', ['x', '--certs', certs, '--domain', 'site.example.net'])
        with pytest.raises(SystemExit):
            module.main()


@pytest.mark.parametrize('domain', ['', 'bad host', 'a/b', '../x'])
def test_refuses_a_missing_folder_or_a_non_dns_name_before_docker(tmp_path, monkeypatch, domain):
    module = load()
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: pytest.fail('docker reached'))
    for certs, name in ((tmp_path / 'missing', 'site.example.net'), (tmp_path, domain)):
        monkeypatch.setattr('sys.argv', ['x', '--certs', str(certs), '--domain', name])
        with pytest.raises(SystemExit):
            module.main()


def _renew_with_pending(module, tmp_path, monkeypatch, exec_result):
    (tmp_path / '.tls-reload-pending').touch()
    monkeypatch.setattr('sys.argv', ['x', '--certs', str(tmp_path), '--domain', 'site.example.net'])
    monkeypatch.setattr(module, 'PRODUCTION', tmp_path / 'absent')
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: '[{"Image": "sha256:x"}]')
    commands = []

    def run(command, **_):
        commands.append(command)
        if command[:2] == ['docker', 'exec']:
            return exec_result(command)
        return module.subprocess.CompletedProcess(command, 0, stdout='{}', stderr='')

    monkeypatch.setattr(module.subprocess, 'run', run)
    return commands


def test_changed_pair_reloads_only_the_account_proxy(tmp_path, monkeypatch):
    module = load()
    commands = _renew_with_pending(module, tmp_path, monkeypatch, lambda command: None)
    module.main()
    assert not (tmp_path / '.tls-reload-pending').exists()
    assert not any('vault' in part for command in commands for part in command)


def test_failed_account_reload_keeps_the_pending_marker(tmp_path, monkeypatch):
    module = load()

    def fail(command):
        raise module.subprocess.CalledProcessError(1, command)

    _renew_with_pending(module, tmp_path, monkeypatch, fail)
    with pytest.raises(RuntimeError, match='reload pending: Account'):
        module.main()
    assert (tmp_path / '.tls-reload-pending').exists()


def test_unit_reads_code_folder_and_hostname_from_its_environment_file():
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(ROOT / 'deploy/site/rosy-account-tls-renew.service')
    assert unit['Service']['EnvironmentFile'] == '%h/.config/rosy/account-tls.env'
    assert unit['Service']['ExecStart'] == ('/usr/bin/python3 ${ROSY_ACCOUNT_TLS_SOURCE} --certs '
                                            '${ROSY_ACCOUNT_TLS_CERTS} --domain ${ROSY_ACCOUNT_TLS_DOMAIN}')


def test_pilot_fetch_imports_from_the_signed_model_code_release():
    unit = (ROOT / 'deploy/model_pc/rosy-pilot-fetch@.service').read_text(encoding='utf-8')
    command = next(line for line in unit.splitlines() if line.startswith('ExecStart='))
    assert '-I %h/.local/lib/rosy-model-code/rosy_model_code.py' in command
    assert '--config %h/.config/rosy/model-code.json exec dataset/fetch_http.py' in command
    assert 'Environment=PYTHONPATH=' not in unit


def test_system_twin_runs_the_signed_release_script_and_keeps_certs_outside_it():
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(ROOT / 'deploy/site/rosy-site-account-tls-renew.service')
    service = unit['Service']
    assert service['EnvironmentFile'] == '/etc/rosy/site/account-tls.env'
    assert service['ExecStart'] == ('/usr/bin/python3 -I /opt/rosy/candidate/deploy/site/account_tls_renew.py '
                                    '--certs ${ROSY_ACCOUNT_TLS_CERTS} --domain ${ROSY_ACCOUNT_TLS_DOMAIN}')
    assert service['UMask'] == '0077' and service['NoNewPrivileges'] == 'yes'
    assert 'ROSY_ACCOUNT_TLS_SOURCE' not in (ROOT / 'deploy/site/rosy-site-account-tls-renew.service').read_text()
    timer = (ROOT / 'deploy/site/rosy-site-account-tls-renew.timer').read_text()
    assert 'Unit=rosy-site-account-tls-renew.service' in timer and 'Persistent=true' in timer
    env = dict(line.split('=', 1) for line in (ROOT / 'deploy/site/account-tls.env.example').read_text().splitlines()
               if line and not line.startswith('#'))
    assert set(env) == {'ROSY_ACCOUNT_TLS_CERTS', 'ROSY_ACCOUNT_TLS_DOMAIN'} and env['ROSY_ACCOUNT_TLS_DOMAIN'] == ''
    assert not env['ROSY_ACCOUNT_TLS_CERTS'].startswith(('/opt/rosy/candidate', '/etc/rosy/account-tls'))


def test_signed_candidate_builds_and_requires_the_renewal_group():
    from deploy.site import build_candidate, verify_candidate
    group = set(verify_candidate.ACCOUNT_TLS_FILES)
    assert group <= set(build_candidate.DEPLOY_FILES) and group <= set(verify_candidate.REQUIRED_DEPLOYMENT_FILES)
    assert all((ROOT / 'deploy/site' / name).is_file() for name in group)
