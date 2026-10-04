"""CI must install the wheels it actually builds, with their local dependency closure."""

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_wheel_install_matches_project_versions_and_local_dependencies():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Build and install ROS-free platform API wheels", 1)[1]
    step = step.split("\n      - name:", 1)[0]
    built = {}
    for path in re.findall(r"(?:contracts|middleware|operations|integrations)/[A-Za-z0-9_/-]+", step):
        metadata = ROOT / path / "pyproject.toml"
        if metadata.exists():
            project = tomllib.loads(metadata.read_text(encoding="utf-8"))["project"]
            built[project["name"]] = project
    installed = dict(re.findall(r"(rosy-[A-Za-z0-9-]+)==([0-9.]+)", step))
    assert built, "CI must build real local wheels"
    assert set(installed) == set(built), "Every selected wheel must be installed, with no stale package"
    for name, project in built.items():
        assert installed[name] == project["version"], f"{name}: CI installs a stale local version"
        for dependency in project.get("dependencies", []):
            if not dependency.startswith("rosy-"):
                continue
            dep_name, dep_version = dependency.split("==", 1)
            assert installed.get(dep_name) == dep_version, f"{name}: missing local dependency {dependency}"
