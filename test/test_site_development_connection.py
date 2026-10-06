"""D-473 site wiring — development connection mode is off unless site.env sets both keys."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_site_compose_passes_both_development_settings_off_by_default():
    compose = _text("deploy/site/compose.yaml")

    assert '--connection-mode\n      - "${ROSY_FLEET_CONNECTION_MODE:-paired}"' in compose
    assert 'ROSY_DEPLOYMENT: "${ROSY_DEPLOYMENT:-}"' in compose


def test_site_env_example_leaves_development_mode_empty():
    env = _text("deploy/site/.env.example")

    assert "\nROSY_DEPLOYMENT=\n" in env
    assert "\nROSY_FLEET_CONNECTION_MODE=\n" in env


def test_site_readme_explains_how_to_turn_development_mode_on_and_its_risk():
    readme = _text("deploy/site/README.md")

    assert "## Development connection mode (D-473)" in readme
    assert "ROSY_DEPLOYMENT=development" in readme
    assert "ROSY_FLEET_CONNECTION_MODE=development" in readme
    assert "/api/fleet/auth/connection" in readme
    assert "trust" in readme
