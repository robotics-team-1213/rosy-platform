"""Installation profiles contain only built application and runtime owners."""

from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
for relative in ("apps/agent/src", "apps/gateway/src"):
    path = ROOT / relative
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from rosy_agent.omx_sim import load_profile  # noqa: E402
from rosy_gateway.compose import load_site_profile  # noqa: E402


def test_profile_wheels_match_the_built_application_packages():
    agent = load_profile(ROOT / "profiles/installations/omx_cell_sim.yaml")
    site = load_site_profile(ROOT / "profiles/installations/site_cell.yaml")
    agent_package = tomllib.loads((ROOT / "apps/agent/pyproject.toml").read_text())
    gateway_package = tomllib.loads((ROOT / "apps/gateway/pyproject.toml").read_text())
    assert agent_package["project"]["name"] in agent.wheels
    assert gateway_package["project"]["name"] in site.wheels


def test_minimal_runtime_dependencies_do_not_pull_pinky_learning_or_model_sdks():
    agent = tomllib.loads((ROOT / "apps/agent/pyproject.toml").read_text())
    gateway = tomllib.loads((ROOT / "apps/gateway/pyproject.toml").read_text())
    wheels = load_profile(ROOT / "profiles/installations/omx_cell_sim.yaml").wheels
    dependencies = agent["project"]["dependencies"] + gateway["project"]["dependencies"]
    forbidden = ("pinky", "torch", "lerobot", "model-sdk", "google-generativeai")
    assert not any(token in item.lower() for item in (*wheels, *dependencies) for token in forbidden)
