from hashlib import sha256

import pytest

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
