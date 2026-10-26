"""Read signed SDK compatibility declarations without executing candidate code."""
from __future__ import annotations

import ast
from pathlib import Path

from os_state_layout import COMMON, _layout, _object, _path, _read

BOOT_ABI = 1
AB_V1_FILES = (
    "native_release.py", "signing.py", "os_payload_compatibility.py",
    "os_state_storage.py", "os_state_firstboot.py", "os_state_layout.py", "os_state_io.py",
    "os_state_accounts.py", "os_state_files.py", "os_state_config.py", "os_state_ready.py",
    "os_state_tls.py", "os_factory_release.py", "os_storage_dispatch.py", "operator_keys.py",
    "auto_update_apply.py", "auto_update_records.py", "auto_update_host.py", "auto_update_stage.py",
    "rosy_auto_update.py", "rosy_claim.py", "image_layer_boot.py", "image_layer_files.py",
    "sync-image-layer.py", "image-layer-reconcile.py", "first_boot_runtime.py", "first_boot_support.py",
)
AB_V2_FILES = (*AB_V1_FILES, "os_update_state.py", "os_update_manifest.py", "media_layout.py")


def _mapping(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("unsupported compatibility fields")
    return value


def _integer(value):
    if type(value) is not int or not 1 <= value <= 2**31 - 1:
        raise ValueError("compatibility version is not a positive integer")
    return value


def verify_contract(native: Path, *, state_schema: int, boot_abi: int = BOOT_ABI) -> dict:
    """Parse metadata only; deployment callers first verify the whole candidate's signature."""
    from image_layer_boot import _engine_contract, _safe
    state_schema, boot_abi = _integer(state_schema), _integer(boot_abi)
    files, source = _engine_contract(native)
    declarations = [node.value for node in ast.parse(source).body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "OS_COMPATIBILITY" for t in node.targets)]
    if len(declarations) != 1:
        raise ValueError("a single signed OS compatibility declaration is required")
    value = _mapping(ast.literal_eval(declarations[0]), {"schema_version", "boot_abi", "state_schema"})
    if _integer(value["schema_version"]) != 1:
        raise ValueError("unsupported OS compatibility schema")
    abi = _mapping(value["boot_abi"], {"min", "max"})
    state = _mapping(value["state_schema"], {"read_min", "read_max", "write"})
    if not _integer(abi["min"]) <= boot_abi <= _integer(abi["max"]):
        raise ValueError("payload cannot preserve this OS boot ABI")
    if (not _integer(state["read_min"]) <= state_schema <= _integer(state["read_max"])
            or _integer(state["write"]) != state_schema):
        raise ValueError("payload cannot read and preserve the shared state schema")
    if not set(AB_V1_FILES) <= set(files):
        raise ValueError("payload SDK omits required A/B state owners")
    if boot_abi == 2 and not set(AB_V2_FILES) <= set(files):
        raise ValueError("payload SDK omits the persistent OS pending fence")
    for name in files:
        if not _safe(native, name).is_file():
            raise ValueError("declared SDK closure is incomplete")
    return value


def require_native_maintenance(root: Path) -> None:
    """Called under native release.lock; the OS controller creates pending under that same short lock."""
    admitted = _layout(root)
    if admitted is None or admitted[0]["schema_version"] != 2:
        return
    from os_update_state import read_state
    if read_state(root)["pending"] is not None:
        raise ValueError("OS_UPDATE_PENDING: native maintenance waits for the OS transaction")


def require_ab_payload(root: Path, release: Path) -> None:
    try:
        admitted = _layout(root)
        if admitted is None:
            return
        schema = _object(_read(_path(root, COMMON + "/state/schema.json"), 8192, root.stat().st_uid),
                         {"schema_version", "state_schema"})
        verify_contract(release / "deploy/robot/native", state_schema=schema["state_schema"],
                        boot_abi=admitted[0]["schema_version"])
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        raise ValueError(f"OS_PAYLOAD_INCOMPATIBLE: {exc}") from exc
