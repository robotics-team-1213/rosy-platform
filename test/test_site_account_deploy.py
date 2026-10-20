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
    assert private in services['fleet']['volumes']
    assert services['fleet']['environment']['ROSY_ACCOUNT_CONFIG'] == '${ROSY_ACCOUNT_CONFIG:-}'
    assert public in services['proxy']['volumes']
    assert private not in services['proxy']['volumes']
    assert private not in services['vision']['volumes']
    config = (ROOT/'deploy/site/Caddyfile').read_text()
    assert 'handle /.well-known/assetlinks.json {' in config
    assert 'root * /run/rosy-account-public' in config
    assert 'rewrite * /assetlinks.json' in config
