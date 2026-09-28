"""Rejection contracts for the release manifest (WP-1).

A device reads the manifest before it unpacks anything, so this is the first
place an unusable or hostile release can be turned away. Each test below
names the stable rejection code rather than merely asserting "it failed" —
the failure-handling matrix in the design requires an operator to be shown a
code and a recovery action, so the codes are part of the contract and change
only deliberately.

The valid manifest is built by ``_manifest()`` and each test mutates one
field, so a test failing means that single mutation stopped being caught.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from manifest import (  # via test/conftest.py
    REQUIRED_FIELDS,
    SCHEMA_PATH,
    ManifestRejected,
    load_manifest,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]

DIGEST_CORE = "sha256:" + "a" * 64
DIGEST_IO = "sha256:" + "b" * 64
FILE_SHA = "c" * 64


def _manifest(**overrides) -> dict:
    """A manifest that must validate cleanly."""
    data = {
        "schema_version": 1,
        "release_id": "2026.09.01-001",
        "git_revision": "0" * 40,
        "created_at": "2026-09-01T00:00:00Z",
        "target": {
            "board": "raspberry-pi-5",
            "architecture": "arm64",
            "os_family": "raspberry-pi-os-lite",
            "os_suite": "trixie",
        },
        "runtime": {"config_schema": 1, "data_schema": 1, "minimum_bootloader": None},
        "containers": {"rosy_core": DIGEST_CORE, "rosy_io": DIGEST_IO},
        "defaults": {"runtime_mode": "core"},
        "signing_key_id": "rosy-release-2026-01",
        "requires_recommissioning": True,
        "files": [{"path": "images/rosy-core.oci.tar", "sha256": FILE_SHA}],
    }
    data.update(overrides)
    return data


def _codes(data, **kwargs) -> set[str]:
    return {r.code for r in validate_manifest(data, **kwargs)}


# --- the happy path -------------------------------------------------------


def test_valid_manifest_is_accepted():
    assert validate_manifest(_manifest()) == []


def test_minimum_bootloader_may_be_a_version_string():
    assert validate_manifest(_manifest(runtime={
        "config_schema": 1, "data_schema": 1, "minimum_bootloader": "2026-03-14",
    })) == []


# --- schema version -------------------------------------------------------


def test_unknown_schema_version_is_rejected():
    assert "MANIFEST_SCHEMA_UNKNOWN" in _codes(_manifest(schema_version=2))


def test_unknown_schema_version_stops_further_interpretation():
    """Fields of an unimplemented schema must not be second-guessed."""
    rejections = validate_manifest(_manifest(schema_version=99, release_id="nonsense"))
    assert [r.code for r in rejections] == ["MANIFEST_SCHEMA_UNKNOWN"]


def test_missing_schema_version_is_rejected():
    data = _manifest()
    del data["schema_version"]
    assert "MANIFEST_FIELD_MISSING" in _codes(data)


def test_boolean_is_not_accepted_as_an_integer_version():
    assert "MANIFEST_FIELD_TYPE" in _codes(_manifest(schema_version=True))


# --- required fields ------------------------------------------------------


@pytest.mark.parametrize("field", [f for f in REQUIRED_FIELDS if f != "schema_version"])
def test_every_required_field_is_enforced(field):
    data = _manifest()
    del data[field]
    rejections = validate_manifest(data)
    assert any(r.code == "MANIFEST_FIELD_MISSING" and r.field == field for r in rejections)


def test_unrecognised_field_is_refused_not_ignored():
    codes = _codes(_manifest(rollout_percentage=50))
    assert "MANIFEST_FIELD_UNKNOWN" in codes


# --- identity and provenance formats --------------------------------------


@pytest.mark.parametrize(
    "release_id",
    ["2026.9.1-001", "2026.09.01-1", "v2026.09.01-001", "2026.09.01", ""],
)
def test_malformed_release_id_is_rejected(release_id):
    assert "MANIFEST_RELEASE_ID_INVALID" in _codes(_manifest(release_id=release_id))


@pytest.mark.parametrize(
    "revision",
    ["0" * 39, "0" * 41, "g" * 40, "ABCDEF" + "0" * 34, "HEAD", ""],
)
def test_malformed_git_revision_is_rejected(revision):
    """An abbreviated or non-hex revision cannot identify a build."""
    assert "MANIFEST_GIT_REVISION_INVALID" in _codes(_manifest(git_revision=revision))


@pytest.mark.parametrize("stamp", ["not-a-date", "2026-13-01T00:00:00Z", ""])
def test_malformed_created_at_is_rejected(stamp):
    assert "MANIFEST_CREATED_AT_INVALID" in _codes(_manifest(created_at=stamp))


def test_created_at_without_utc_offset_is_rejected():
    """A local timestamp means different things on different devices."""
    assert "MANIFEST_CREATED_AT_INVALID" in _codes(_manifest(created_at="2026-09-01T00:00:00"))


# --- target ---------------------------------------------------------------


@pytest.mark.parametrize(
    "key,value",
    [
        ("board", "raspberry-pi-4"),
        ("architecture", "armhf"),
        ("architecture", "amd64"),
        ("os_family", "ubuntu-server"),
    ],
)
def test_target_mismatch_is_rejected(key, value):
    target = _manifest()["target"] | {key: value}
    rejections = validate_manifest(_manifest(target=target))
    assert any(r.code == "MANIFEST_TARGET_MISMATCH" and r.field == f"target.{key}" for r in rejections)


def test_os_suite_is_not_pinned_by_the_device():
    """The suite is recorded for provenance; the device does not refuse on it."""
    target = _manifest()["target"] | {"os_suite": "bookworm"}
    assert validate_manifest(_manifest(target=target)) == []


def test_missing_target_key_is_rejected():
    target = {k: v for k, v in _manifest()["target"].items() if k != "board"}
    rejections = validate_manifest(_manifest(target=target))
    assert any(r.code == "MANIFEST_FIELD_MISSING" and r.field == "target.board" for r in rejections)


# --- runtime schemas ------------------------------------------------------


def test_unsupported_config_schema_is_rejected():
    runtime = {"config_schema": 2, "data_schema": 1, "minimum_bootloader": None}
    assert "MANIFEST_CONFIG_SCHEMA_UNSUPPORTED" in _codes(_manifest(runtime=runtime))


def test_unsupported_data_schema_is_rejected():
    runtime = {"config_schema": 1, "data_schema": 7, "minimum_bootloader": None}
    assert "MANIFEST_DATA_SCHEMA_UNSUPPORTED" in _codes(_manifest(runtime=runtime))


def test_config_and_data_schemas_are_reported_separately():
    runtime = {"config_schema": 3, "data_schema": 4, "minimum_bootloader": None}
    codes = _codes(_manifest(runtime=runtime))
    assert {"MANIFEST_CONFIG_SCHEMA_UNSUPPORTED", "MANIFEST_DATA_SCHEMA_UNSUPPORTED"} <= codes


# --- container digests ----------------------------------------------------


@pytest.mark.parametrize(
    "digest",
    [
        "rosy-core:latest",
        "sha256:" + "a" * 63,
        "sha256:" + "z" * 64,
        "a" * 64,
        "md5:" + "a" * 32,
        "",
    ],
)
def test_mutable_or_malformed_digest_is_rejected(digest):
    containers = {"rosy_core": digest, "rosy_io": DIGEST_IO}
    rejections = validate_manifest(_manifest(containers=containers))
    assert any(r.code == "MANIFEST_DIGEST_INVALID" for r in rejections)


def test_both_container_digests_are_required():
    rejections = validate_manifest(_manifest(containers={"rosy_core": DIGEST_CORE}))
    assert any(r.code == "MANIFEST_FIELD_MISSING" and r.field == "containers.rosy_io" for r in rejections)


# --- core-only default ----------------------------------------------------


@pytest.mark.parametrize("mode", ["motor", "hardware", "CORE", ""])
def test_default_runtime_mode_must_be_core(mode):
    """Update and rollback both come up core-only; a manifest cannot opt out."""
    assert "MANIFEST_RUNTIME_MODE_NOT_CORE" in _codes(_manifest(defaults={"runtime_mode": mode}))


def test_core_default_is_accepted():
    assert validate_manifest(_manifest(defaults={"runtime_mode": "core"})) == []


# --- signing key ----------------------------------------------------------


@pytest.mark.parametrize("key_id", ["Rosy-Release", "ab", "key_with_underscore", "-leading", ""])
def test_malformed_signing_key_id_is_rejected(key_id):
    assert "MANIFEST_SIGNING_KEY_ID_INVALID" in _codes(_manifest(signing_key_id=key_id))


def test_untrusted_signing_key_is_rejected():
    codes = _codes(_manifest(), trusted_key_ids={"rosy-release-2027-01"})
    assert "MANIFEST_SIGNING_KEY_UNTRUSTED" in codes


def test_trusted_signing_key_is_accepted():
    assert validate_manifest(_manifest(), trusted_key_ids={"rosy-release-2026-01"}) == []


def test_key_trust_is_not_checked_when_no_trust_store_is_supplied():
    """Build-host validation has no trust store; the device supplies one."""
    assert "MANIFEST_SIGNING_KEY_UNTRUSTED" not in _codes(_manifest())


# --- payload paths --------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/etc/rosy/rosy.yaml", "/etc/passwd", "C:/Windows/System32/drivers/etc/hosts", "~/.ssh/authorized_keys"],
)
def test_absolute_payload_path_is_rejected(path):
    files = [{"path": path, "sha256": FILE_SHA}]
    assert "MANIFEST_FILE_PATH_ABSOLUTE" in _codes(_manifest(files=files))


@pytest.mark.parametrize(
    "path",
    ["../../etc/systemd/system/rosy-runtime.service", "images/../../../root/.ssh/id_ed25519", "..", "a/../../b"],
)
def test_traversing_payload_path_is_rejected(path):
    files = [{"path": path, "sha256": FILE_SHA}]
    assert "MANIFEST_FILE_PATH_TRAVERSAL" in _codes(_manifest(files=files))


def test_dot_segments_that_stay_inside_are_allowed():
    files = [{"path": "images/./rosy-core.oci.tar", "sha256": FILE_SHA}]
    assert validate_manifest(_manifest(files=files)) == []


def test_duplicate_payload_path_is_rejected():
    """Two entries for one path let the weaker checksum stand in for the other."""
    files = [
        {"path": "images/rosy-core.oci.tar", "sha256": FILE_SHA},
        {"path": "images/rosy-core.oci.tar", "sha256": "d" * 64},
    ]
    assert "MANIFEST_FILE_PATH_DUPLICATE" in _codes(_manifest(files=files))


def test_duplicate_detection_normalises_separators():
    files = [
        {"path": "images/rosy-core.oci.tar", "sha256": FILE_SHA},
        {"path": "images\\rosy-core.oci.tar", "sha256": "d" * 64},
    ]
    assert "MANIFEST_FILE_PATH_DUPLICATE" in _codes(_manifest(files=files))


@pytest.mark.parametrize("digest", ["c" * 63, "c" * 65, "C" * 64, "sha256:" + "c" * 64, ""])
def test_malformed_payload_checksum_is_rejected(digest):
    files = [{"path": "images/rosy-core.oci.tar", "sha256": digest}]
    assert "MANIFEST_FILE_SHA256_INVALID" in _codes(_manifest(files=files))


def test_payload_path_with_a_nul_byte_is_rejected():
    """The one rejection code no test named.

    A NUL truncates a path at the C boundary, so what Python validates and
    what the kernel opens can differ. The traversal check fires first when a
    path also contains "..", so this one's only problem is the NUL.
    """
    files = [{"path": "images/rosy-core.oci.tar" + chr(0) + "extra", "sha256": FILE_SHA}]
    assert "MANIFEST_FILE_PATH_INVALID" in _codes(_manifest(files=files))


# --- null is neither absence nor a value ----------------------------------


@pytest.mark.parametrize(
    "field",
    ["release_id", "git_revision", "created_at", "target", "runtime",
     "containers", "defaults", "signing_key_id", "requires_recommissioning", "files"],
)
def test_an_explicitly_null_field_is_rejected(field):
    """Guards written "if x is not None" all had the same hole.

    A single null slipped between them and the "field not in data" check,
    defeating the board check, the payload-path check and the core-only
    default at once.
    """
    assert "MANIFEST_FIELD_NULL" in _codes(_manifest(**{field: None}))


@pytest.mark.parametrize(
    "parent,key",
    [
        ("target", "board"),
        ("target", "architecture"),
        ("runtime", "config_schema"),
        ("containers", "rosy_core"),
        ("defaults", "runtime_mode"),
    ],
)
def test_a_nested_null_is_rejected(parent, key):
    data = _manifest()
    data[parent][key] = None
    assert "MANIFEST_FIELD_NULL" in _codes(data)


def test_a_null_inside_a_file_entry_is_rejected():
    files = [{"path": None, "sha256": None}]
    assert "MANIFEST_FIELD_NULL" in _codes(_manifest(files=files))


def test_minimum_bootloader_is_the_one_field_that_may_be_null():
    """Its contract is "a version string or nothing"."""
    assert validate_manifest(_manifest()) == []
    assert _manifest()["runtime"]["minimum_bootloader"] is None


@pytest.mark.parametrize(
    "parent,key",
    [("target", "board_revision"), ("runtime", "extra"), ("defaults", "allow_hardware")],
)
def test_a_nested_unknown_key_is_rejected(parent, key):
    """The schema sets additionalProperties: false at every level."""
    data = _manifest()
    data[parent][key] = "surprise"
    assert "MANIFEST_FIELD_UNKNOWN" in _codes(data)


def test_an_unknown_key_in_a_file_entry_is_rejected():
    files = [{"path": "images/a.tar", "sha256": FILE_SHA, "mode": "0777"}]
    assert "MANIFEST_FIELD_UNKNOWN" in _codes(_manifest(files=files))


def test_every_rejection_code_the_validator_can_emit_is_asserted_somewhere():
    """A code no test names is a rejection path no test exercises."""
    import re as _re

    source = (ROOT / "deploy" / "robot" / "pinky_pro" / "release" / "manifest.py").read_text(encoding="utf-8")
    emitted = set(_re.findall(r'Rejection\(\s*"(MANIFEST_[A-Z_]+)"', source))

    tests = Path(__file__).read_text(encoding="utf-8")
    unasserted = sorted(code for code in emitted if code not in tests)
    assert not unasserted, f"rejection codes with no test: {unasserted}"


def test_empty_file_list_is_rejected():
    assert "MANIFEST_FILES_EMPTY" in _codes(_manifest(files=[]))


# --- reporting behaviour --------------------------------------------------


def test_all_problems_are_reported_at_once():
    """Operators should not have to fix one field per attempt."""
    codes = _codes(
        _manifest(
            release_id="bad",
            git_revision="short",
            defaults={"runtime_mode": "hardware"},
            files=[{"path": "../escape", "sha256": "nope"}],
        )
    )
    assert {
        "MANIFEST_RELEASE_ID_INVALID",
        "MANIFEST_GIT_REVISION_INVALID",
        "MANIFEST_RUNTIME_MODE_NOT_CORE",
        "MANIFEST_FILE_PATH_TRAVERSAL",
        "MANIFEST_FILE_SHA256_INVALID",
    } <= codes


def test_rejection_renders_code_field_and_reason():
    rejection = validate_manifest(_manifest(schema_version=2))[0]
    rendered = str(rejection)
    assert "MANIFEST_SCHEMA_UNKNOWN" in rendered
    assert "schema_version" in rendered


# --- file loading ---------------------------------------------------------


def test_load_manifest_accepts_a_valid_file(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert load_manifest(path)["release_id"] == "2026.09.01-001"


def test_load_manifest_raises_with_every_rejection(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest(release_id="bad", git_revision="bad")), encoding="utf-8")
    with pytest.raises(ManifestRejected) as excinfo:
        load_manifest(path)
    codes = {r.code for r in excinfo.value.rejections}
    assert {"MANIFEST_RELEASE_ID_INVALID", "MANIFEST_GIT_REVISION_INVALID"} <= codes


def test_malformed_json_is_rejected_with_a_code(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestRejected) as excinfo:
        load_manifest(path)
    assert excinfo.value.rejections[0].code == "MANIFEST_MALFORMED_JSON"


def test_missing_file_is_rejected_with_a_code(tmp_path):
    with pytest.raises(ManifestRejected) as excinfo:
        load_manifest(tmp_path / "absent.json")
    assert excinfo.value.rejections[0].code == "MANIFEST_UNREADABLE"


# --- schema document and implementation agree -----------------------------


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_document_exists_and_is_valid_json(schema):
    assert schema["title"] == "ROSY Release Manifest"


def test_schema_and_validator_require_the_same_fields(schema):
    """Two statements of one contract drift apart unless something checks."""
    assert set(schema["required"]) == set(REQUIRED_FIELDS)


def test_schema_declares_every_required_field_as_a_property(schema):
    assert set(schema["required"]) <= set(schema["properties"])


def test_schema_forbids_additional_properties(schema):
    assert schema["additionalProperties"] is False


def test_schema_pins_the_core_only_default(schema):
    assert schema["properties"]["defaults"]["properties"]["runtime_mode"]["const"] == "core"


def test_the_documented_example_manifest_validates(schema):
    """The design's example must be a manifest the validator accepts."""
    assert schema["properties"]["schema_version"]["const"] == 1
    assert validate_manifest(_manifest()) == []
