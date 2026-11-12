"""Sealed PostgreSQL context backups reuse the signed mirrored postgres image, never a pull."""
import json
from pathlib import Path

import pytest
import yaml

from deploy.site.build_candidate import MIRRORED_IMAGES
from test_site_candidate_verifier import candidate, _verify, _load_verifier

ROOT = Path(__file__).resolve().parents[1]
FILES = {'compose.pg-backup.yaml', 'rosy-pg-backup.service', 'rosy-pg-backup.timer',
         'rosy-pg-backup-check.service', 'rosy-pg-backup-check.timer'}


def test_pg_backup_jobs_reuse_sealed_mirror_image_and_never_pull_or_build():
    config = yaml.safe_load((ROOT / 'deploy/site/compose.pg-backup.yaml').read_text())
    assert set(config) == {'x-pg-maintenance', 'services', 'networks', 'secrets'}
    assert config['networks'] == {'site_backend': {'external': True, 'name': 'rosy-site_site_backend'}}
    assert config['secrets'] == {'postgres_password': {
        'file': '${ROSY_SITE_SECRETS_DIR:?set ROSY_SITE_SECRETS_DIR}/postgres_password'}}
    assert set(config['services']) == {'pg-backup', 'pg-backup-check'}
    for job in config['services'].values():
        assert job['image'] == 'rosy-site-postgres:${ROSY_SITE_IMAGE_TAG:?set ROSY_SITE_IMAGE_TAG}'
        assert MIRRORED_IMAGES['postgres'] == 'postgres:16-alpine'  # the sealed upstream of this image
        assert job['pull_policy'] == 'never' and 'build' not in job
        assert job['read_only'] is True and job['cap_drop'] == ['ALL']
        assert job['security_opt'] == ['no-new-privileges:true']
        assert job['tmpfs'] == ['/tmp:rw,noexec,nosuid,size=32m']
        assert job['networks'] == ['site_backend'] and job['secrets'] == ['postgres_password']
        assert job['entrypoint'] == ['sh', '-eu', '-c'] and job['user'] == '70:70'
        assert job['mem_limit'] == '512m'
        assert job['environment'] == {'PGHOST': 'postgres', 'PGPORT': '5432',
                                      'PGDATABASE': 'rosy_context',
                                      'PGUSER': '${ROSY_SITE_POSTGRES_USER:-rosy}',
                                      'PGPASSFILE': '/tmp/.pgpass'}
        assert not set(job) & {'depends_on', 'cap_add', 'ports'}
    backup, check = (config['services'][name] for name in ('pg-backup', 'pg-backup-check'))
    assert backup['profiles'] == ['backup'] and check['profiles'] == ['backup-check']
    dump = backup['command'][0]
    assert len(backup['command']) == 1
    assert 'tmp=/backup/postgres-backup-$$stamp.dump.tmp' in dump
    assert 'pg_dump -Fc -f "$$tmp"' in dump
    assert 'pg_restore --list "$$tmp" >/dev/null' in dump
    assert 'chmod 0600 "$$tmp"' in dump
    assert 'mv "$$tmp" /backup/postgres-backup-$$stamp.dump' in dump
    assert 'sort -r | tail -n +15' in dump  # keep only the newest fourteen dumps
    fresh = check['command'][0]
    assert len(check['command']) == 1
    assert 'ls -1 /backup/postgres-backup-*.dump | sort | tail -n 1' in fresh
    assert '[ "$$age" -lt 48 ]' in fresh
    assert 'pg_restore --list "$$newest" >/dev/null' in fresh
    assert backup['volumes'][0]['source'] == '${ROSY_PG_BACKUP_DIR:-/var/backups/rosy-pg}'
    assert check['volumes'][0]['source'] == '${ROSY_PG_BACKUP_DIR:-/var/backups/rosy-pg}'
    for job in (backup, check):
        bind = job['volumes'][0]
        assert bind['type'] == 'bind' and bind['target'] == '/backup'
        assert bind['bind'] == {'create_host_path': False}
    assert 'read_only' not in backup['volumes'][0] and check['volumes'][0]['read_only'] is True


def test_pg_backup_units_are_separate_opt_in_and_never_pull_or_build():
    for name, job in (('rosy-pg-backup.service', 'pg-backup'),
                      ('rosy-pg-backup-check.service', 'pg-backup-check')):
        unit = (ROOT / 'deploy/site' / name).read_text()
        assert '--project-name rosy-site' in unit
        assert '--env-file /etc/rosy/site/site.env' in unit
        assert 'EnvironmentFile=/etc/rosy/site/site.env' in unit
        assert '-f /opt/rosy/candidate/deploy/site/compose.pg-backup.yaml' in unit
        assert f'run --rm --no-deps --pull never {job}\n' in unit
        assert 'fleet' not in unit.lower() and 'ExecStartPre=' not in unit
    daily = (ROOT / 'deploy/site/rosy-pg-backup.timer').read_text()
    check = (ROOT / 'deploy/site/rosy-pg-backup-check.timer').read_text()
    assert 'OnCalendar=daily' in daily and 'Persistent=true' in daily
    assert 'RandomizedDelaySec=15m' in daily
    assert 'OnBootSec=30min' in check and 'OnUnitInactiveSec=6h' in check
    assert 'pg-backup' not in (ROOT / 'deploy/site/rosy-site-stack.service').read_text()


@pytest.mark.parametrize('damage', ['missing_one', 'tampered'])
def test_new_signed_pg_inventory_group_is_indivisible_and_authenticated(candidate, damage):
    root = candidate[0]
    manifest = json.loads((root / 'release.json').read_text())
    assert FILES <= manifest['deployment_file_sha256'].keys()
    if damage == 'tampered':
        (root / 'deploy/site/rosy-pg-backup.service').write_text('unreviewed command')
    else:
        manifest['deployment_file_sha256'].pop('rosy-pg-backup.timer')
        (root / 'release.json').write_text(json.dumps(manifest))
    with pytest.raises(_load_verifier().CandidateVerificationError):
        _verify(candidate)


def test_legacy_signed_inventory_without_pg_group_stays_verifiable(candidate):
    root = candidate[0]
    manifest = json.loads((root / 'release.json').read_text())
    for name in FILES:
        del manifest['deployment_file_sha256'][name]
        (root / 'deploy/site' / name).unlink()
    (root / 'release.json').write_text(json.dumps(manifest))
    assert 'postgres' in _verify(candidate)['verified_images']


def test_pg_group_requires_the_postgres_image_inventory(candidate):
    root = candidate[0]
    manifest = json.loads((root / 'release.json').read_text())
    del manifest['images']['postgres']
    (root / 'release.json').write_text(json.dumps(manifest))
    with pytest.raises(_load_verifier().CandidateVerificationError,
                       match='PostgreSQL maintenance requires the signed postgres image'):
        _verify(candidate)
