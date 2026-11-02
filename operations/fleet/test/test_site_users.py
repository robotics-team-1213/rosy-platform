from hashlib import sha256

import pytest

import yaml

from fleet.server.site_users import load_site_users


def test_site_users_load_principal_roles_by_sha256_token_digest(tmp_path):
    token = "distinct-user-token"
    config = tmp_path / "site-users.yaml"
    config.write_text(
        "users:\n"
        "  - principal_id: alice\n"
        "    role: viewer\n"
        f"    token_sha256: {sha256(token.encode()).hexdigest()}\n",
        encoding="utf-8",
    )

    users = load_site_users(config)

    assert users == {
        sha256(token.encode()).hexdigest(): {"principal_id": "alice", "role": "viewer"}
    }


def test_site_users_accept_service_role_for_non_operator_automation(tmp_path):
    token = "cell-service-token"
    config = tmp_path / "site-users.yaml"
    config.write_text(
        "users:\n"
        "  - principal_id: rosy-cell-service\n"
        "    role: service\n"
        f"    token_sha256: {sha256(token.encode()).hexdigest()}\n",
        encoding="utf-8",
    )

    users = load_site_users(config)

    assert users[sha256(token.encode()).hexdigest()] == {
        "principal_id": "rosy-cell-service", "role": "service",
    }


@pytest.mark.parametrize(
    "entry",
    [
        "principal_id: ''\n    role: viewer\n    token_sha256: " + "a" * 64,
        "principal_id: alice\n    role: admin\n    token_sha256: " + "a" * 64,
        "principal_id: alice\n    role: viewer\n    token_sha256: not-a-digest",
    ],
)
def test_site_users_reject_invalid_identity_role_or_token_digest(tmp_path, entry):
    config = tmp_path / "site-users.yaml"
    config.write_text(f"users:\n  - {entry.replace(chr(10), chr(10) + '    ')}\n",
                      encoding="utf-8")

    with pytest.raises(ValueError):
        load_site_users(config)


def test_site_users_retains_explicit_machine_viewer_marker(tmp_path):
    from types import SimpleNamespace
    from fleet.server.site_auth import parse_site_principals
    config = tmp_path / "site-users.yaml"
    entry = {"principal_id": "health-check", "role": "viewer", "machine": True,
             "token_sha256": sha256(b"health-check-credential").hexdigest()}
    config.write_text(yaml.safe_dump({"users": [entry]}), encoding="utf-8")
    assert load_site_users(config) == {
        entry["token_sha256"]: {"principal_id": "health-check", "role": "viewer", "machine": True}}
    def no_secret_overlap(_):
        return False
    console = SimpleNamespace(user_credential_overlaps_robot_secret=no_secret_overlap)
    marked = parse_site_principals(load_site_users(config), console)[entry["token_sha256"]]
    ordinary = parse_site_principals({entry["token_sha256"]: {
        "principal_id": "health-check", "role": "viewer"}}, console)[entry["token_sha256"]]
    assert marked == ordinary


@pytest.mark.parametrize("changes", [
    {"machine": False}, {"machine": "true"}, {"machine": 1}, {"machine": None},
    {"role": "operator"}, {"role": "policy-admin"}, {"role": "service"}, {"role": "ai_observer"},
    {"login": "health"}, {"password_scrypt": "unused"}, {"policy_admin": False}, {"policy_admin": True},
])
def test_site_users_rejects_machine_markers_outside_token_only_viewer(tmp_path, changes):
    config = tmp_path / "site-users.yaml"
    entry = {"principal_id": "health-check", "role": "viewer", "machine": True,
             "token_sha256": sha256(b"health-check-credential").hexdigest(), **changes}
    config.write_text(yaml.safe_dump({"users": [entry]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_site_users(config)
