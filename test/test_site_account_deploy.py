"""Account private authority material never enters camera or public proxy mounts."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_account_origin_resolves_to_its_tls_proxy_for_container_clients():
    base = yaml.safe_load((ROOT / 'deploy/site/compose.yaml').read_text())['services']
    proxy = yaml.safe_load((ROOT / 'deploy/site/compose.account.yaml').read_text())['services']['proxy']
    assert proxy['networks']['site_edge']['aliases'] == [
        '${ROSY_ACCOUNT_HTTPS_HOST:?set ROSY_ACCOUNT_HTTPS_HOST}']
    assert set(proxy['networks']) == set(base['proxy']['networks'])
    assert 'site_edge' not in base['fleet']['networks']
    assert 'network_mode' not in proxy


def test_authority_and_public_app_links_have_separate_mounts():
    services = yaml.safe_load((ROOT/'deploy/site/compose.yaml').read_text())['services']
    private = '/etc/rosy/account:/run/rosy-account:ro'
    public = '/etc/rosy/account-public:/run/rosy-account-public:ro'
    overlay = yaml.safe_load((ROOT/'deploy/site/compose.account.yaml').read_text())['services']
    account = overlay['account']
    assert private in account['volumes']
    assert private not in services['fleet']['volumes']
    assert services['fleet']['environment']['ROSY_ACCOUNT_CONFIG'] == ''
    assert overlay['fleet']['environment']['ROSY_FLEET_ACCOUNT_CLIENT_CONFIG'] == (
        '${ROSY_FLEET_ACCOUNT_CLIENT_CONFIG:?set ROSY_FLEET_ACCOUNT_CLIENT_CONFIG}')
    assert public in services['proxy']['volumes']
    assert private not in services['proxy']['volumes']
    assert private not in services['vision']['volumes']
    config = (ROOT/'deploy/site/Caddyfile').read_text()
    assert 'handle /.well-known/assetlinks.json {' in config
    assert 'root * /run/rosy-account-public' in config
    assert 'rewrite * /assetlinks.json' in config


def test_account_process_has_own_state_and_no_fleet_runtime_authority():
    account = yaml.safe_load((ROOT/'deploy/site/compose.account.yaml').read_text())['services']['account']
    assert account['image'] == 'rosy-site-fleet:${ROSY_SITE_IMAGE_TAG:-local}'
    assert account['command'][1:4] == ['python3', '-m', 'rosy_account']
    assert account['environment']['PYTHONPATH'] == (
        '/opt/rosy/src/operations/account:/opt/rosy/src/contracts/foundation')
    assert 'account_state:/var/lib/rosy-account' in account['volumes']
    assert not any('fleet' in str(mount) or 'docker.sock' in str(mount) for mount in account['volumes'])
    assert set(account['secrets']) == {'site_cert', 'site_key', 'site_ca'}
    assert account['networks'] == ['site_backend']
    assert 'depends_on' not in account
    assert account['read_only'] is True
    assert account['cap_drop'] == ['ALL']
    assert 'rosy_account.healthcheck' in account['healthcheck']['test']


def test_account_issuer_routes_to_independent_signed_process():
    config = (ROOT/'deploy/site/Caddyfile.account').read_text()
    assert 'reverse_proxy https://account:8098 {' in config
    assert 'reverse_proxy https://fleet:' not in config
    dockerfile = (ROOT/'deploy/site/Dockerfile.fleet').read_text()
    assert 'COPY operations/account/rosy_account/ /opt/rosy/src/operations/account/rosy_account/' in dockerfile
    assert '!operations/account/rosy_account/**' in (ROOT/'deploy/site/Dockerfile.fleet.dockerignore').read_text()
