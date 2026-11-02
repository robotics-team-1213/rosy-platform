"""Independent Account identity backups never borrow a Fleet image or create a new authority volume."""
import json
from pathlib import Path

import pytest
import yaml

from test_site_candidate_verifier import candidate, _add_account, _verify, _load_verifier

ROOT = Path(__file__).resolve().parents[1]
FILES = {'compose.account-backup.yaml', 'rosy-account-backup.service', 'rosy-account-backup.timer',
         'rosy-account-backup-check.service', 'rosy-account-backup-check.timer'}


def test_account_maintenance_jobs_use_only_existing_authority_volume_and_own_image():
    config = yaml.safe_load((ROOT / 'deploy/site/compose.account-backup.yaml').read_text())
    assert config['volumes'] == {'account_state': {'external': True, 'name': 'rosy-site_account_state'}}
    assert set(config['services']) == {'account-backup', 'account-backup-check'}
    for job in config['services'].values():
        assert job['image'] == 'rosy-site-account:${ROSY_SITE_IMAGE_TAG:-local}'
        assert job['pull_policy'] == 'never' and 'build' not in job
        assert job['profiles'] == ['backup']
        assert job['entrypoint'] == ['python3', '/opt/rosy/site_db.py']
        assert job['user'] == '10001:10001' and job['network_mode'] == 'none'
        assert job['read_only'] is True and job['cap_drop'] == ['ALL']
        assert job['security_opt'] == ['no-new-privileges:true']
        assert not set(job) & {'depends_on', 'secrets', 'cap_add', 'ports'}
    backup, check = (config['services'][name] for name in ('account-backup', 'account-backup-check'))
    assert backup['command'] == ['backup', '--source', '/var/lib/rosy-account/account.sqlite3',
        '--dest-dir', '/backup', '--prune', '14', '--prune-history', '0', '--prune-audit', '0']
    assert check['command'] == ['check', '--dest-dir', '/backup', '--max-age-hours', '48']
    assert backup['volumes'][0] == {'type': 'volume', 'source': 'account_state',
                                   'target': '/var/lib/rosy-account'}
    assert len(check['volumes']) == 1 and check['volumes'][0]['read_only'] is True
    for job in (backup, check):
        bind = next(mount for mount in job['volumes'] if mount['type'] == 'bind')
        assert bind['source'] == '${ROSY_ACCOUNT_BACKUP_DIR:-/var/backups/rosy-account}'
        assert bind['target'] == '/backup' and bind['bind'] == {'create_host_path': False}
    docker = (ROOT / 'deploy/site/Dockerfile.account').read_text()
    assert 'COPY deploy/site/site_db.py /opt/rosy/site_db.py' in docker


def test_account_backup_units_are_separate_opt_in_and_never_pull_or_build():
    for name in ('rosy-account-backup.service', 'rosy-account-backup-check.service'):
        unit = (ROOT / 'deploy/site' / name).read_text()
        assert '--project-name rosy-site' in unit
        assert '--env-file /etc/rosy/site/site.env' in unit
        assert '-f /opt/rosy/candidate/deploy/site/compose.account-backup.yaml' in unit
        assert 'run --rm --no-deps --pull never ' in unit
        assert 'fleet' not in unit.lower() and 'ExecStartPre=' not in unit
    daily = (ROOT / 'deploy/site/rosy-account-backup.timer').read_text()
    check = (ROOT / 'deploy/site/rosy-account-backup-check.timer').read_text()
    assert 'OnCalendar=daily' in daily and 'Persistent=true' in daily
    assert 'OnUnitInactiveSec=6h' in check
    assert 'account-backup' not in (ROOT / 'deploy/site/rosy-site-stack.service').read_text()


@pytest.mark.parametrize('damage', ['missing_one', 'missing_group', 'tampered'])
def test_new_signed_account_inventory_requires_complete_authenticated_backup_group(candidate, damage):
    _add_account(candidate)
    root = candidate[0]
    manifest = json.loads((root / 'release.json').read_text())
    assert FILES <= manifest['deployment_file_sha256'].keys()
    assert _verify(candidate)['verified_images'][-1] == 'account'
    if damage == 'tampered':
        (root / 'deploy/site/rosy-account-backup.service').write_text('unreviewed command')
    else:
        removed = FILES if damage == 'missing_group' else {'rosy-account-backup.timer'}
        for name in removed:
            manifest['deployment_file_sha256'].pop(name)
        (root / 'release.json').write_text(json.dumps(manifest))
    with pytest.raises(_load_verifier().CandidateVerificationError):
        _verify(candidate)


def test_legacy_signed_inventory_needs_no_account_maintenance_group(candidate):
    manifest = json.loads((candidate[0] / 'release.json').read_text())
    assert not FILES & manifest['deployment_file_sha256'].keys()
    assert 'account' not in _verify(candidate)['verified_images']
