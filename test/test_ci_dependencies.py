"""Keep root contract tests reproducible in the ROS CI container."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


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
