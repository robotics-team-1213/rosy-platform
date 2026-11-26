"""Signed optional Compose overlays keep the site updater working."""
import json
from types import SimpleNamespace

import pytest

from deploy.site import rosy_site_autoupdate as upd
from deploy.site.site_update_io import WORLD_OVERLAY, active_services, allowed_overlays, companion_services
from deploy.site.site_update_runtime import containers_reason
from test_site_autoupdate import FakeHost, FakeHttp, NEW, _updater, _world, host  # noqa: F401 - host is a fixture


@pytest.mark.parametrize("overlay", [
    "-f /opt/rosy/candidate/deploy/site/compose.omx.yaml",
    "-f /opt/rosy/candidate/deploy/site/compose.pairing.yaml -f /opt/rosy/candidate/deploy/site/compose.omx.yaml",
    "-f /opt/rosy/candidate/deploy/site/compose.account.yaml",
    "-f /opt/rosy/candidate/deploy/site/compose.pairing.yaml -f /opt/rosy/candidate/deploy/site/compose.account.yaml",
    "-f /opt/rosy/candidate/deploy/site/compose.omx.yaml -f /opt/rosy/candidate/deploy/site/compose.account.yaml",
    "-f /opt/rosy/candidate/deploy/site/compose.pairing.yaml -f /opt/rosy/candidate/deploy/site/compose.omx.yaml -f /opt/rosy/candidate/deploy/site/compose.account.yaml",
    "-f /opt/rosy/candidate/deploy/site/compose.account.yaml -f /opt/rosy/candidate/deploy/site/compose.account-lan.yaml",  # D-1068
])
def test_omx_overlay_from_the_candidate_is_allowed(host, overlay):
    with host.paths.site_env.open("a", encoding="utf-8") as stream:
        stream.write(f"ROSY_SITE_PAIRING_COMPOSE={overlay}\n")
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    assert _updater(host, FakeHttp(releases, blobs), FakeHost(host.paths)).run() == upd.EXIT_OK


@pytest.mark.parametrize("pairing", [False, True])
@pytest.mark.parametrize("omx", [False, True])
@pytest.mark.parametrize("account", [False, True])
def test_signed_workcell_overlay_composes_with_existing_optional_overlays(host, pairing, omx, account):
    names = (["pairing"] if pairing else []) + (["omx"] if omx else []) + ["workcell"]
    names += ["account"] if account else []
    overlay = " ".join(f"-f /opt/rosy/candidate/deploy/site/compose.{name}.yaml" for name in names)
    with host.paths.site_env.open("a", encoding="utf-8") as stream:
        stream.write(f"ROSY_SITE_PAIRING_COMPOSE={overlay}\n")
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    assert _updater(host, FakeHttp(releases, blobs), FakeHost(host.paths)).run() == upd.EXIT_OK


@pytest.mark.parametrize("workcell", [False, True])
def test_signed_control_unit_overlay_keeps_automatic_updates(host, workcell):
    """D-960: with R's control-unit overlay from the signed candidate the updater still installs new candidates."""
    names = ["omx"] + (["workcell"] if workcell else []) + ["control-unit"]
    overlay = " ".join(f"-f /opt/rosy/candidate/deploy/site/compose.{name}.yaml" for name in names)
    with host.paths.site_env.open("a", encoding="utf-8") as stream:
        stream.write(f"ROSY_SITE_PAIRING_COMPOSE={overlay}\n")
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    assert _updater(host, FakeHttp(releases, blobs), FakeHost(host.paths)).run() == upd.EXIT_OK


def test_world_overlay_uses_one_signed_image_and_requires_bridge_health():
    services = (*upd.SERVICES, "world")
    assert active_services(services, []) == upd.SERVICES
    env = {"ROSY_SITE_PAIRING_COMPOSE": " ".join(WORLD_OVERLAY)}
    assert allowed_overlays(env) == WORLD_OVERLAY
    assert active_services(services, WORLD_OVERLAY) == services
    assert companion_services(WORLD_OVERLAY, upd.SERVICES, {}) == set()
    companions = companion_services(WORLD_OVERLAY, services, {})
    assert companions == {"world-real-bridge"}
    references = {role: f"rosy-site-{role}:{NEW}" for role in services}
    accepted = {role: [f"image:{role}"] for role in services}
    rows = [
        {"Service": service, "ID": f"image:{owner}", "Image": references[owner],
         "State": "running", "Health": "healthy"}
        for service, owner in [*((role, role) for role in services), ("world-real-bridge", "world")]
    ]

    def reason():
        return containers_reason(rows, NEW, accepted, lambda args: SimpleNamespace(stdout=args[-1]),
                                 services, references, companions=companions)

    assert reason() == ""
    rows[-1]["ID"] = "image:other"
    assert "world-real-bridge running image identity differs" in reason()
    rows[-1]["Health"] = "unhealthy"
    assert "world-real-bridge is running/unhealthy" in reason()
    del accepted["world"]
    assert reason() == "world signed image identity proof is incomplete"


@pytest.mark.parametrize("signed_pair", [False, True])
def test_signed_world_overlay_requires_both_deployment_assets_and_an_image(tmp_path, signed_pair):
    from deploy.site.site_update_io import Rejected
    from deploy.site.site_update_runtime import SiteRuntimeIO

    runtime = SiteRuntimeIO()
    runtime.config = {"key_id": "test", "public_key": "test"}
    runtime.runner = None
    runtime.verifier = lambda *_args, **_kw: {
        "source_commit": NEW, "verified_images": list(upd.SERVICES), "world": signed_pair,
    }
    env = {"ROSY_SITE_PAIRING_COMPOSE": " ".join(WORLD_OVERLAY)}
    message = "requires a signed world image" if signed_pair else "is not covered by this signed candidate"
    with pytest.raises(Rejected, match=message):
        runtime._verify(tmp_path / NEW, loaded=False, env=env)
