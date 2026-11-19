import pytest


@pytest.mark.parametrize("field", [
    "password", "passwrd", "passwd", "wifi_psk", "passphrase", "client_secret",
    "access_TOKEN", "credential", "AUTHORIZATION", "api_key", "api-key", "apikey",
    "private_key", "private-key", "privatekey", "Bearer", "nested_password_hash",
])
def test_credential_field_names_are_recognized(field):
    from core_common.audit_fields import is_credential_field

    assert is_credential_field(field)


@pytest.mark.parametrize("field", ["owner", "actor_id", "revision", "outcome", "monkey", 42, None])
def test_noncredential_field_names_are_allowed(field):
    from core_common.audit_fields import is_credential_field

    assert not is_credential_field(field)
