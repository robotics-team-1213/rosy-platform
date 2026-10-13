"""Existing imports and monkeypatches share the extracted channel implementation."""

import importlib

import pytest


MODULES = ("requests", "workflow", "missions", "incidents", "replies", "gateway",
           "deliberation", "model_worker", "model_runtime")


@pytest.mark.parametrize("name", MODULES)
def test_legacy_channel_module_is_the_actual_owner(name, monkeypatch):
    owner = importlib.import_module("fleet.server.channel." + name)
    legacy = importlib.import_module("fleet.server.channel_" + name)
    assert legacy is owner
    assert "/server/channel/" in owner.__file__.replace("\\", "/")
    marker = object()
    monkeypatch.setattr(legacy, "_alias_probe", marker, raising=False)
    assert owner._alias_probe is marker


def test_gateway_http_client_patch_reaches_actual_worker(monkeypatch):
    legacy = importlib.import_module("fleet.server.channel_gateway")
    owner = importlib.import_module("fleet.server.channel.gateway")
    marker = object()
    monkeypatch.setattr(legacy.httpx, "AsyncClient", marker)
    assert owner.httpx.AsyncClient is marker
