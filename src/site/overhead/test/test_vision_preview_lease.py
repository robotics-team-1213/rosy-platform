import pytest

from core_common.protocol.vision_preview import VisionLeaseError, VisionLeaseSigner


def test_vision_lease_is_source_scoped_short_lived_and_frame_read_only():
    signer = VisionLeaseSigner("x" * 32)
    token = signer.issue(principal_id="viewer-1", source_id="ceiling-north", now=100, ttl_s=60)

    assert signer.verify(token, source_id="ceiling-north", now=159)["scope"] == "frame:read"
    with pytest.raises(VisionLeaseError):
        signer.verify(token, source_id="ceiling-south", now=159)
    with pytest.raises(VisionLeaseError):
        signer.verify(token, source_id="ceiling-north", now=160)


def test_vision_lease_rejects_tampering_and_long_ttl():
    signer = VisionLeaseSigner("x" * 32)
    token = signer.issue(principal_id="viewer-1", source_id="ceiling-north", now=100)
    with pytest.raises(VisionLeaseError):
        signer.verify(token[:-1] + ("A" if token[-1] != "A" else "B"),
                      source_id="ceiling-north", now=101)
    with pytest.raises(ValueError):
        signer.issue(principal_id="viewer-1", source_id="ceiling-north", now=100, ttl_s=121)


def test_vision_lease_secret_must_be_dedicated_and_adequate():
    with pytest.raises(ValueError):
        VisionLeaseSigner("short")
