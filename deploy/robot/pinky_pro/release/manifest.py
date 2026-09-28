"""Validate a ROSY release manifest before anything is installed.

Both artifacts in the release contract — the SD image and the release bundle —
carry this manifest. A device reads it first and decides whether the release
is installable at all: right board, a schema generation it implements, a
signing key it trusts, payload paths that stay inside the bundle. Only then
is any payload touched.

Every rejection carries a stable ``code``. The failure-handling matrix in the
image/release design requires operators to be shown the failing step, the
target release, an error code and a recovery action — not a count. Codes are
part of the contract, so they are asserted by name in the tests.

Implemented in the standard library on purpose: this runs on the device
during an update, where a missing pip dependency would be a failure mode of
its own. ``manifest.schema.json`` states the same contract declaratively and
``test_release_manifest.py`` holds the two together.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("manifest.schema.json")

#: Manifest contract versions this implementation understands.
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

#: Config and data generations this runtime can read.
SUPPORTED_CONFIG_SCHEMAS = frozenset({1})
SUPPORTED_DATA_SCHEMAS = frozenset({1})

#: What this device is. A release built for anything else is refused.
DEVICE_TARGET = {
    "board": "raspberry-pi-5",
    "architecture": "arm64",
    "os_family": "raspberry-pi-os-lite",
}

REQUIRED_FIELDS = (
    "schema_version",
    "release_id",
    "git_revision",
    "created_at",
    "target",
    "runtime",
    "containers",
    "defaults",
    "signing_key_id",
    "requires_recommissioning",
    "files",
)

_RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class Rejection:
    """One reason a manifest is not installable."""

    code: str
    field: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.field}: {self.detail}"


class ManifestRejected(Exception):
    """Raised by :func:`load_manifest` when a manifest is not installable."""

    def __init__(self, rejections: list[Rejection]) -> None:
        self.rejections = rejections
        super().__init__("; ".join(str(r) for r in rejections))


def _check_type(
    value: Any, expected: type | tuple[type, ...], field: str, out: list[Rejection]
) -> bool:
    # bool is an int subclass; an integer field must not accept True.
    if expected is int and isinstance(value, bool):
        out.append(Rejection("MANIFEST_FIELD_TYPE", field, "expected integer, got boolean"))
        return False
    if not isinstance(value, expected):
        names = expected.__name__ if isinstance(expected, type) else "/".join(t.__name__ for t in expected)
        out.append(
            Rejection("MANIFEST_FIELD_TYPE", field, f"expected {names}, got {type(value).__name__}")
        )
        return False
    return True


def _validate_files(files: Any, out: list[Rejection]) -> None:
    if not _check_type(files, list, "files", out):
        return
    if not files:
        out.append(Rejection("MANIFEST_FILES_EMPTY", "files", "a release must declare at least one payload file"))
        return

    seen: dict[str, int] = {}
    for index, entry in enumerate(files):
        field = f"files[{index}]"
        if not _check_type(entry, dict, field, out):
            continue

        for key in ("path", "sha256"):
            if key not in entry:
                out.append(Rejection("MANIFEST_FIELD_MISSING", f"{field}.{key}", "required"))

        extra = sorted(set(entry) - FILE_ENTRY_KEYS)
        if extra:
            out.append(
                Rejection("MANIFEST_FIELD_UNKNOWN", field, f"unrecognised fields {extra}")
            )

        path = entry.get("path")
        if isinstance(path, str):
            _validate_payload_path(path, f"{field}.path", out)
            # Compare on the normalised form so "a/b" and "a//b" collide.
            key = path.replace("\\", "/").strip("/")
            if key in seen:
                out.append(
                    Rejection(
                        "MANIFEST_FILE_PATH_DUPLICATE",
                        f"{field}.path",
                        f"{path!r} already declared at files[{seen[key]}]; "
                        "a duplicate path lets one entry's checksum stand in for another",
                    )
                )
            else:
                seen[key] = index
        elif path is not None:
            _check_type(path, str, f"{field}.path", out)

        digest = entry.get("sha256")
        if isinstance(digest, str) and not _SHA256.match(digest):
            out.append(
                Rejection("MANIFEST_FILE_SHA256_INVALID", f"{field}.sha256", f"not a 64-hex sha256: {digest!r}")
            )
        elif digest is not None and not isinstance(digest, str):
            _check_type(digest, str, f"{field}.sha256", out)


def _validate_payload_path(path: str, field: str, out: list[Rejection]) -> None:
    """Payload paths must stay inside the bundle root.

    Checked on the declared string rather than after joining: by the time a
    traversal has been resolved against a staging directory it has already
    escaped.
    """
    normalised = path.replace("\\", "/")

    if normalised.startswith("/") or _WINDOWS_DRIVE.match(path):
        out.append(Rejection("MANIFEST_FILE_PATH_ABSOLUTE", field, f"absolute path: {path!r}"))
        return

    if any(part == ".." for part in normalised.split("/")):
        out.append(
            Rejection("MANIFEST_FILE_PATH_TRAVERSAL", field, f"path escapes the bundle root: {path!r}")
        )
        return

    if normalised.startswith("~"):
        out.append(
            Rejection("MANIFEST_FILE_PATH_ABSOLUTE", field, f"home-relative path: {path!r}")
        )
        return

    if "\0" in path:
        out.append(Rejection("MANIFEST_FILE_PATH_INVALID", field, "path contains a NUL byte"))


def _validate_target(target: Any, expected: dict[str, str], out: list[Rejection]) -> None:
    if not _check_type(target, dict, "target", out):
        return

    for key in ("board", "architecture", "os_family", "os_suite"):
        if key not in target:
            out.append(Rejection("MANIFEST_FIELD_MISSING", f"target.{key}", "required"))

    for key, want in expected.items():
        got = target.get(key)
        if got is not None and got != want:
            out.append(
                Rejection(
                    "MANIFEST_TARGET_MISMATCH",
                    f"target.{key}",
                    f"release targets {got!r}, this device is {want!r}",
                )
            )


def _validate_runtime(runtime: Any, out: list[Rejection]) -> None:
    if not _check_type(runtime, dict, "runtime", out):
        return

    for key in ("config_schema", "data_schema", "minimum_bootloader"):
        if key not in runtime:
            out.append(Rejection("MANIFEST_FIELD_MISSING", f"runtime.{key}", "required"))

    config_schema = runtime.get("config_schema")
    if (
        config_schema is not None
        and _check_type(config_schema, int, "runtime.config_schema", out)
        and config_schema not in SUPPORTED_CONFIG_SCHEMAS
    ):
        out.append(
            Rejection(
                "MANIFEST_CONFIG_SCHEMA_UNSUPPORTED",
                "runtime.config_schema",
                f"generation {config_schema} is not readable by this runtime "
                f"(supported: {sorted(SUPPORTED_CONFIG_SCHEMAS)})",
            )
        )

    data_schema = runtime.get("data_schema")
    if (
        data_schema is not None
        and _check_type(data_schema, int, "runtime.data_schema", out)
        and data_schema not in SUPPORTED_DATA_SCHEMAS
    ):
        out.append(
            Rejection(
                "MANIFEST_DATA_SCHEMA_UNSUPPORTED",
                "runtime.data_schema",
                f"generation {data_schema} is not readable by this runtime "
                f"(supported: {sorted(SUPPORTED_DATA_SCHEMAS)})",
            )
        )

    bootloader = runtime.get("minimum_bootloader")
    if bootloader is not None and not isinstance(bootloader, str):
        out.append(
            Rejection("MANIFEST_FIELD_TYPE", "runtime.minimum_bootloader", "expected string or null")
        )


def _validate_containers(containers: Any, out: list[Rejection]) -> None:
    if not _check_type(containers, dict, "containers", out):
        return

    for key in ("rosy_core", "rosy_io"):
        if key not in containers:
            out.append(Rejection("MANIFEST_FIELD_MISSING", f"containers.{key}", "required"))
            continue
        digest = containers[key]
        if not isinstance(digest, str) or not _DIGEST.match(digest):
            out.append(
                Rejection(
                    "MANIFEST_DIGEST_INVALID",
                    f"containers.{key}",
                    f"expected sha256:<64-hex> immutable digest, got {digest!r}; "
                    "a tag is mutable and cannot pin an image",
                )
            )


#: Fields whose contract genuinely allows null.
NULLABLE_FIELDS = frozenset({"runtime.minimum_bootloader"})


def _reject_nulls(value: object, out: list[Rejection], prefix: str = "") -> None:
    """Report every explicit null, at any depth, except where one is allowed."""
    if isinstance(value, dict):
        for key, item in value.items():
            field = f"{prefix}.{key}" if prefix else key
            if item is None:
                if field not in NULLABLE_FIELDS:
                    out.append(
                        Rejection(
                            "MANIFEST_FIELD_NULL",
                            field,
                            "explicitly null; omit the field or give it a value, "
                            "but do not declare it empty",
                        )
                    )
                continue
            _reject_nulls(item, out, field)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            field = f"{prefix}[{index}]"
            if item is None:
                out.append(Rejection("MANIFEST_FIELD_NULL", field, "explicitly null"))
                continue
            _reject_nulls(item, out, field)


def _reject_unknown_keys(value: object, allowed: dict, out: list[Rejection], prefix: str) -> None:
    """Refuse keys the contract does not define, at every level.

    manifest.schema.json sets additionalProperties: false throughout, so the
    implementation has to agree — an unrecognised key is a manifest written
    against a contract this build does not implement.
    """
    if not isinstance(value, dict):
        return
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        out.append(
            Rejection(
                "MANIFEST_FIELD_UNKNOWN",
                prefix or "<root>",
                f"unrecognised fields {unknown}; refusing rather than ignoring them",
            )
        )
    for key, nested in allowed.items():
        if nested and key in value:
            _reject_unknown_keys(value[key], nested, out, f"{prefix}.{key}" if prefix else key)


#: The full key shape, mirroring manifest.schema.json.
ALLOWED_KEYS: dict = {
    "schema_version": None,
    "release_id": None,
    "git_revision": None,
    "created_at": None,
    "target": {"board": None, "architecture": None, "os_family": None, "os_suite": None},
    "runtime": {"config_schema": None, "data_schema": None, "minimum_bootloader": None},
    "containers": {"rosy_core": None, "rosy_io": None},
    "defaults": {"runtime_mode": None},
    "signing_key_id": None,
    "requires_recommissioning": None,
    "files": None,
}

FILE_ENTRY_KEYS = frozenset({"path", "sha256"})


def validate_manifest(
    data: Any,
    *,
    device_target: dict[str, str] | None = None,
    trusted_key_ids: frozenset[str] | set[str] | None = None,
) -> list[Rejection]:
    """Return every reason ``data`` is not installable; empty means it is.

    All checks run rather than stopping at the first failure, so an operator
    sees the whole story instead of fixing one field at a time.
    """
    out: list[Rejection] = []

    if not _check_type(data, dict, "<root>", out):
        return out

    # Schema version first: everything below is written against version 1, so
    # interpreting an unknown version's fields would be guesswork.
    version = data.get("schema_version")
    if version is None:
        out.append(Rejection("MANIFEST_FIELD_MISSING", "schema_version", "required"))
        return out
    if not _check_type(version, int, "schema_version", out):
        return out
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        out.append(
            Rejection(
                "MANIFEST_SCHEMA_UNKNOWN",
                "schema_version",
                f"manifest schema {version} is not implemented here "
                f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)})",
            )
        )
        return out

    for field in REQUIRED_FIELDS:
        if field not in data:
            out.append(Rejection("MANIFEST_FIELD_MISSING", field, "required"))

    # null is neither absence nor a value, and every check below is written
    # as "if x is not None". Left alone, a single null walks straight past the
    # board check, the payload-path check and the core-only default. Reject it
    # here so no downstream guard has to remember.
    _reject_nulls(data, out)

    _reject_unknown_keys(data, ALLOWED_KEYS, out, "")

    release_id = data.get("release_id")
    if isinstance(release_id, str) and not _RELEASE_ID.match(release_id):
        out.append(
            Rejection("MANIFEST_RELEASE_ID_INVALID", "release_id", f"expected YYYY.MM.DD-NNN, got {release_id!r}")
        )
    elif release_id is not None and not isinstance(release_id, str):
        _check_type(release_id, str, "release_id", out)

    revision = data.get("git_revision")
    if isinstance(revision, str) and not _GIT_REVISION.match(revision):
        out.append(
            Rejection(
                "MANIFEST_GIT_REVISION_INVALID",
                "git_revision",
                f"expected a full 40-hex commit, got {revision!r}; "
                "an abbreviated revision is ambiguous",
            )
        )
    elif revision is not None and not isinstance(revision, str):
        _check_type(revision, str, "git_revision", out)

    created_at = data.get("created_at")
    if isinstance(created_at, str):
        try:
            parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            out.append(
                Rejection("MANIFEST_CREATED_AT_INVALID", "created_at", f"not an RFC 3339 timestamp: {created_at!r}")
            )
        else:
            if parsed.tzinfo is None:
                out.append(
                    Rejection(
                        "MANIFEST_CREATED_AT_INVALID",
                        "created_at",
                        "timestamp has no UTC offset; a local time is ambiguous across devices",
                    )
                )
    elif created_at is not None:
        _check_type(created_at, str, "created_at", out)

    if "target" in data:
        _validate_target(data["target"], device_target or DEVICE_TARGET, out)
    if "runtime" in data:
        _validate_runtime(data["runtime"], out)
    if "containers" in data:
        _validate_containers(data["containers"], out)

    defaults = data.get("defaults")
    if defaults is not None and _check_type(defaults, dict, "defaults", out):
        mode = defaults.get("runtime_mode")
        if mode is None:
            out.append(Rejection("MANIFEST_FIELD_MISSING", "defaults.runtime_mode", "required"))
        elif mode != "core":
            out.append(
                Rejection(
                    "MANIFEST_RUNTIME_MODE_NOT_CORE",
                    "defaults.runtime_mode",
                    f"first boot, update and rollback must come up core-only, got {mode!r}; "
                    "motor and hardware are a separate field approval",
                )
            )

    key_id = data.get("signing_key_id")
    if isinstance(key_id, str):
        if not _KEY_ID.match(key_id):
            out.append(
                Rejection("MANIFEST_SIGNING_KEY_ID_INVALID", "signing_key_id", f"malformed key id: {key_id!r}")
            )
        elif trusted_key_ids is not None and key_id not in trusted_key_ids:
            out.append(
                Rejection(
                    "MANIFEST_SIGNING_KEY_UNTRUSTED",
                    "signing_key_id",
                    f"{key_id!r} is not in this device's trusted release keys "
                    f"({sorted(trusted_key_ids)})",
                )
            )
    elif key_id is not None:
        _check_type(key_id, str, "signing_key_id", out)

    recommission = data.get("requires_recommissioning")
    if recommission is not None and not isinstance(recommission, bool):
        out.append(
            Rejection("MANIFEST_FIELD_TYPE", "requires_recommissioning", "expected boolean")
        )

    if "files" in data:
        _validate_files(data["files"], out)

    return out


def load_manifest(
    path: Path,
    *,
    device_target: dict[str, str] | None = None,
    trusted_key_ids: frozenset[str] | set[str] | None = None,
) -> dict:
    """Read and validate a manifest file, or raise :class:`ManifestRejected`."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestRejected(
            [Rejection("MANIFEST_UNREADABLE", str(path), str(exc))]
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestRejected(
            [Rejection("MANIFEST_MALFORMED_JSON", str(path), f"line {exc.lineno}: {exc.msg}")]
        ) from exc

    rejections = validate_manifest(
        data, device_target=device_target, trusted_key_ids=trusted_key_ids
    )
    if rejections:
        raise ManifestRejected(rejections)
    return data


def main(argv: list[str] | None = None) -> int:
    """Validate a manifest from the command line.

    Exit code separates success from failure, and ``--json`` emits the
    rejections as data so the dashboard and build scripts do not parse prose.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Validate a ROSY release manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--json", action="store_true", help="emit rejections as JSON")
    parser.add_argument(
        "--trusted-key-id",
        action="append",
        dest="trusted_key_ids",
        help="accept only these signing key ids (repeatable)",
    )
    args = parser.parse_args(argv)

    trusted = frozenset(args.trusted_key_ids) if args.trusted_key_ids else None
    try:
        load_manifest(args.manifest, trusted_key_ids=trusted)
    except ManifestRejected as rejected:
        if args.json:
            print(json.dumps(
                {"ok": False, "rejections": [vars(r) for r in rejected.rejections]},
                ensure_ascii=False,
                indent=2,
            ))
        else:
            for rejection in rejected.rejections:
                print(rejection)
        return 1

    if args.json:
        print(json.dumps({"ok": True, "rejections": []}, indent=2))
    else:
        print(f"{args.manifest}: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
