"""The site stack runs Fleet's calibration-drift watch against Vision by default.

Fleet reads Vision's existing D-375 map-proposal endpoint server-side
(`--vision-url`, 60 s cadence) so a re-aimed camera is caught with no robot in view.
The vision origin uses the internal compose network, the site leaf's ``vision`` SAN,
and the site CA the fleet container already trusts through ``SSL_CERT_FILE``.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "deploy" / "site"


def _fleet_service() -> str:
    compose = (SITE / "compose.yaml").read_text(encoding="utf-8")
    return compose.split("  fleet:\n", 1)[1].split("  vision:\n", 1)[0]


def test_fleet_watches_calibration_drift_against_the_vision_map_proposal():
    fleet = _fleet_service()
    assert "--vision-preview-secret-env\n      - ROSY_VISION_PREVIEW_SECRET" in fleet
    assert "--vision-url\n      - https://vision:${ROSY_VISION_PORT:?set ROSY_VISION_PORT}" in fleet
    # No explicit interval: the 60 s default (calibration drift stays on unless asked off).
    assert "--calibration-drift-interval-s" not in fleet


def test_the_drift_watch_flags_exist_on_the_console_command():
    import shlex

    from fleet.cli import parse_args

    args = parse_args(shlex.split(
        "console --vision-url https://vision:8095 --calibration-drift-interval-s 30"))
    assert args.vision_url == "https://vision:8095"
    assert args.calibration_drift_interval_s == 30.0
    default = parse_args(["console"])
    assert default.vision_url is None and default.calibration_drift_interval_s == 60.0
