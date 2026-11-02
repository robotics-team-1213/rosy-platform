"""G1 plan coverage and evidence rejection, using synthetic tests rather than timing retries."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
import affected_tests

from harness import affected_exclusive as exclusive
from test_land import cached, commit, land, repos  # existing fake landing boundary

ROOT = Path(__file__).resolve().parents[1]
CLEAN = '[g1-timing-gate] expected=2 collected=2 passed=2 skipped=0 clean=1\n2 passed in 0.01s\n'


@pytest.mark.parametrize('invocations', [[], [['test', '--ignore=' + exclusive.TARGET]],
    [exclusive.DEDICATED, exclusive.DEDICATED], [exclusive.DEDICATED, ['test']],
    [exclusive.DEDICATED[:-1]], [exclusive.DEDICATED + ['-k', 'one']],
    [exclusive.DEDICATED, ['--ignore=' + exclusive.TARGET]]])
def test_missing_duplicate_partial_or_empty_jobs_cannot_cover_full(invocations):
    with pytest.raises(ValueError):
        exclusive.validate(invocations, True)


def test_duplicate_prebuilt_jobs_are_rejected_at_both_producer_boundaries():
    with pytest.raises(ValueError):
        exclusive.separate([exclusive.DEDICATED, exclusive.DEDICATED])
    with pytest.raises(ValueError):
        exclusive.matrix([{'invocations': [exclusive.DEDICATED, exclusive.DEDICATED]}], True)


@pytest.mark.parametrize('paths', [['test'], [exclusive.TARGET, 'test/test_other.py'], [exclusive.TARGET]])
def test_ordinary_real_collection_excludes_timing_for_directories_and_explicit_files(tmp_path, paths):
    target = tmp_path / exclusive.TARGET
    target.parent.mkdir()
    target.write_text('def test_timing_stub(): pass\n', encoding='utf-8')
    (target.parent / 'test_other.py').write_text('def test_other(): pass\n', encoding='utf-8')
    invocations = exclusive.separate([paths])
    assert invocations[-1] == exclusive.DEDICATED
    for inv in invocations[:-1]:
        result = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q', *inv],
            cwd=tmp_path, env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'},
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'test_other.py::test_other' in result.stdout
        assert 'test_platform_g1_timing.py::' not in result.stdout


@pytest.mark.parametrize('body,args,alone,good', [
    ('def test_one(): pass\ndef test_two(): pass\n', [], '1', True),
    ('import pytest\ndef test_one():\n with pytest.raises(pytest.skip.Exception): pytest.skip("self-check")\n'
     'def test_two(): pass\n', [], '1', True),
    ('import pytest\ndef test_one(): pass\ndef test_two(): pytest.skip("contended")\n', [], '1', False),
    ('def test_one(): pass\ndef test_two(): assert False\n', [], '1', False),
    ('def test_one(): pass\ndef test_two(): pass\n', ['-k', 'one'], '1', False),
    ('def test_one(): pass\n', ['--collect-only'], '1', False),
    ('value = 1\n', [], '1', False),
    ('def test_one(): pass\n', ['DUPLICATE'], '1', False),
    ('def test_one(): pass\n', [], '0', False),
])
def test_gate_observes_whole_collection_and_real_results(tmp_path, body, args, alone, good):
    target = tmp_path / 'test_timing_stub.py'
    target.write_text(body, encoding='utf-8')
    argv = [str(target), '-q', '-pno:cacheprovider', '-pno:xdist', *args]
    argv = [str(target) if word == 'DUPLICATE' else word for word in argv]
    script = ('import sys,pytest; sys.path.insert(0,' + repr(str(ROOT)) + '); '
              'from tools.g1_timing_gate import TimingGate; '
              'sys.exit(pytest.main(' + repr(argv) + ', plugins=[TimingGate(' + repr(str(target)) + ')]))')
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'ROSY_JOB_ALONE': alone}, timeout=30)
    log = tmp_path / 'result.txt'
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    assert (result.returncode == 0) == good, result.stdout + result.stderr
    if body == 'value = 1\n':
        assert result.returncode == 1, 'exit5 is accepted by ordinary CI/lab; this required file must fail'
    assert (exclusive.evidence(log, result.returncode) is None) == good


@pytest.mark.parametrize('text,code', [('', 0), ('2 passed in 0.01s\n', 0), (CLEAN + CLEAN, 0),
    (CLEAN.replace('skipped=0', 'skipped=1'), 0), (CLEAN.replace('collected=2', 'collected=1'), 0),
    (CLEAN.replace('2 passed in', '1 failed, 1 passed in'), 1), (CLEAN, 1)])
def test_nonclean_dedicated_job_is_not_retried_or_cached(cached, monkeypatch, text, code):
    wt, run, _ = cached
    commit(wt, {exclusive.TARGET: 'def test_stub(): pass\n'}, 'timing fixture')
    calls = []

    def remote(invocations, logs, *args, on_done=None, **kwargs):
        calls.append(invocations)
        for inv, log in zip(invocations, logs):
            log.write_text(text, encoding='utf-8')
            if on_done:
                on_done(inv, log)
        return [code] * len(invocations)

    monkeypatch.setattr(land.remote_pytest, 'run', remote)
    with pytest.raises(land.Stop):
        run([exclusive.DEDICATED])
    assert calls == [[exclusive.DEDICATED]]
    assert land.land_cache.entries(wt) == []


def test_ci_extracts_exclusive_environment_before_passing_pytest_arguments():
    args, environment = exclusive.split_environment(exclusive.DEDICATED)
    assert environment == {'ROSY_JOB_ALONE': '1'} and args[0] == exclusive.TARGET
    workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    assert 'paths, job_environment = split_environment(paths)' in workflow
    assert '(rest, job_environment)' in workflow
    assert 'ids = [] if dedicated(paths)' in workflow


def test_affected_json_cannot_drop_the_required_timing_file_or_leave_only_flags():
    selection = {'mode': 'affected', 'invocations': [['test', '--ignore=' + exclusive.TARGET],
                                                     exclusive.DEDICATED]}
    with pytest.raises(ValueError):
        exclusive.affected_invocations(selection, {exclusive.TARGET})


def test_affected_runner_exports_job_words_instead_of_using_them_as_paths(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(affected_tests.subprocess, 'run', run)
    selection = affected_tests.Selection('affected', [], invocations=[exclusive.DEDICATED])
    assert affected_tests.run(tmp_path, selection) == 0
    command, kwargs = calls[0]
    assert exclusive.ALONE not in command and exclusive.TARGET in command
    assert kwargs['env']['ROSY_JOB_ALONE'] == '1'


def test_remote_exclusive_failure_cannot_turn_green_through_quarantine(tmp_path, monkeypatch):
    remote = land.remote_pytest
    monkeypatch.setattr(remote, 'ship', lambda *a, **k: None)
    monkeypatch.setattr(remote, 'deps', lambda *a: ('d' * 16, []))
    monkeypatch.setattr(remote, 'remote', lambda *a, **k: subprocess.CompletedProcess([], 0, b'', b''))
    node = exclusive.TARGET + '::test_fixture'
    monkeypatch.setattr(remote, 'quarantine', lambda *a: {node: 'synthetic quarantine'})
    calls = []

    def job(host, name, key, log, job_args, inv, *args):
        calls.append(inv)
        log.write_text('FAILED ' + node + ' - fixture miss\n', encoding='utf-8')
        return 1

    monkeypatch.setattr(remote.remote_job, 'run', job)
    assert remote.run_on('fixture-host', [exclusive.DEDICATED], [tmp_path / 'remote.txt'],
                         'ab' * 20, tmp_path, None) == [1]
    assert calls == [exclusive.DEDICATED]
