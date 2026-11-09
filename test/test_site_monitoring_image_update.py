"""D-1001: Monitoring's own signed image is an optional inventory member beside the Fleet image."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/site"))
import site_update_io as io  # noqa: E402
import site_update_runtime as runtime  # noqa: E402
import verify_candidate as verify  # noqa: E402

TAG = "a" * 40
BASE = ("fleet", "vision", "proxy", "postgres")
OVERLAY = "-f /opt/rosy/candidate/deploy/site/compose.monitoring.yaml"


@pytest.mark.parametrize("base", [BASE[:3], BASE, (*BASE, "account")])
def test_verified_inventory_accepts_monitoring_only_once_beside_a_known_base(base):
    assert verify.verified_services(list(base)) == base
    assert verify.verified_services([*base, "monitoring"]) == (*base, "monitoring")
    assert verify.verified_services(["monitoring", *base]) == (*base, "monitoring")
    for bad in ([*base, "monitoring", "monitoring"], [*base, "other"], ["monitoring"]):
        with pytest.raises(verify.CandidateVerificationError):
            verify.verified_services(bad)


def _overrides(compose_images, inventory, overlays=OVERLAY):
    run = lambda args: SimpleNamespace(stdout="")  # noqa: E731
    compose = lambda *a, **k: SimpleNamespace(stdout=json.dumps({"services": {  # noqa: E731
        name: {"image": image} for name, image in compose_images.items()}}))
    references = {role: f"rosy-site-{role}:{TAG}" for role in inventory}
    io.check_overrides({"ROSY_SITE_PAIRING_COMPOSE": overlays}, TAG, run, compose, inventory, references)


def test_own_monitoring_image_is_required_when_the_signed_inventory_has_one():
    inventory = (*BASE, "monitoring")
    images = {role: f"rosy-site-{role}:{TAG}" for role in inventory}
    _overrides(images, inventory)
    _overrides({**images, "monitoring": f"rosy-site-fleet:{TAG}"}, inventory) if False else None
    with pytest.raises(io.Refused, match="Compose resolves monitoring"):
        _overrides({**images, "monitoring": f"rosy-site-fleet:{TAG}"}, inventory)
    with pytest.raises(io.Refused, match="service set differs"):  # overlay off: a running monitoring is not signed
        _overrides(images, inventory, overlays="")


def test_older_candidates_keep_monitoring_on_the_fleet_image():
    images = {role: f"rosy-site-{role}:{TAG}" for role in BASE} | {"monitoring": f"rosy-site-fleet:{TAG}"}
    _overrides(images, BASE)


@pytest.mark.parametrize("fault", [None, "fleet-image", "no-proof", "wrong-identity"])
def test_runtime_check_pins_monitoring_to_its_own_image_and_identity(fault):
    roles = (*BASE, "monitoring")
    references = {role: f"rosy-site-{role}:{TAG}" for role in roles}
    accepted = {role: [f"sha256:{role[0] * 64}"] for role in roles}
    accepted = {role: ["sha256:" + format(i, "x") * 64] for i, role in enumerate(roles)}
    rows = [{"Service": role, "Image": references[role], "State": "running", "Health": "healthy", "ID": role}
            for role in roles]
    if fault == "fleet-image":
        rows[-1]["Image"] = references["fleet"]
    if fault == "no-proof":
        accepted.pop("monitoring")

    def inspect(args):
        role = args[-1]
        wrong = fault == "wrong-identity" and role == "monitoring"
        return SimpleNamespace(stdout=accepted["fleet" if wrong else role][0])
    reason = runtime.containers_reason(rows, TAG, accepted, inspect, roles, references, companions=set())
    assert (reason == "") is (fault is None)
    if fault:
        assert "monitoring" in reason
