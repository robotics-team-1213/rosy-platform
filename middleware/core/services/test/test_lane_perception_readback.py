"""Actual keeper paint is display-only evidence with a local receipt lifetime."""
import json

import pytest

from core_features.vision import VisionFrameStore


def packet(source="learned", stamp=10.0, **extra):
    extra.setdefault("paint_source_requested", "learned" if source == "denoise_fallback" else source)
    if source == "learned":
        extra.setdefault("paint_model_revision", "lane-a")
    return json.dumps(dict(paint_source_used=source, stamp=stamp, **extra))


def test_fallback_is_reported_from_actual_frame_not_configured_model():
    store = VisionFrameStore().lane_perception
    assert store.accept(packet("denoise_fallback"), now=20.0, source_now=10.1)
    actual = store.snapshot(paint_source="learned", now=20.5)
    assert actual["applied_paint_source"] == "denoise_fallback"
    assert actual["applied_model_revision"] is None
    assert actual["applied_source_age_s"] == 0.5
    assert store.snapshot(paint_source="learned", now=22.01)["applied_paint_source"] is None


@pytest.mark.parametrize("raw", ["{", "[]", packet("imagined"),
    packet(stamp=float("nan")), json.dumps({"paint_source_used": "learned"}),
    packet(paint_model_revision=32), "x" * 16385], ids=["json", "array", "source", "stamp", "missing-stamp", "revision", "oversize"])
def test_malformed_packet_clears_prior_observation(raw):
    store = VisionFrameStore().lane_perception
    assert store.accept(packet(), now=20.0, source_now=10.1)
    assert not store.accept(raw, now=20.1, source_now=10.1)
    assert store.snapshot(paint_source="learned", now=20.2)["applied_paint_source"] is None


def test_config_mismatch_model_mismatch_clock_reset_and_clear_are_unknown():
    store = VisionFrameStore().lane_perception
    assert store.accept(packet(paint_model_revision="lane-a"), now=20.0, source_now=10.1)
    assert store.snapshot(paint_source="denoise", now=20.1)["applied_paint_source"] is None
    assert store.snapshot(paint_source="learned", model_revision="lane-b", now=20.1)["applied_paint_source"] is None
    assert store.snapshot(paint_source="learned", model_revision="lane-a", now=20.1)["applied_model_revision"] == "lane-a"
    assert not store.accept(packet(stamp=2.0), now=20.2, source_now=2.1)
    assert store.snapshot(paint_source="learned", now=20.3)["applied_paint_source"] is None
    assert store.accept(packet(stamp=2.1), now=20.4, source_now=2.2)
    store.clear()
    assert store.snapshot(paint_source="learned", now=20.5)["applied_paint_source"] is None


def test_receipt_clock_reversal_is_unknown():
    store = VisionFrameStore().lane_perception
    assert store.accept(packet(), now=20.0, source_now=10.1)
    assert store.snapshot(paint_source="learned", now=19.0)["applied_paint_source"] is None


@pytest.mark.parametrize("source_now", [12.01, 9.99, float("nan")])
def test_delayed_image_or_invalid_source_clock_never_becomes_fresh_receipt(source_now):
    store = VisionFrameStore().lane_perception
    assert not store.accept(packet(), now=20.0, source_now=source_now)
    assert store.snapshot(paint_source="learned", now=20.1)["applied_paint_source"] is None


def test_learned_without_served_mask_revision_is_unknown():
    store = VisionFrameStore().lane_perception
    raw = json.dumps(dict(paint_source_used="learned", stamp=10.0))
    assert not store.accept(raw, now=20.0, source_now=10.1)


def test_learned_drivable_paint_is_reported_as_learned():
    store = VisionFrameStore().lane_perception
    raw = json.dumps(dict(paint_source_used="learned_drivable", stamp=10.0,
                          paint_source_requested="learned", paint_model_revision="lane-a"))
    assert store.accept(raw, now=20.0, source_now=10.1)
    actual = store.snapshot(paint_source="learned", model_revision="lane-a", now=20.1)
    assert actual["applied_paint_source"] == "learned" and actual["applied_model_revision"] == "lane-a"
    assert store.snapshot(paint_source="learned", model_revision="lane-b", now=20.1)["applied_paint_source"] is None


@pytest.mark.parametrize("extra", [dict(paint_source_requested="learned"),
                                   dict(paint_source_requested="denoise", paint_model_revision="lane-a")])
def test_learned_drivable_needs_the_learned_request_and_a_revision(extra):
    store = VisionFrameStore().lane_perception
    assert not store.accept(json.dumps(dict(paint_source_used="learned_drivable", stamp=10.0, **extra)),
                            now=20.0, source_now=10.1)
