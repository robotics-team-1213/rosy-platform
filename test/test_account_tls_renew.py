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


@pytest.mark.parametrize('domain', ['', 'bad host', 'a/b', '../x'])
def test_refuses_a_missing_folder_or_a_non_dns_name_before_docker(tmp_path, monkeypatch, domain):
    module = load()
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **k: pytest.fail('docker reached'))
    for certs, name in ((tmp_path / 'missing', 'site.example.net'), (tmp_path, domain)):
        monkeypatch.setattr('sys.argv', ['x', '--certs', str(certs), '--domain', name])
        with pytest.raises(SystemExit):
            module.main()


def test_unit_reads_code_folder_and_hostname_from_its_environment_file():
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(ROOT / 'deploy/site/rosy-account-tls-renew.service')
    assert unit['Service']['EnvironmentFile'] == '%h/.config/rosy/account-tls.env'
    assert unit['Service']['ExecStart'] == ('/usr/bin/python3 ${ROSY_ACCOUNT_TLS_SOURCE} --certs '
                                            '${ROSY_ACCOUNT_TLS_CERTS} --domain ${ROSY_ACCOUNT_TLS_DOMAIN}')


def test_pilot_fetch_imports_from_the_signed_model_code_release():
    unit = (ROOT / 'deploy/model_pc/rosy-pilot-fetch@.service').read_text(encoding='utf-8')
    path = next(line for line in unit.splitlines() if line.startswith('Environment=PYTHONPATH='))
    assert all(part.startswith('%h/.local/share/rosy/model-code/current/') for part in path.split('=', 2)[2].split(':'))
