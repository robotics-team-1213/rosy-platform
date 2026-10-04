"""D-457 7: the console ships the overhead tracking layer, its status line and the apply button."""

from fastapi.testclient import TestClient

from fleet.server.app import create_app
from fleet.server.console import FleetConsole


def test_console_serves_the_tracking_layer_wired_into_the_map_and_shell():
    client = TestClient(create_app(FleetConsole([], [])))
    page = client.get("/console").text
    install_page = client.get("/console/install").text
    layer = client.get("/console/assets/tracking-layer.js")
    view = client.get("/console/assets/tracking-view.js")
    shell = client.get("/console/assets/console.js").text
    map_view = client.get("/console/assets/map-view.js").text
    fit_view = client.get("/console/assets/map-fit-view.js").text
    vision_view = client.get("/console/assets/vision-view.js").text

    assert layer.status_code == 200 and "classifyTracking" in layer.text
    assert view.status_code == 200
    assert '"/api/fleet/tracking"' in view.text and '"/api/fleet/tracking/relearn"' in view.text
    assert 'import { createTrackingView } from "./tracking-view.js";' in shell
    assert "trackingView.refresh()" in shell
    assert 'import { offsetLabel, preferMarkers } from "./tracking-layer.js";' in map_view
    assert 'layerOn("tracking")' in map_view
    assert '"/api/fleet/calibrations"' in fit_view and "calibrationRequest(" in fit_view
    assert "currentLensInfo: () => currentLensInfo" in vision_view
    for element_id in ("tracking-state", "tracking-relearn", "legend-tracking", "tracking-positions"):
        assert f'id="{element_id}"' in page
    assert 'id="map-fit-apply"' in install_page
    assert 'data-layer="tracking"' in install_page
    assert "<script>" not in page and 'style="' not in page


def test_tracking_assets_set_no_inline_style():
    """CSP style-src 'self': the new assets colour by class and canvas only, never el.style."""
    client = TestClient(create_app(FleetConsole([], [])))
    for name in ("tracking-layer.js", "tracking-view.js"):
        response = client.get(f"/console/assets/{name}")
        assert response.status_code == 200, name
        text = response.text
        assert ".style" not in text and "setAttribute(\"style\"" not in text, name
