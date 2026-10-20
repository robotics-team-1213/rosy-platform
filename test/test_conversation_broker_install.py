"""Administrator installer boundary checks; all host mutations are simulated."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'deploy/site/install_conversation_broker.py'


def module():
    assert SCRIPT.exists(), 'protected conversation installer is missing'
    spec = importlib.util.spec_from_file_location('conversation_install', SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_installer_rejects_unprivileged_before_reading_inputs(tmp_path):
    m = module()
    if os.geteuid() == 0:
        pytest.skip('unprivileged test account required')
    with pytest.raises(ValueError, match='ADMIN_INSTALL_REQUIRED'):
        m.require_admin()
    assert list(tmp_path.iterdir()) == []


def test_dispatcher_allows_only_two_exact_zero_argument_commands(tmp_path):
    m = module()
    script = tmp_path/'ingress'
    script.write_bytes(m.dispatcher())
    subprocess.run(['/bin/sh', '-n', str(script)], check=True)
    for command in ('', 'id', 'rosy-conversation-v1 extra', 'rosy-conversation-v1; id', 'rosy-status-v1\n'):
        p = subprocess.run(['/bin/sh', str(script)], env={'SSH_ORIGINAL_COMMAND': command}, capture_output=True)
        assert p.returncode == 64
    for command in ('rosy-status-v1', 'rosy-conversation-v1'):
        p = subprocess.run(['/bin/sh', str(script), 'unexpected'], env={'SSH_ORIGINAL_COMMAND': command}, capture_output=True)
        assert p.returncode == 64


def test_ingress_traverses_public_parent_without_broker_group(tmp_path):
    m = module()
    assert m.INGRESS == Path('/usr/local/libexec/rosy-model-ingress')
    assert not m.INGRESS.is_relative_to(m.LIBEXEC)
    if os.geteuid() == 0:
        pytest.skip('unprivileged traversal reproduction required')
    private = tmp_path/'protected'
    private.mkdir()
    blocked = private/'model-ingress'
    accessible = tmp_path/'rosy-model-ingress'
    for path in (blocked, accessible):
        path.write_bytes(m.dispatcher())
        path.chmod(0o755)
    private.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            subprocess.run([str(blocked)], check=False)
        assert subprocess.run([str(accessible)], env={'SSH_ORIGINAL_COMMAND':'unknown'}, check=False).returncode == 64
    finally:
        private.chmod(0o700)


@pytest.mark.parametrize('exitcode', [126, 127, 0])
def test_ingress_readback_rejects_unreachable_or_unexpected_command(tmp_path,monkeypatch,exitcode):
    import types
    m = module()
    calls = []
    def run(*args, **kwargs):
        calls.append((args,kwargs))
        return types.SimpleNamespace(returncode=exitcode,stdout=b'',stderr=b'')
    monkeypatch.setattr(m,'run',run)
    with pytest.raises(ValueError,match='INGRESS_EXECUTION_READBACK_FAILED') as error:
        m.verify_ingress()
    detail = json.loads(str(error.value).split(' ',1)[1])
    assert detail['command'] == 'rosy-conversation-v1' and detail['returncode'] == exitcode
    args,kwargs = calls[0]
    assert args[:4] == ('/usr/sbin/runuser','-u','rosy-model-ingress','--')
    assert args[4] == str(m.INGRESS)
    assert kwargs['input'] == b'{}\n' and kwargs['cwd'] == '/'


def test_root_path_rejects_untrusted_owner_and_symlink(tmp_path):
    m = module()
    target = tmp_path/'file'
    target.write_bytes(b'private')
    link = tmp_path/'link'
    link.symlink_to(target)
    with pytest.raises(ValueError, match='PROTECTED'):
        m.protected(link)
    if os.geteuid() != 0:
        with pytest.raises(ValueError, match='PROTECTED'):
            m.protected(target)


def test_replacement_is_idempotent_and_refuses_foreign_files(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setattr(m, 'protected', lambda p: p.read_bytes())
    monkeypatch.setattr(m, 'trusted_directory', lambda p: None)
    monkeypatch.setattr(m.os, 'chown', lambda *a: None)
    target = tmp_path/'managed'
    m.replace_managed(target, b'old', 0o600, os.getgid(), ())
    m.replace_managed(target, b'new', 0o600, os.getgid(), (b'old',))
    backup = target.with_name('managed.before-'+hashlib.sha256(b'old').hexdigest())
    assert backup.read_bytes() == b'old'
    m.replace_managed(target, b'new', 0o600, os.getgid(), ())
    assert len(list(tmp_path.iterdir())) == 2
    with pytest.raises(ValueError, match='FOREIGN'):
        m.replace_managed(target, b'foreign', 0o600, 0, ())
    assert target.read_bytes() == b'new'


def test_receipt_binds_independent_proof_and_source():
    m = module()
    proof = {'source_commit':'a'*40, 'source_manifest_sha256':'b'*64, 'suite_sha256':'c'*64,
             'evaluated_at':123, 'profile':{'revision':'d728-semantic-v2'}}
    receipt = {**{k:proof[k] for k in ('source_commit','source_manifest_sha256','suite_sha256','evaluated_at')},
        'schema':'rosy.conversation-evaluation-receipt/1', 'verdict':'PASS', 'evaluation_owner':'model_pc',
        'candidate_diagnostics_used':False, 'device_commands_performed':False,
        'protected_admission_performed':False, 'proof_sha256':'d'*64, 'profile_revision':'d728-semantic-v2'}
    m.validate_receipt(receipt, proof, 'd'*64)
    for key,value in [('source_commit','f'*40), ('proof_sha256','e'*64), ('evaluation_owner','ai_pc'),
                      ('candidate_diagnostics_used',True), ('suite_sha256','e'*64)]:
        with pytest.raises(ValueError, match='RECEIPT'):
            m.validate_receipt({**receipt,key:value}, proof, 'd'*64)

@pytest.fixture
def bundle(tmp_path, monkeypatch):
    import base64
    m = module()
    monkeypatch.setattr(m, 'REVIEWED', tmp_path)
    monkeypatch.setattr(m, 'trusted_directory', lambda p: None)
    monkeypatch.setattr(m, 'protected', lambda p: p.read_bytes())
    source = tmp_path/'source'
    names = ['deploy/site/deliberation_install.py', 'deploy/site/requirements-fleet.txt',
        'deploy/ai_pc/conversation_acceptance.py', 'deploy/ai_pc/deliberation_conversation_broker.py',
        'deploy/ai_pc/deliberation_conversation.py', 'operations/decision/src/rosy/decision/conversation/codec.py']
    files = {}
    for name in names:
        path = source/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'# source\n')
        files[name] = m.sha(path.read_bytes())
    manifest = {'source_commit':'a'*40,'files':files}
    proof = {'source_commit':'a'*40, 'source_manifest_sha256':m.sha(json.dumps(files,sort_keys=True,separators=(',',':')).encode()),
             'suite_sha256':'c'*64, 'evaluated_at':123, 'profile':{'revision':'d728-semantic-v2'}}
    proof_raw = json.dumps(proof).encode()
    receipt = {**{k:proof[k] for k in ('source_commit','source_manifest_sha256','suite_sha256','evaluated_at')},
        'schema':'rosy.conversation-evaluation-receipt/1', 'verdict':'PASS', 'evaluation_owner':'model_pc',
        'candidate_diagnostics_used':False, 'device_commands_performed':False,
        'protected_admission_performed':False, 'proof_sha256':m.sha(proof_raw), 'profile_revision':'d728-semantic-v2'}
    wire = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'+b'x'*32
    values = {'source-manifest.json':json.dumps(manifest).encode(), 'semantic-evaluation-proof.json':proof_raw,
              'semantic-evaluation-receipt.json':json.dumps(receipt).encode(),
              'ingress.pub':b'ssh-ed25519 '+base64.b64encode(wire)+b' fixture\n'}
    for name,raw in values.items():
        (tmp_path/name).write_bytes(raw)
    pins = dict(zip(('manifest','proof','receipt','public_key'),map(m.sha,values.values())))
    return m, tmp_path, pins


def test_reviewed_source_hashes_and_independent_receipt_match(bundle):
    m,root,pins = bundle
    manifest,proof,contents,*_ = m.inputs(root,pins)
    assert manifest['source_commit'] == proof['source_commit']
    assert set(contents) == set(manifest['files'])


@pytest.mark.parametrize('include_preprocessing', [False, True])
def test_d831_profile_requires_its_pinned_preprocessing_source(bundle, include_preprocessing):
    m, root, pins = bundle
    manifest = json.loads((root/'source-manifest.json').read_bytes())
    proof = json.loads((root/'semantic-evaluation-proof.json').read_bytes())
    receipt = json.loads((root/'semantic-evaluation-receipt.json').read_bytes())
    revision = 'd728-semantic-v3-d831'
    if include_preprocessing:
        name = 'operations/decision/src/rosy/decision/conversation/preprocessing.py'
        path = root/'source'/name
        path.write_bytes(b'# reviewed preprocessing\n')
        manifest['files'][name] = m.sha(path.read_bytes())
    proof['profile']['revision'] = revision
    proof['source_manifest_sha256'] = m.sha(json.dumps(manifest['files'], sort_keys=True, separators=(',',':')).encode())
    proof_raw = json.dumps(proof).encode()
    receipt.update(profile_revision=revision, proof_sha256=m.sha(proof_raw),
                   source_manifest_sha256=proof['source_manifest_sha256'])
    for name, key, data in [('source-manifest.json','manifest',manifest),
        ('semantic-evaluation-proof.json','proof',proof), ('semantic-evaluation-receipt.json','receipt',receipt)]:
        raw = json.dumps(data).encode()
        (root/name).write_bytes(raw)
        pins[key] = m.sha(raw)
    if include_preprocessing:
        assert m.inputs(root, pins)[1]['profile']['revision'] == revision
    else:
        with pytest.raises(ValueError):
            m.inputs(root, pins)


@pytest.mark.parametrize('name', ['source-manifest.json','semantic-evaluation-proof.json',
    'semantic-evaluation-receipt.json','ingress.pub','source/deploy/ai_pc/deliberation_conversation.py'])
def test_each_tampered_review_input_is_rejected(bundle,name):
    m,root,pins = bundle
    (root/name).write_bytes(b'changed')
    with pytest.raises(ValueError,match='SHA_MISMATCH'):
        m.inputs(root,pins)


def test_missing_proof_fails_before_any_installation(bundle):
    m,root,pins = bundle
    (root/'semantic-evaluation-proof.json').unlink()
    with pytest.raises(FileNotFoundError):
        m.inputs(root,pins)
    assert not (root/'venv').exists()


def test_incomplete_source_manifest_is_rejected_even_with_new_manifest_pin(bundle):
    m,root,pins = bundle
    path = root/'source-manifest.json'
    value = json.loads(path.read_bytes())
    value['files'].pop('deploy/ai_pc/deliberation_conversation_broker.py')
    path.write_text(json.dumps(value))
    pins['manifest'] = m.sha(path.read_bytes())
    with pytest.raises(ValueError,match='CLOSURE'):
        m.inputs(root,pins)


def test_changed_source_cannot_borrow_prior_evaluation(bundle):
    m,root,pins = bundle
    path = root/'source-manifest.json'
    value = json.loads(path.read_bytes())
    source = root/'source/deploy/ai_pc/deliberation_conversation.py'
    source.write_bytes(b'# changed source\n')
    value['files']['deploy/ai_pc/deliberation_conversation.py'] = m.sha(source.read_bytes())
    path.write_text(json.dumps(value))
    pins['manifest'] = m.sha(path.read_bytes())
    with pytest.raises(ValueError,match='EVALUATED_SOURCE'):
        m.inputs(root,pins)


@pytest.mark.parametrize('name', ['../outside.py','/etc/shadow','deploy//bad.py','deploy/./bad.py'])
def test_source_manifest_cannot_escape_snapshot(bundle,name):
    m,root,pins = bundle
    path = root/'source-manifest.json'
    value = json.loads(path.read_bytes())
    value['files'][name] = 'a'*64
    path.write_text(json.dumps(value))
    pins['manifest'] = m.sha(path.read_bytes())
    with pytest.raises(ValueError,match='SOURCE_PATH'):
        m.inputs(root,pins)


def test_ingress_account_refuses_unregistered_existing_account(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import grp
    import pwd
    m = module()
    account = SimpleNamespace(pw_name='rosy-model-ingress',pw_uid=996,pw_gid=983,pw_dir='/var/empty',pw_shell='/bin/sh')
    monkeypatch.setattr(pwd,'getpwnam',lambda _:account)
    monkeypatch.setattr(grp,'getgrgid',lambda _:SimpleNamespace(gr_name=account.pw_name,gr_mem=[]))
    monkeypatch.setattr(m,'protected',lambda p:p.read_bytes())
    with pytest.raises(FileNotFoundError):
        m.account_registration(None,tmp_path)


def test_ingress_account_rejects_supplementary_group(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import grp
    import pwd
    m = module()
    account = SimpleNamespace(pw_name='rosy-model-ingress',pw_uid=996,pw_gid=983,pw_dir='/var/empty',pw_shell='/bin/sh')
    monkeypatch.setattr(pwd,'getpwnam',lambda _:account)
    monkeypatch.setattr(pwd,'getpwall',lambda:[account])
    monkeypatch.setattr(grp,'getgrgid',lambda _:SimpleNamespace(gr_name=account.pw_name,gr_mem=[]))
    monkeypatch.setattr(m.os,'getgrouplist',lambda *a:[983,27])
    monkeypatch.setattr(m,'protected',lambda p:p.read_bytes())
    path = tmp_path/'ingress.json'
    path.write_text(json.dumps({'uid':996,'gid':983}))
    path.chmod(0o600)
    with pytest.raises(ValueError,match='DEDICATED_INGRESS'):
        m.account_registration(None,tmp_path)

@pytest.mark.parametrize('failure', ['verify','reload'])
def test_activation_rolls_back_every_changed_file_on_failure(tmp_path,monkeypatch,failure):
    m = module()
    assert hasattr(m,'activate'), 'transactional activation is missing'
    monkeypatch.setattr(m,'protected',lambda p:p.read_bytes())
    monkeypatch.setattr(m,'trusted_directory',lambda p:None)
    monkeypatch.setattr(m.os,'chown',lambda *a:None)
    old = tmp_path/'existing'
    old.write_bytes(b'old')
    old.chmod(0o600)
    created = tmp_path/'new'
    plans = [(old,b'changed',0o600,os.getgid(),(b'old',)), (created,b'new',0o600,os.getgid(),())]
    calls = []
    def verify():
        assert old.read_bytes() == b'changed' and created.read_bytes() == b'new'
        if failure == 'verify':
            raise RuntimeError('verify failed')
    def reload():
        calls.append('reload')
        if failure == 'reload' and len(calls) == 1:
            raise RuntimeError('reload failed')
    with pytest.raises(RuntimeError,match='failed'):
        m.activate(plans,verify,reload)
    assert old.read_bytes() == b'old'
    assert not created.exists()
    assert old.with_name('existing.before-'+m.sha(b'old')).read_bytes() == b'old'


def test_activation_checks_all_modes_before_first_write(tmp_path,monkeypatch):
    m = module()
    assert hasattr(m,'activate'), 'transactional activation is missing'
    monkeypatch.setattr(m,'protected',lambda p:p.read_bytes())
    monkeypatch.setattr(m,'trusted_directory',lambda p:None)
    old = tmp_path/'existing'
    old.write_bytes(b'same')
    old.chmod(0o644)
    plans = [(tmp_path/'new',b'new',0o600,os.getgid(),()), (old,b'same',0o600,os.getgid(),())]
    with pytest.raises(ValueError,match='MODE_CONFLICT'):
        m.activate(plans,lambda:None,lambda:None)
    assert not (tmp_path/'new').exists()


def test_offline_wheel_closure_binds_metadata_and_direct_requirements(tmp_path,monkeypatch):
    import io
    import zipfile
    m = module()
    assert hasattr(m,'dependencies'), 'offline dependency verification is missing'
    monkeypatch.setattr(m,'trusted_directory',lambda p:None)
    monkeypatch.setattr(m,'protected',lambda p:p.read_bytes())
    (tmp_path/'wheels').mkdir()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('demo-1.0.dist-info/METADATA','Name: demo\nVersion: 1.0\n')
    raw = stream.getvalue()
    (tmp_path/'wheels/demo-1.0-py3-none-any.whl').write_bytes(raw)
    doc = json.dumps({'wheels':{'demo-1.0-py3-none-any.whl':m.sha(raw)}}).encode()
    (tmp_path/'dependencies.json').write_bytes(doc)
    lock = m.dependencies(tmp_path,m.sha(doc),b'demo==1.0\n')
    assert lock == ('demo==1.0 --hash=sha256:'+m.sha(raw)+'\n').encode()
    with pytest.raises(ValueError,match='DEPENDENCY'):
        m.dependencies(tmp_path,m.sha(doc),b'demo==2.0\n')
    (tmp_path/'wheels/demo-1.0-py3-none-any.whl').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='SHA'):
        m.dependencies(tmp_path,m.sha(doc),b'demo==1.0\n')

@pytest.mark.parametrize('stage', ['dependencies','model','visudo','sshd','effective','configuration','reload',None,
    'upgrade','upgrade_missing','upgrade_wrong_config','upgrade_wrong_broker','upgrade_lone_config',
    'upgrade_lone_broker','upgrade_malformed','upgrade_foreign_wrapper','upgrade_rollback',
    'ingress','migration','migration_foreign','migration_rollback','no_status'])
def test_full_admin_install_preserves_existing_state_and_rolls_back(tmp_path,monkeypatch,stage):
    import types
    import time
    m = module()
    for name,relative in [('REVIEWED','reviewed'),('VERSIONS','opt/conversation'),('CONFIG','etc/conversation.json'),
        ('LIBEXEC','libexec/private'),('INGRESS','libexec/rosy-model-ingress'),
        ('PREVIOUS_INGRESS','libexec/private/model-ingress'),('STATUS','libexec/private/status-broker'),
        ('BROKER','libexec/conversation-broker'),('KEYS','ssh/keys'),('SUDO','sudo/rules'),('SSHD','ssh/sshd')]:
        path = tmp_path/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        monkeypatch.setattr(m,name,path)
    m.LIBEXEC.mkdir(exist_ok=True)
    bundle = m.REVIEWED
    bundle.mkdir()
    security = (tmp_path/'credential', tmp_path/'spent')
    for path in security:path.write_bytes(b'unchanged private state')
    monkeypatch.setattr(m,'SECURITY_FILES',security)
    if stage != 'no_status':
        m.STATUS.write_bytes(b'previous status owner')
        m.STATUS.chmod(0o750)
    status_config = m.CONFIG.parent/'status.json'
    if stage != 'no_status':
        status_config.write_bytes(b'previous status config')
        status_config.chmod(0o640)
    reviewer = m.CONFIG.parent/'status-reviewer-admission.json'
    reviewer.write_bytes(b'previous protected billing evidence')
    original_stat = m.Path.stat
    # Simulate only the privilege metadata; the actual file writes and rollback run in tmp_path.
    def simulated_stat(path,*a,**kw):
        st = original_stat(path,*a,**kw)
        values = list(st)
        values[4] = 0
        values[5] = 0
        return os.stat_result(values)
    monkeypatch.setattr(m.Path,'stat',simulated_stat)
    monkeypatch.setattr(m,'require_admin',lambda:None)
    monkeypatch.setattr(m,'trusted_directory',lambda p:None)
    monkeypatch.setattr(m,'protected',lambda p:p.read_bytes())
    monkeypatch.setattr(m.os,'chown',lambda *a:None)
    monkeypatch.setattr(m,'account_registration',lambda *a:None)
    account = types.SimpleNamespace(pw_name='rosy-deliberation',pw_uid=997,pw_gid=0)
    helper = types.SimpleNamespace(validated_account=lambda:account)
    def install_file(path,data,mode):
        if path.exists():
            assert path.read_bytes() == data
        else:
            path.write_bytes(data)
            path.chmod(mode)
    helper.install_file = install_file
    monkeypatch.setattr(m.importlib.util,'module_from_spec',lambda spec:helper)
    monkeypatch.setattr(m.importlib.util,'spec_from_file_location',lambda *a:types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda m:None)))
    contents = {'deploy/site/requirements-fleet.txt':b'demo==1.0\n'}
    manifest = {'source_commit':'a'*40,'files':{k:m.sha(v) for k,v in contents.items()}}
    proof = {'profile':{'revision':'d728-semantic-v2'},'policy':{'authority':'proposal_only'},'evaluated_at':time.time()}
    monkeypatch.setattr(m,'inputs',lambda *a:(manifest,proof,contents,b'proof',b'receipt','ssh-ed25519 fixture'))
    monkeypatch.setattr(m,'dependencies',lambda *a:(calls.append(('dependencies-read',)) or b'demo==1.0 --hash=sha256:' + b'b'*64+b'\n'))
    calls = []
    ingress_probes = []
    failures = []
    def fake_run(*args,**kwargs):
        calls.append(args)
        command = ' '.join(args)
        point = None
        if args[:4] == ('/usr/bin/python3','-I','-m','venv'):
            (Path(args[-1])/'bin').mkdir(parents=True)
        if '--require-hashes' in args:
            point = 'dependencies'
            assert '--no-index' in args and '--only-binary=:all:' in args
        if args[0] == '/usr/sbin/runuser':
            point = 'ingress' if args[2] == 'rosy-model-ingress' else ('model' if 'loaded(exchange(' in command else 'configuration')
        if args[0] == '/usr/sbin/visudo':point = 'visudo'
        if args[:2] == ('/usr/sbin/sshd','-t'):point = 'sshd'
        if args[:2] == ('/usr/sbin/sshd','-T'):point = 'effective'
        if args[:2] == ('/usr/bin/systemctl','reload'):point = 'reload'
        failure_stage = ('configuration' if stage == 'upgrade_rollback' and manifest['source_commit'] == 'd'*40
                         else 'ingress' if stage == 'migration_rollback' else stage)
        if point == failure_stage and stage is not None and not failures:
            failures.append(point)
            raise RuntimeError('injected '+point)
        if args[:2] == ('/usr/sbin/sshd','-T'):
            return types.SimpleNamespace(stdout='\n'.join(['forcecommand '+str(m.INGRESS),'authorizedkeysfile '+str(m.KEYS),
                'authenticationmethods publickey','pubkeyauthentication yes','passwordauthentication no','kbdinteractiveauthentication no',
                'disableforwarding yes','permittty no']))
        if point == 'ingress':
            name = kwargs['env']['SSH_ORIGINAL_COMMAND']
            ingress_probes.append((name,len(args)))
            if stage == 'no_status' and name == 'rosy-status-v1' and len(args) == 5:
                raise AssertionError('Absent optional status broker must not be probed')
            reason = {'rosy-status-v1':'STATUS', 'rosy-conversation-v1':'CONVERSATION'}.get(name)
            if reason and len(args) == 5:
                return types.SimpleNamespace(returncode=1,stdout=json.dumps({'state':'HOLD','reason':reason+'_BROKER_NOT_ADMITTED_OR_RESULT_UNKNOWN'}).encode(),stderr=b'')
            return types.SimpleNamespace(returncode=64,stdout=b'',stderr=b'')
        return types.SimpleNamespace(stdout='')
    monkeypatch.setattr(m,'run',fake_run)
    argv = [str(bundle)]
    for name in ('manifest','proof','receipt','public-key','dependencies'):
        argv += ['--'+name+'-sha256','b'*64]
    if stage and stage.startswith('migration'):
        old_key = ('restrict,command="'+m.PREVIOUS_FORCE+'" ssh-ed25519 fixture\n').encode()
        old_sshd = m.SSHD_BASE.format(m.PREVIOUS_FORCE).encode()
        old_dispatcher = m.dispatcher() if stage != 'migration_foreign' else b'foreign'
        for path,raw,mode in ((m.KEYS,old_key,0o644),(m.SSHD,old_sshd,0o644),(m.PREVIOUS_INGRESS,old_dispatcher,0o755)):
            path.write_bytes(raw)
            path.chmod(mode)
        if stage == 'migration':
            assert m.main(argv) == 0
            assert m.NEW_FORCE.encode() in m.KEYS.read_bytes()
            assert m.main(argv) == 0
        else:
            with pytest.raises((RuntimeError,ValueError)):
                m.main(argv)
            assert m.KEYS.read_bytes() == old_key and m.SSHD.read_bytes() == old_sshd
            assert not m.INGRESS.exists()
        assert m.PREVIOUS_INGRESS.read_bytes() == old_dispatcher
    elif stage and stage.startswith('upgrade'):
        assert m.main(argv) == 0
        old_config,old_broker = m.CONFIG.read_bytes(),m.BROKER.read_bytes()
        manifest['source_commit'] = 'd'*40
        supplied = [m.sha(old_config),m.sha(old_broker)]
        if stage == 'upgrade_wrong_config':supplied[0] = '0'*64
        if stage == 'upgrade_wrong_broker':supplied[1] = '0'*64
        if stage == 'upgrade_malformed':supplied[0] = 'not-a-sha'
        if stage == 'upgrade_foreign_wrapper':
            old_broker = b'#!/bin/sh\nexec /bin/sh\n'
            m.BROKER.write_bytes(old_broker)
            supplied[1] = m.sha(old_broker)
        if stage != 'upgrade_missing':
            if stage != 'upgrade_lone_broker':argv += ['--previous-config-sha256',supplied[0]]
            if stage != 'upgrade_lone_config':argv += ['--previous-broker-sha256',supplied[1]]
        calls.clear()
        if stage in ('upgrade','upgrade_rollback'):
            if stage == 'upgrade':
                assert m.main(argv) == 0
                assert json.loads(m.CONFIG.read_bytes())['source_commit'] == 'd'*40
                assert (str(m.VERSIONS/('d'*40))).encode() in m.BROKER.read_bytes()
                for path,raw in ((m.CONFIG,old_config),(m.BROKER,old_broker)):
                    assert path.with_name(path.name+'.before-'+m.sha(raw)).read_bytes() == raw
                assert m.main(argv[:-4]) == 0
            else:
                with pytest.raises(RuntimeError,match='injected configuration'):m.main(argv)
                assert m.CONFIG.read_bytes() == old_config and m.BROKER.read_bytes() == old_broker
        else:
            with pytest.raises(ValueError):m.main(argv)
            assert calls == []
            assert not (m.VERSIONS/('d'*40)).exists()
            assert m.CONFIG.read_bytes() == old_config and m.BROKER.read_bytes() == old_broker
    elif stage in (None,'no_status'):
        assert m.main(argv) == 0
        assert m.main(argv) == 0
        assert len([c for c in calls if '--require-hashes' in c]) == 1
        cfg = json.loads(m.CONFIG.read_bytes())
        assert cfg['valid_until'] == proof['evaluated_at']+7*86400
        assert ('rosy-conversation-v1',5) in ingress_probes
        assert ('unknown',5) in ingress_probes
        assert ('rosy-status-v1',6) in ingress_probes and ('rosy-conversation-v1',6) in ingress_probes
        assert (('rosy-status-v1',5) in ingress_probes) == (stage is None)
    else:
        with pytest.raises(RuntimeError,match='injected '+stage):
            m.main(argv)
        assert all(not p.exists() for p in (m.CONFIG,m.BROKER,m.INGRESS,m.KEYS,m.SUDO,m.SSHD))
    assert all(path.read_bytes() == b'unchanged private state' for path in security)
    if stage == 'no_status':
        assert not m.STATUS.exists() and not status_config.exists()
    else:
        assert m.STATUS.read_bytes() == b'previous status owner'
        assert status_config.read_bytes() == b'previous status config'
    assert reviewer.read_bytes() == b'previous protected billing evidence'
    assert all('execute(' not in ' '.join(c) and '/api/chat' not in ' '.join(c) for c in calls)
