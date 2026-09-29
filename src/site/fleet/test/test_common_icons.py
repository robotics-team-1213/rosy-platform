"""D-358 3항: the console favicon is served from the /common allowlist, nothing else in icons/."""

from pathlib import Path

from fastapi.testclient import TestClient

from fleet.server.app import create_app
from fleet.server.console import FleetConsole

WEB_COMMON = Path(__file__).resolve().parents[3] / "hmi" / "web_common"


def test_listed_icons_are_served_and_the_folder_is_not():
    client = TestClient(create_app(FleetConsole([], []), web_common=WEB_COMMON))
    icon = client.get("/common/icons/fleet-console.svg")
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/svg+xml")
    assert icon.content.startswith(b"<svg")
    for unlisted in ("/common/icons/", "/common/icons/unknown.svg",
                     "/common/icons/%2e%2e/manifest.json", "/common/surfaces.yaml"):
        assert client.get(unlisted).status_code == 404, unlisted
