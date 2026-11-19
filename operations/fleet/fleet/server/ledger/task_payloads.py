"""Finite, bounded, credential-free payload encoding for Fleet task records."""
import json
from collections.abc import Mapping

from core_common.audit_fields import is_credential_field


def safe_json(value: object) -> str:
    def inspect(child: object) -> None:
        if isinstance(child, Mapping):
            for key, nested in child.items():
                if is_credential_field(key):
                    raise ValueError("task records cannot contain credential fields")
                inspect(nested)
        elif isinstance(child, (list, tuple)):
            for nested in child:
                inspect(nested)

    inspect(value)
    try:
        text = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False, sort_keys=True
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("task data must be finite JSON") from exc
    if len(text.encode("utf-8")) > 64 * 1024:
        raise ValueError("task data exceeds the 64 KiB limit")
    return text
