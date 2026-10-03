"""Installed application composition boundaries remain declarative and injectable."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for relative in (
    "apps/agent/src",
    "operations/apps/fleet/src",
):
    path = ROOT / relative
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from rosy_agent.omx_sim import compose, load_profile  # noqa: E402
from rosy_gateway.compose import compose_site, load_site_profile  # noqa: E402
from fleet import cli as fleet_cli  # noqa: E402


def test_omx_sim_profile_selects_only_registered_provider_and_fake_lifecycle():
    profile = load_profile(ROOT / "profiles/installations/omx_cell_sim.yaml")
    calls = []
    lifecycle = object()
    result = compose(profile, {
        "omx.cell-transfer.sim.v1": lambda selected: calls.append(selected) or lifecycle,
    })
    assert result is lifecycle
    assert calls == [profile]
    assert profile.hardware_dispatch_enabled is False


def test_omx_sim_profile_rejects_arbitrary_provider_and_executable_fields(tmp_path):
    source = ROOT / "profiles/installations/omx_cell_sim.yaml"
    document = source.read_text(encoding="utf-8")
    bad_provider = tmp_path / "provider.yaml"
    bad_provider.write_text(document.replace(
        "omx.cell-transfer.sim.v1", "python:os.system",
    ), encoding="utf-8")
    with pytest.raises(ValueError, match="provider"):
        load_profile(bad_provider)
    script = tmp_path / "script.yaml"
    script.write_text(document + "\nstartup_script: /tmp/run-anything.sh\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        load_profile(script)


def test_site_cell_profile_composes_existing_fleet_server_without_new_runtime():
    profile = load_site_profile(ROOT / "profiles/installations/site_cell.yaml")
    sentinel = object()
    assert compose_site(profile, lambda selected: sentinel if selected is profile else None) is sentinel


def test_existing_fleet_cli_delegates_through_gateway_composition(monkeypatch):
    calls = []
    monkeypatch.setattr(fleet_cli, "_main_impl", lambda argv=None: calls.append(argv) or 7)
    assert fleet_cli.main(["console"]) == 7
    assert calls == [["console"]]


def test_installation_profiles_exclude_learning_and_pinky_runtime_dependencies():
    sim = load_profile(ROOT / "profiles/installations/omx_cell_sim.yaml")
    site = load_site_profile(ROOT / "profiles/installations/site_cell.yaml")
    all_wheels = set(sim.wheels) | set(site.wheels)
    assert not any(token in wheel.lower() for wheel in all_wheels
                   for token in ("pinky", "torch", "lerobot", "model-sdk"))
