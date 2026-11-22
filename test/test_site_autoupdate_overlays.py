"""D-441/D-960/D-1068: signed optional compose overlays keep the site updater working."""
import pytest

from deploy.site import rosy_site_autoupdate as upd
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
