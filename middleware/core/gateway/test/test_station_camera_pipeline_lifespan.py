"""Slow cases of test_station_camera_pipeline.py in their own file, so xdist (--dist loadfile) runs them on another
worker. The body is that file's test; only the parameters live here."""
import pytest

import test_station_camera_pipeline as pipeline
from test_station_camera_pipeline import pipeline_sources, station_api  # noqa: F401


@pytest.mark.parametrize('full_return', ['lifespan', 'shutdown_UNDOCKING'])
def test_station_camera_http_pipeline_aligns_then_requires_contact_and_measured_stop(station_api, tmp_path,
                                                                                   pipeline_sources, full_return, monkeypatch):
    pipeline.test_station_camera_http_pipeline_aligns_then_requires_contact_and_measured_stop(
        station_api, tmp_path, pipeline_sources, full_return, monkeypatch)
