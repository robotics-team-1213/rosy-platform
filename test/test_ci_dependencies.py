"""Keep root contract tests reproducible in the ROS CI container."""

from pathlib import Path
import os
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


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
