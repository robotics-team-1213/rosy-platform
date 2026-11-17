"""D-977 2: cell Fleet startup settings for device_trial ARM transfer; every refusal happens before serving."""
import json

import pytest

from fleet import arm_transfer_config as cfg
from test_device_trial_arm_transfer import one_arm, TOKEN  # noqa: F401
from test_physical_transfer_evidence import geometry, policy  # noqa: F401  (fixtures)
from test_physical_transfer_store import installation  # noqa: F401


class FakeTransport:
    capabilities = ()

    def __init__(self, root):
        pass

    def transfer_capability(self, instance_id, *, workcell_id):
        return next(c for c in self.capabilities if (c.workcell_id, c.instance_id) == (workcell_id, instance_id))


@pytest.fixture
def owner(monkeypatch, installation):
    one = one_arm(installation)
    monkeypatch.setattr("fleet.server.local_action_transport.UnixLocalActionTransport",
                        type("T", (FakeTransport,), {"capabilities": one.capabilities}))
    return one


def write(tmp_path, installed):
    path = tmp_path / "installation.json"
    path.write_text(json.dumps({"policy": installed.policy.model_dump(mode="json"),
                                "policy_digest": installed.policy.digest}), encoding="utf-8")
    return {cfg.INSTALLATION_ENV: str(path)}


def test_profile_is_closed_to_two_values():
    assert cfg.deployment_profile({}) == "production"
    assert cfg.deployment_profile({cfg.PROFILE_ENV: "device_trial"}) == "device_trial"
    for bad in ("simulation", "", "Production", "device_trial "):
        with pytest.raises(SystemExit):
            cfg.deployment_profile({cfg.PROFILE_ENV: bad})


def test_grant_revisions():
    assert cfg.grant_revisions({}) is None
    ok = {"arm-a": {"capability_revision": "c", "config_revision": "k", "commissioning_revision": "m"}}
    assert cfg.grant_revisions({cfg.GRANTS_ENV: json.dumps(ok)}) == ok
    for bad in ("[]", "{", '{"a":{}}', '{"a":{"other":"x"}}', '{"a":{"config_revision":1}}'):
        with pytest.raises(SystemExit):
            cfg.grant_revisions({cfg.GRANTS_ENV: bad})


def test_loader_installs_one_arm_from_the_owner_capability(tmp_path, owner):
    installed = cfg.load_installation("device_trial", tmp_path, write(tmp_path, owner))
    assert installed.policy.digest == owner.policy.digest
    assert cfg.load_installation("production", tmp_path, {}) is None


def test_loader_refuses_outside_device_trial(tmp_path, owner):
    with pytest.raises(SystemExit, match="device_trial"):
        cfg.load_installation("production", tmp_path, write(tmp_path, owner))


def test_loader_refuses_two_arms(tmp_path, installation, monkeypatch):
    assert len(installation.policy.participants) > 1
    with pytest.raises(SystemExit, match="exactly one"):
        cfg.load_installation("device_trial", tmp_path, write(tmp_path, installation))


def test_loader_refuses_missing_file_and_digest_mismatch(tmp_path, owner):
    with pytest.raises(SystemExit, match="cannot install"):
        cfg.load_installation("device_trial", tmp_path, {cfg.INSTALLATION_ENV: str(tmp_path / "none.json")})
    env = write(tmp_path, owner)
    path = tmp_path / "installation.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "policy_digest": "f" * 64}))
    with pytest.raises(SystemExit, match="digest"):
        cfg.load_installation("device_trial", tmp_path, env)


def test_loader_refuses_an_owner_reporting_another_policy_digest(tmp_path, owner, monkeypatch):
    stale = tuple(c.model_copy(update=dict(resource_policy_digest="e" * 64)) for c in owner.capabilities)
    monkeypatch.setattr("fleet.server.local_action_transport.UnixLocalActionTransport",
                        type("T", (FakeTransport,), {"capabilities": stale}))
    with pytest.raises(SystemExit, match="do not match"):
        cfg.load_installation("device_trial", tmp_path, write(tmp_path, owner))


def test_observer_absent_without_token_and_bound_to_the_policy_producer(owner):
    assert cfg.load_observer(owner, {}) is None
    observer = cfg.load_observer(owner, {cfg.OBSERVER_TOKEN_ENV: TOKEN,
                                         cfg.OBSERVER_VALID_UNTIL_ENV: "2035-01-01T00:00:00+00:00"})
    assert observer.producer_id == owner.policy.producer_id


@pytest.mark.parametrize("until", [None, "2035-01-01T00:00:00", "soon"])
def test_observer_refuses_missing_or_naive_expiry(owner, until):
    env = {cfg.OBSERVER_TOKEN_ENV: TOKEN, **({} if until is None else {cfg.OBSERVER_VALID_UNTIL_ENV: until})}
    with pytest.raises(SystemExit):
        cfg.load_observer(owner, env)


def test_observer_token_without_installation_is_refused():
    with pytest.raises(SystemExit):
        cfg.load_observer(None, {cfg.OBSERVER_TOKEN_ENV: TOKEN})
