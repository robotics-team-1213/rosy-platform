"""CI dispatches each Android project through the real committed wrapper."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('app', ['operations/ui/cam', 'middleware/ui/pilot/android'])
def test_each_matrix_project_reaches_wrapper_java_with_its_own_unit_task(tmp_path, app):
    workflow = yaml.safe_load((ROOT / '.github/workflows/android.yml').read_text('utf-8'))
    job = workflow['jobs']['android-unit']
    assert set(job['strategy']['matrix']['app']) == {'operations/ui/cam', 'middleware/ui/pilot/android'}
    step = next(s for s in job['steps'] if s['name'] == 'Unit tests')
    command = step['run'].replace('${{ matrix.app }}', app)
    bash = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
    assert bash and Path(bash).is_file(), 'shell launcher regression requires bash'
    java = tmp_path / 'java home' / 'bin' / 'java'
    java.parent.mkdir(parents=True)
    probe = tmp_path / 'arguments.txt'
    java.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$GRADLE_PROBE"\n', encoding='utf-8', newline='\n')
    java.chmod(0o700)
    env = {**os.environ, 'GITHUB_WORKSPACE': ROOT.as_posix(),
           'JAVA_HOME': java.parent.parent.as_posix(), 'GRADLE_PROBE': probe.as_posix(),
           'JAVA_OPTS': '', 'GRADLE_OPTS': ''}
    subprocess.run([bash, '-n', '-c', command], env=env, check=True, timeout=10)
    subprocess.run([bash, '-c', command], cwd=ROOT / app, env=env, check=True, timeout=10)
    args = probe.read_text('utf-8').splitlines()
    wrapper_jar = Path(args[args.index('-classpath') + 1])
    assert wrapper_jar.samefile(ROOT / 'operations/ui/cam/gradle/wrapper/gradle-wrapper.jar')
    assert 'org.gradle.wrapper.GradleWrapperMain' in args
    selected = Path(args[args.index('--project-dir') + 1])
    assert selected.samefile(ROOT / app)
    assert 'testDebugUnitTest' in args and '--no-daemon' in args
    assert not any(a in args for a in ('--dry-run', '--exclude-task', '-x'))
