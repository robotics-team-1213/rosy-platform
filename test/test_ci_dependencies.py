"""Keep root contract tests reproducible in the ROS CI container."""

from pathlib import Path
import os
import shutil
import shlex
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.mark.parametrize('target', [
    'applications/fleet/test',
    'applications/fleet/test/test_sample_browser.py',
    'applications/fleet/test/test_sample_browser.py::test_sample_login',
])
def test_ci_activates_standalone_app_browsers(monkeypatch, target):
    import json
    import yaml
    from types import SimpleNamespace

    steps = yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))['jobs']['test']['steps']
    install = next(step for step in steps if step['name'] == 'Install Fleet browser verification tools')
    # Evaluate the condition with the same serialized invocation payload used by Actions.
    condition = install['if'].replace('toJSON(matrix.invocations)', 'payload').replace('||', 'or')
    assert eval(condition, {'__builtins__': {}, 'contains': lambda value, part: part in value,
                            'payload': json.dumps([[target]])})
    script = next(step['run'] for step in steps if step['name'] == 'Test (matrix suite, D-436)')
    python = script.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    calls = []
    monkeypatch.setenv('ROSY_INVOCATIONS', json.dumps([['middleware/core/gateway/test', target]]))
    monkeypatch.delenv('ROSY_RUN_BROWSER_TESTS', raising=False)
    monkeypatch.delenv('ROSY_BROWSER_TESTS', raising=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda args, **kwargs:
                        calls.append((args, kwargs['env'])) or SimpleNamespace(stdout=iter(()), wait=lambda: 0))
    with pytest.raises(SystemExit) as ended:
        exec(compile(python, str(WORKFLOW), 'exec'), {})
    assert ended.value.code == 0
    assert len(calls) == 2
    assert 'ROSY_RUN_BROWSER_TESTS' not in calls[0][1]
    assert target in calls[1][0]
    assert calls[1][1]['ROSY_RUN_BROWSER_TESTS'] == '1'


@pytest.mark.parametrize("selection", [
    ["middleware/devices/omx/adapter/test"],
    ["middleware/devices/omx/adapter/test/test_omx_ros_runtime.py::test_feedback_source_stamp_cannot_be_replayed_as_a_fresh_owner_state"],
    ["middleware/devices/omx/adapter/test/test_omx_fleet_ros_actionserver.py"],
])
def test_native_omx_ros_selection_runs_in_isolated_processes(monkeypatch, selection):
    import json
    import yaml
    from types import SimpleNamespace

    runtime = "middleware/devices/omx/adapter/test/test_omx_ros_runtime.py"
    fleet = "middleware/devices/omx/adapter/test/test_omx_fleet_ros_actionserver.py"
    step = next(s for s in yaml.safe_load(WORKFLOW.read_text(encoding="utf8"))["jobs"]["test"]["steps"]
                if s["name"] == "Test (matrix suite, D-436)")
    script = step["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    calls = []
    monkeypatch.setenv("ROSY_INVOCATIONS", json.dumps([selection]))
    monkeypatch.setenv("ROS_DISCOVERY_SERVER", "inherited-server-must-not-leak")
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs:
                        calls.append((args, kwargs["env"])) or
                        SimpleNamespace(stdout=iter(()), wait=lambda: 0))
    with pytest.raises(SystemExit) as ended:
        exec(compile(script, str(WORKFLOW), "exec"), {})
    assert ended.value.code == 0
    expected = [runtime, fleet] if selection[0].endswith("/test") else selection
    for target in expected:
        isolated = [(args, env) for args, env in calls if args[3] == target]
        assert len(isolated) == 1, calls
        args, env = isolated[0]
        assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert env["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"
        assert env["RMW_IMPLEMENTATION"] == "rmw_fastrtps_cpp"
        assert "ROS_DISCOVERY_SERVER" not in env
    if selection[0].endswith("/test"):
        residual = next(args for args, _ in calls if args[3] == selection[0])
        assert all("--ignore=" + target in residual for target in expected)
        assert len({env["ROS_DOMAIN_ID"] for args, env in calls if args[3] in expected}) == 2


@pytest.mark.parametrize("code,output", [(0, "1 skipped"), (5, "no tests ran"), (1, "1 failed")])
def test_native_omx_ros_skips_empty_collection_and_failures_block_ci(monkeypatch, code, output):
    import json
    import yaml
    from types import SimpleNamespace

    target = "middleware/devices/omx/adapter/test/test_omx_ros_runtime.py"
    step = next(s for s in yaml.safe_load(WORKFLOW.read_text(encoding="utf8"))["jobs"]["test"]["steps"]
                if s["name"] == "Test (matrix suite, D-436)")
    script = step["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    monkeypatch.setenv("ROSY_INVOCATIONS", json.dumps([[target]]))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs:
                        SimpleNamespace(stdout=iter([output]), wait=lambda: code))
    with pytest.raises(SystemExit) as ended:
        exec(compile(script, str(WORKFLOW), "exec"), {})
    assert ended.value.code == 1


def test_ci_local_execution_wheel_pin_matches_package_metadata():
    project = tomllib.loads((ROOT / 'middleware/robot_execution/local/pyproject.toml').read_text(encoding='utf8'))
    assert f"{project['project']['name']}=={project['project']['version']}" in WORKFLOW.read_text(encoding='utf8')


def test_actual_act_cpu_has_a_gating_runner_and_its_own_pinned_tools():
    import yaml
    from tools.harness.affected_tests import CI_FULL_MATRIX, Repo, Selection, ci_matrix

    entries = [e for e in CI_FULL_MATRIX if e['name'] == 'omx-act-cpu']
    assert len(entries) == 1, 'actual ACT must not depend on optional imports in learning-policy'
    full = ci_matrix(Repo.load(ROOT), Selection('full', []))['include']
    native = [e for e in full if e['name'] == 'omx-act-cpu']
    assert len(native) == 1 and native[0]['gating'] and native[0]['ros'] == 'none'
    assert {'learning/training/omx/test/test_act_inference_native.py',
            'learning/training/omx/test/test_act_owner_capture.py',
            'learning/training/omx/test/test_act_parent_chain.py'} <= {
                path for invocation in entries[0]['invocations'] for path in invocation}
    steps = yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))['jobs']['test']['steps']
    step = next(s for s in steps if s['name'] == 'Install OMX ACT CPU verification tools')
    assert step['if'] == "matrix.name == 'omx-act-cpu'"
    assert 'deploy/robot/omx/requirements-lerobot-export.txt' in step['run']
    assert '--target /tmp/rosy-omx-act-cpu' in step['run']
    assert 'https://download.pytorch.org/whl/cpu' in step['run']
    assert 'ROSY_ACT_CPU_REQUIRED=1' in step['run'] and 'HF_HUB_OFFLINE=1' in step['run']


@pytest.mark.parametrize('code,output,expected', [
    (0, '1 skipped', 1), (5, 'no tests ran', 1), (1, '1 failed', 1), (0, '6 passed', 0),
    (1, '1 failed, 1 skipped; quarantined', 1),
])
def test_actual_act_cpu_skips_and_empty_collection_cannot_pass(monkeypatch, code, output, expected):
    import json
    import yaml
    from types import SimpleNamespace

    step = next(s for s in yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))['jobs']['test']['steps']
                if s['name'] == 'Test (matrix suite, D-436)')
    script = step['run'].split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    monkeypatch.setenv('ROSY_INVOCATIONS', json.dumps([
        ['learning/training/omx/test/test_act_inference_native.py']]))
    monkeypatch.setenv('ROSY_ACT_CPU_REQUIRED', '1')
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs:
                        SimpleNamespace(stdout=iter([output]), wait=lambda: code))
    if 'quarantined' in output:
        monkeypatch.syspath_prepend(str(ROOT / 'test'))
        import known_failures
        monkeypatch.setattr(known_failures, 'should_rerun', lambda *args: True)
        monkeypatch.setattr(known_failures, 'rerun_passed', lambda *args: True)
        monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs:
                            SimpleNamespace(stdout='1 passed', returncode=0))
    with pytest.raises(SystemExit) as ended:
        exec(compile(script, str(WORKFLOW), 'exec'), {})
    assert ended.value.code == expected


def test_core_wheel_dependencies_are_available_before_offline_install():
    import ast
    import re
    import yaml
    from packaging.requirements import Requirement

    tree = ast.parse((ROOT / 'contracts/foundation/setup.py').read_text(encoding='utf8'))
    requirements = next(ast.literal_eval(keyword.value) for node in ast.walk(tree)
                        if isinstance(node, ast.Call) for keyword in node.keywords
                        if keyword.arg == 'install_requires')
    steps = yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))['jobs']['test']['steps']
    wheel_index = next(i for i, step in enumerate(steps)
                       if step['name'] == 'Build and install ROS-free platform API wheels')
    commands = '\n'.join(step.get('run', '') for step in steps[:wheel_index] if not step.get('if'))
    tokens = shlex.split(commands.replace('\\\n', ' '), comments=True)
    providers = dict(re.findall(r'^([A-Za-z0-9._-]+)==([^\s\\]+)',
                               (ROOT / 'deploy/robot/pinky_pro/image/device-python-requirements.txt')
                               .read_text(), re.MULTILINE))
    providers.update(token.split('==', 1) for token in tokens
                     if re.fullmatch(r'[A-Za-z0-9._-]+==[0-9.]+', token))
    for value in requirements:
        requirement = Requirement(value)
        if requirement.name == 'setuptools':  # ROS/colcon's apt build bootstrap.
            continue
        assert requirement.name in providers, f'CI offline wheel install lacks {value}'
        assert providers[requirement.name] in requirement.specifier


def test_ci_provides_the_site_account_oauth_runtime():
    import re
    import yaml

    site_requirements = (ROOT / 'deploy/site/requirements-fleet.txt').read_text(encoding='utf8')
    oauth_pin = re.search(r'^oauthlib==[^\s]+', site_requirements, re.MULTILINE).group()
    steps = yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))['jobs']['test']['steps']
    test_index = next(i for i, step in enumerate(steps) if step['name'] == 'Test (matrix suite, D-436)')
    tokens = shlex.split('\n'.join(step.get('run', '') for step in steps[:test_index]
                                  if not step.get('if')).replace('\\\n', ' '), comments=True)
    assert oauth_pin in tokens, f'CI account authority lacks site runtime {oauth_pin}'


def test_fleet_account_oauth_pin_matches_site_runtime():
    import ast
    import re

    site = (ROOT / 'deploy/site/requirements-fleet.txt').read_text(encoding='utf8')
    pin = re.search(r'^oauthlib==[^\s]+', site, re.MULTILINE).group()
    tree = ast.parse((ROOT / 'operations/fleet/setup.py').read_text(encoding='utf8'))
    requirements = next(ast.literal_eval(keyword.value) for node in ast.walk(tree)
                        if isinstance(node, ast.Call) for keyword in node.keywords
                        if keyword.arg == 'install_requires')
    assert pin in requirements, 'Fleet wheel and site account runtime must agree'


def test_ci_runs_the_account_browser_without_enabling_other_core_browsers(monkeypatch):
    import json
    import yaml
    from types import SimpleNamespace
    from tools.harness.affected_tests import CI_FULL_MATRIX

    browser_node = 'middleware/core/gateway/test/test_account_pipeline.py'
    core = next(entry for entry in CI_FULL_MATRIX if entry['name'] == 'core-domain')
    assert [browser_node] in core['invocations'], 'SSO browser journey must not remain opt-in-only'
    steps = yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))['jobs']['test']['steps']
    install = next(step for step in steps if step['name'] == 'Install Fleet browser verification tools')
    assert 'test_account_pipeline.py' in install['if']
    script = next(step['run'] for step in steps if step['name'] == 'Test (matrix suite, D-436)')
    python = script.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    calls = []
    monkeypatch.setenv('ROSY_INVOCATIONS', json.dumps([['middleware/core/gateway/test'], [browser_node]]))
    monkeypatch.delenv('ROSY_RUN_BROWSER_TESTS', raising=False)
    # The matrix step streams each pytest through Popen (D-762 stage 1); a green run prints nothing here.
    monkeypatch.setattr(subprocess, 'Popen', lambda args, **kwargs:
                        calls.append((args, kwargs['env'])) or SimpleNamespace(stdout=iter(()), wait=lambda: 0))
    with pytest.raises(SystemExit) as ended:
        exec(compile(python, str(WORKFLOW), 'exec'), {})
    assert ended.value.code == 0
    assert len(calls) == 2
    assert 'ROSY_RUN_BROWSER_TESTS' not in calls[0][1]
    assert browser_node in calls[1][0]
    assert calls[1][1]['ROSY_RUN_BROWSER_TESTS'] == '1'


@pytest.mark.parametrize('paths, expected', [
    (['test/test_a.py', 'test/test_b.py'], 1),  # root-test-*of3 since 2026-10-11: whole session skipped
    (['test/test_only_skips.py'], 0),  # one selected module that only skips is not a failure
])
def test_ci_fails_a_session_that_collected_nothing(monkeypatch, capsys, paths, expected):
    import json
    import yaml
    from types import SimpleNamespace

    steps = yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))['jobs']['test']['steps']
    script = next(step['run'] for step in steps if step['name'] == 'Test (matrix suite, D-436)')
    python = script.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    calls = []
    out = ['collecting ... collected 0 items / 1 skipped\n', '========== 1 skipped in 0.54s ==========\n']
    monkeypatch.setenv('ROSY_INVOCATIONS', json.dumps([paths]))
    monkeypatch.setattr(subprocess, 'Popen', lambda args, **kwargs:
                        calls.append(args) or SimpleNamespace(stdout=iter(out), wait=lambda: 0))
    with pytest.raises(SystemExit) as ended:
        exec(compile(python, str(WORKFLOW), 'exec'), {})
    assert ended.value.code == expected
    assert ('collected 0 items' in capsys.readouterr().out.split('::endgroup::')[-1]) == bool(expected)
    # The launch_testing hook is what turns one importorskip into a skipped session.
    assert calls[0][-2:] == ['-pno:launch_testing', '-pno:launch_ros']


def test_no_test_module_defines_a_nose_style_setup_function():
    # CI's apt pytest 7.4 calls a module-level plain setup()/teardown() once with the module as
    # its argument (nose compatibility), so a helper by that name gets the module as tmp_path.
    import ast

    found = []
    for path in ROOT.rglob('test_*.py'):
        if any(part in {'.git', '.worktrees', 'build', 'install', 'log', 'node_modules'} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding='utf8'))
        found += [f'{path.relative_to(ROOT).as_posix()}:{node.lineno}' for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name in {'setup', 'teardown'}
                  and not node.decorator_list]
    assert found == [], 'rename these helpers (e.g. _setup): ' + ', '.join(found)


def test_ci_builds_and_pins_the_internal_wheel_dependency_closure():
    import yaml
    steps = yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))['jobs']['test']['steps']
    script = next(step['run'] for step in steps if step['name'] == 'Build and install ROS-free platform API wheels')
    build, install = script.split('pip3 wheel', 1)[1].split('pip3 install', 1)
    projects = [tomllib.loads((ROOT / token / 'pyproject.toml').read_text(encoding='utf8'))['project']
                for token in shlex.split(build) if (ROOT / token / 'pyproject.toml').is_file()]
    assert len(projects) >= 11
    pins = {f"{project['name']}=={project['version']}" for project in projects}
    for project in projects:
        assert f"{project['name']}=={project['version']}" in install
        for requirement in project.get('dependencies', []):
            if requirement.startswith('rosy-'):
                assert requirement in pins, f"{project['name']} requires an unbuilt wheel: {requirement}"


@pytest.mark.parametrize("build_exit", [0, 42])
@pytest.mark.parametrize("preexisting", [False, True])
def test_colcon_ignore_is_scoped_to_the_build(tmp_path, build_exit, preexisting):
    """Source metadata remains visible after either successful or failed builds."""
    import yaml

    bash = (Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/missing-bash"))
    if not bash.is_file():
        pytest.skip("Bash is required for the real CI shell-step fixture")
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    script = next(step["run"] for step in jobs["test"]["steps"] if step["name"] == "Build (colcon)")
    script = script.replace(". /opt/ros/jazzy/setup.sh", ":")
    marker = tmp_path / "integrations/simulation/gazebo/COLCON_IGNORE"
    marker.parent.mkdir(parents=True)
    if preexisting:
        marker.write_text("preexisting\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "python3": "printf '%s\\n' integrations\n",
        "colcon": "test -f integrations/simulation/gazebo/COLCON_IGNORE || exit 91\n"
                  "printf '%s\\n' ignored > build-trace\n" + f"exit {build_exit}\n",
    }.items():
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    environment = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
    result = subprocess.run([str(bash), "-e", "-c", script], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == build_exit, result.stderr
    assert (tmp_path / "build-trace").read_text().strip() == "ignored"
    if preexisting:
        assert marker.read_text() == "preexisting\n"
    else:
        assert not marker.exists(), "CI-generated ignore hid the source package from later guards"


def test_ci_installs_root_contract_python_dependencies():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "jsonschema" in workflow


def test_root_contract_step_sources_the_colcon_install():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # D-436: the root contract suites run as `root-test-*` matrix entries with `ros: overlay`
    # (test/test_affected_tests.py pins that); this step is where the overlay is sourced.
    step = workflow.split("- name: Test (matrix suite, D-436)", 1)[1]
    step = step.split("- name:", 1)[0]
    assert ". /opt/ros/jazzy/setup.sh" in step
    # D-427: colcon builds from the repo root, so the overlay is install/, not src/install/.
    assert ". install/setup.sh" in step
    assert "src/install" not in workflow


def test_ci_colcon_build_runs_from_the_repo_root_over_the_manifest_roots():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("- name: Build (colcon)", 1)[1].split("- name:", 1)[0]
    assert "cd src" not in workflow
    assert 'COLCON_ROOTS="$(python3 tools/harness/colcon_roots.py)"' in step
    assert "--base-paths $COLCON_ROOTS" in step
    assert "colcon --log-base log build" in step  # --log-base is a global colcon option
    assert "--build-base build --install-base install" in step


def test_ci_installs_the_ext4_reader_for_the_card_diagnostics_test():
    # Without it test_card_diagnostics.py skips its real-ext4 case (D-174 F8).
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "jsonschema ext4" in workflow


def test_ci_result_aggregates_the_matrix_for_branch_protection():
    """D-436: a stable `ci-result` check fails unless scope and every gating entry passed."""
    import yaml

    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    result = jobs["ci-result"]
    assert result["name"] == "ci-result"
    assert set(result["needs"]) == {"scope", "test"}
    assert result["if"] == "always()", "must run (and fail) when a needed job fails or is cancelled"
    script = result["steps"][-1]["run"]
    assert 'test "$SCOPE_RESULT" = success' in script and 'test "$TEST_RESULT" = success' in script


def test_offline_wheel_install_matches_built_metadata_and_internal_dependencies():
    import re
    import tomllib
    import yaml

    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test"]["steps"]
    script = next(s["run"] for s in steps if s["name"] == "Build and install ROS-free platform API wheels")
    built = {}
    for path in re.findall(r"[a-z][a-z_/-]+/[a-z][a-z_/-]+", script):
        metadata = ROOT / path / "pyproject.toml"
        if metadata.is_file():
            project = tomllib.loads(metadata.read_text(encoding="utf-8"))["project"]
            built[project["name"]] = project
    installed = dict(re.findall(r"(rosy-[a-z-]+)==([0-9.]+)", script))
    assert built, "CI must build real source wheels"
    assert installed == {name: p["version"] for name, p in built.items()}
    for project in built.values():
        for dependency in project.get("dependencies", []):
            if dependency.startswith("rosy-"):
                name, version = dependency.split("==")
                assert installed.get(name) == version, f"offline wheelhouse missing {dependency}"


def test_raw_numpy_tools_are_isolated_from_debian_and_keep_runtime_constraints():
    import shlex
    import yaml

    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test"]["steps"]
    script = next(s["run"] for s in steps if s["name"] == "Install Pinky raw verification tools")
    commands = [shlex.split(line) for line in script.replace("\\\n", " ").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    requirements = next(args for args in commands if "-r" in args)
    target = requirements[requirements.index("--target") + 1]
    assert target.startswith("/tmp/")
    assert "-c" in requirements, "retain runtime constraints for raw tools"
    assert 'PYTHONPATH='+target+'${PYTHONPATH:+:$PYTHONPATH}' in script
    assert "numpy==2.2.6" in (ROOT / "learning/curation/pinky/requirements-raw.txt").read_text()


def test_ci_loads_hashlocked_receiver_crypto_before_tls_contracts():
    import yaml

    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test"]["steps"]
    step = next((s for s in steps if s["name"] == "Install receiver TLS verification runtime"), None)
    assert step is not None, "TLS contracts cannot use the older container cryptography"
    script = step["run"]
    assert "receiver-crypto-requirements.txt" in script
    assert "--require-hashes --no-deps --only-binary=:all:" in script
    assert "--platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64" in script
    assert "--target /tmp/rosy-receiver-crypto" in script
    assert 'echo "PYTHONPATH=/tmp/rosy-receiver-crypto${PYTHONPATH:+:$PYTHONPATH}"' in script
    assert "from cryptography.x509.verification import PolicyBuilder, Store" in script
    assert 'cryptography.__version__ == "50.0.0"' in script
    assert steps.index(step) < next(i for i, s in enumerate(steps) if s["name"] == "Test (matrix suite, D-436)")


def test_every_ci_job_has_a_timeout_below_the_six_hour_default():
    """A lost runner held run 38588670328 for 45 min; without a bound it can hold a run for 6 h."""
    import yaml

    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    for name, job in jobs.items():
        assert 0 < int(job.get("timeout-minutes", 0)) <= 30, name


def test_merge_group_runs_the_full_tier_against_the_group_base():
    """D-762 stage 1: a merge queue group is a full-tier event and checks its own base..head."""
    import yaml

    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True))  # PyYAML reads the bare key `on` as True
    assert "merge_group" in triggers
    assert "concurrency" not in doc, "a concurrency group could cancel a queue or main push run"
    scope = {s["name"]: s for s in doc["jobs"]["scope"]["steps"]}
    safety = scope["Safety-Review trailer (D-430)"]
    assert "github.event_name == 'merge_group'" in safety["if"]
    assert "github.event_name == 'merge_group' && github.event.merge_group.base_sha" in safety["env"]["SAFETY_BASE"]
    tier = scope["Test scope (D-436)"]["run"]
    # Only pull_request takes the affected tier; every other event (merge_group included) is full.
    assert '"${{ github.event_name }}" = "pull_request"' in tier and "--full --ci-matrix" in tier
    assert "merge_group" not in tier
    test = {s["name"]: s for s in doc["jobs"]["test"]["steps"]}["Test (matrix suite, D-436)"]
    assert "github.event.merge_group.base_sha" in test["env"]["HARNESS_BASE_REF"]
    assert "known_failures.should_rerun" in test["run"] and "known_failures.rerun_passed" in test["run"]
