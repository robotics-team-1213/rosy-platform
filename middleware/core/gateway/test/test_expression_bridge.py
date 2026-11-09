"""D-922: actual frame admission and recoverable asynchronous indicator outputs."""
from concurrent.futures import Future
import importlib
import json
from types import SimpleNamespace

from core_features.vision import ModelStatusStore


def bridge():
    return importlib.import_module("core.bridge.expression")


def test_indicator_waits_for_success_and_retries_a_failed_reply():
    output = bridge().ServiceOutput()
    calls = []

    def send(value):
        future = Future()
        calls.append((value, future))
        return future

    output.apply("happy", now=0, ready=True, send=send)
    output.apply("happy", now=.2, ready=True, send=send)
    assert len(calls) == 1
    calls[-1][1].set_result(SimpleNamespace(success=False))
    output.apply("happy", now=.4, ready=True, send=send)
    assert len(calls) == 2
    calls[-1][1].set_result(SimpleNamespace(success=True))
    output.apply("happy", now=.6, ready=True, send=send)
    assert len(calls) == 2
    output.apply("happy", now=.8, ready=False, send=send)
    output.apply("happy", now=1, ready=True, send=send)
    assert len(calls) == 3


def test_a_lost_rpc_is_cancelled_without_accumulating_pending_calls():
    output = bridge().ServiceOutput()
    futures = []

    def send(value):
        future = Future()
        futures.append(future)
        return future

    output.apply("interest", now=0, ready=True, send=send)
    output.apply("basic", now=1.2, ready=True, send=send)
    assert futures[0].cancelled() and len(futures) == 2


def test_display_admission_requires_the_reported_current_model_revision():
    from core.bridge.expression_policy import ExpressionPolicy

    p = ExpressionPolicy()
    models = ModelStatusStore()
    raw = json.dumps(dict(model_revision="active-v1", observed_at=1000, seq=0,
        input_width=320, input_height=240, input_fps=10,
        detections=[dict(label="person", x=.7, y=.1, w=.1, h=.5, confidence=.9, track_id=1)]))
    bridge().observe(p, raw, models=models, source_now=1000, now=0)
    assert p.update("IDLE", "IDLE", 0).gaze_x == 0
    models.accept("perception/learned/object_det/status", json.dumps(dict(
        schema="rosy.perception.learned_status/1", model_revision="active-v1", last_error=None)), now=0)
    for i in range(1, 6):
        packet = json.loads(raw)
        packet.update(seq=i, observed_at=1000 + i * .2)
        bridge().observe(p, json.dumps(packet), models=models, source_now=packet["observed_at"], now=i * .2)
        out = p.update("IDLE", "IDLE", i * .2)
    assert out.face == "happy" and out.gaze_x > 0


def test_alert_dark_phase_and_info_window_both_suppress_the_expression_led():
    from core.bridge.expression_policy import Expression
    desired = Expression("happy", rgb=(12, 4, 10))
    alert = SimpleNamespace(lit_at=lambda _: False, r=255, g=0, b=0)
    assert bridge().led_command(desired, alert=alert, info_visible=False,
                                gauge_percent=80, now=0).command == "clear"
    gauge = bridge().led_command(desired, alert=None, info_visible=True, gauge_percent=80, now=0)
    assert (gauge.r, gauge.g, gauge.b) == (0, 60, 0)
    normal = bridge().led_command(desired, alert=None, info_visible=False, gauge_percent=80, now=0)
    assert (normal.r, normal.g, normal.b) == desired.rgb


def test_emotion_rpc_acknowledges_the_real_string_response_without_restarting():
    output = bridge().ServiceOutput(accept=bridge().emotion_accepted)
    calls = []

    def send(value):
        future = Future()
        future.set_result(SimpleNamespace(response=f"Emotion set to {value}"))
        calls.append(value)
        return future

    output.apply("happy", now=0, ready=True, send=send)
    output.apply("happy", now=.2, ready=True, send=send)
    output.apply("happy", now=.4, ready=True, send=send)
    assert calls == ["happy"]
    assert not bridge().emotion_accepted("happy", SimpleNamespace(response="Wrong command or emotion not cached"))
