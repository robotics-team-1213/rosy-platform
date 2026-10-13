"""Account private authority material never enters camera or public proxy mounts."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


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
