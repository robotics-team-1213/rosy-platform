"""D-785: the console binds same-host OMX owners only through ROSY_FLEET_OMX_INSTANCES (compose.omx.yaml)."""

import pytest

from fleet import cli


def test_unset_keeps_omx_unconfigured(monkeypatch):
    monkeypatch.delenv("ROSY_FLEET_OMX_INSTANCES", raising=False)
    assert cli._omx_instances() == {}


def test_pairs_are_parsed_in_order(monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_OMX_INSTANCES", "omx_cell_a=omx_cell_a_01,omx_cell_b=omx_cell_b_01")
    assert cli._omx_instances() == {"omx_cell_a": "omx_cell_a_01", "omx_cell_b": "omx_cell_b_01"}


@pytest.mark.parametrize("value", [
    "omx_cell_a", "=omx_cell_a_01", "omx_cell_a=", " omx_cell_a=omx_cell_a_01", "a=b=c",
    "omx_cell_a=x,omx_cell_a=y",
])
def test_malformed_or_duplicate_pairs_stop_startup(monkeypatch, value):
    monkeypatch.setenv("ROSY_FLEET_OMX_INSTANCES", value)
    with pytest.raises(SystemExit):
        cli._omx_instances()
