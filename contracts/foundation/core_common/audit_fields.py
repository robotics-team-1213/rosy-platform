"""Credential field-name detection for records; traversal and rejection stay with owners."""
import re


_CREDENTIAL_FIELD = re.compile(
    r"(?:passwo?rd|passwd|psk|passphrase|secret|token|credential|authorization|"
    r"api[_-]?key|private[_-]?key|bearer)",
    re.IGNORECASE,
)


def is_credential_field(name: object) -> bool:
    """Match existing credential-name fragments, not sensitive values or whole payloads."""
    return bool(_CREDENTIAL_FIELD.search(str(name)))
