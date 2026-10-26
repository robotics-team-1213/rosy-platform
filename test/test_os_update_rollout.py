"""Real Ed25519 rollout signatures; no catalogue, device, service or production key is used."""
import datetime as dt
import importlib
import json

import pytest

from signing import sign_checksums
from test_factory_release_signature import _keys
from test_os_update_manifest import metadata


def rollout(value=None):
    value = metadata() if value is None else value
    return dict(schema_version=1, kind="os-update", release_id=value["release_id"],
                bundle=value["bundle"]["filename"], bundle_sha256=value["bundle"]["sha256"],
                published_at="2026-10-26T00:00:00Z", canary=["rosy-pinky-fixture"],
                canary_ok=False, withdrawn=False, wave_delay_s=600)


def test_exact_signed_bytes_bind_rollout_to_os_bundle_and_canary_wave(tmp_path):
    m = importlib.import_module("os_update_rollout")
    private, public = _keys(tmp_path, "rollout")
    value = rollout()
    raw = json.dumps(value).encode("utf-16")
    assert m.verify(raw, sign_checksums(raw, private), public, metadata()) == value
    before = dt.datetime(2026, 10, 26, 0, 9, 59, tzinfo=dt.timezone.utc)
    m.authorize(value, "rosy-pinky-fixture", before)
    with pytest.raises(ValueError): m.authorize(value, "other", before)
    promoted = dict(value, canary_ok=True)
    with pytest.raises(ValueError): m.authorize(promoted, "other", before)
    m.authorize(promoted, "other", before + dt.timedelta(seconds=1))
    with pytest.raises(ValueError): m.authorize(dict(promoted, withdrawn=True), "rosy-pinky-fixture", before)


@pytest.mark.parametrize("fault", ["schema_bool", "kind", "release", "bundle", "digest", "published", "canary",
    "duplicate_canary", "canary_bool", "withdraw_bool", "delay_bool", "delay_short", "extra", "duplicate_json"])
def test_signed_invalid_rollout_is_rejected_without_loosening_metadata(tmp_path, fault):
    m = importlib.import_module("os_update_rollout")
    private, public = _keys(tmp_path, "rollout")
    value = rollout()
    updates = dict(schema_bool=("schema_version", True), kind=("kind", "payload"), release=("release_id", "2026.10.26-999"),
        bundle=("bundle", "../bundle"), digest=("bundle_sha256", "0" * 64), published=("published_at", "unknown"),
        canary=("canary", ["bad/name"]), duplicate_canary=("canary", ["same", "same"]),
        canary_bool=("canary_ok", 1), withdraw_bool=("withdrawn", 1), delay_bool=("wave_delay_s", True),
        delay_short=("wave_delay_s", 599), extra=("unknown", None))
    if fault in updates:
        key, item = updates[fault]
        value[key] = item
    raw = json.dumps(value).encode()
    if fault == "duplicate_json": raw = b'{"schema_version":1,' + raw[1:]
    with pytest.raises(ValueError): m.verify(raw, sign_checksums(raw, private), public, metadata())


def test_untrusted_signature_is_rejected_before_json_parsing(tmp_path, monkeypatch):
    m = importlib.import_module("os_update_rollout")
    private, public = _keys(tmp_path, "rollout")
    raw = json.dumps(rollout()).encode()
    sig = sign_checksums(raw, private)
    monkeypatch.setattr(m.json, "loads", lambda *a, **k: (_ for _ in ()).throw(AssertionError("untrusted JSON parsed")))
    with pytest.raises(ValueError): m.verify(raw + b" ", sig, public, metadata())
