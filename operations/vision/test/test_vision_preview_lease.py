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


def test_vision_lease_signs_and_verifies_bounded_rectification_settings():
    settings = {
        "mode": "manual",
        "fx": 1.2, "fy": 1.2, "cx": 0.5, "cy": 0.5,
        "k1": -0.18, "k2": 0.03, "p1": 0.0, "p2": 0.0, "k3": 0.0,
        "corners": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        "output_aspect": 1.0,
    }
    signer = VisionLeaseSigner("x" * 32)
    token = signer.issue(principal_id="viewer-1", source_id="ceiling-north",
                         rectification=settings, now=100)

    assert signer.verify(token, source_id="ceiling-north", now=101)["rectification"] == settings


def test_vision_lease_signs_the_auto_mode_and_defaults_manual():
    signer = VisionLeaseSigner("x" * 32)
    auto = signer.issue(principal_id="viewer-1", source_id="ceiling-north",
                        rectification={"mode": "auto"}, now=100)
    manual = signer.issue(principal_id="viewer-1", source_id="ceiling-north",
                          rectification={"fx": 1.2}, now=100)

    assert signer.verify(auto, source_id="ceiling-north",
                         now=101)["rectification"]["mode"] == "auto"
    assert signer.verify(manual, source_id="ceiling-north",
                         now=101)["rectification"]["mode"] == "manual"


def test_vision_lease_rejects_invalid_rectification_settings():
    signer = VisionLeaseSigner("x" * 32)
    with pytest.raises(ValueError):
        signer.issue(principal_id="viewer-1", source_id="ceiling-north",
                     rectification={"k1": 999})
