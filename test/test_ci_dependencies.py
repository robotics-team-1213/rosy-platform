"""Keep root contract tests reproducible in the ROS CI container."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_installs_root_contract_python_dependencies():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "jsonschema" in workflow


def test_root_contract_step_sources_the_colcon_install():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("- name: Test (deployment and release contracts)", 1)[1]
    step = step.split("- name:", 1)[0]
    assert ". /opt/ros/jazzy/setup.sh" in step
    assert ". src/install/setup.sh" in step


def test_ci_installs_the_ext4_reader_for_the_card_diagnostics_test():
    # Without it test_card_diagnostics.py skips its real-ext4 case (D-174 F8).
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "jsonschema ext4" in workflow
