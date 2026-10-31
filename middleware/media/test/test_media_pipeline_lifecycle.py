"""A stopped media worker must not hang on a pending GStreamer promise."""

import importlib
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def test_stop_interrupts_a_pending_sdp_operation():
    publisher = importlib.import_module('rosy_media_edge.pipeline').MediaPublisher(
        'https://media.example/robots/r1/front/whip', 'scoped-token')
    pending, entered = threading.Event(), threading.Event()
    interrupted, errors = [], []

    class Promise:
        callback = None

        @classmethod
        def new(cls):
            return cls()

        @classmethod
        def new_with_change_func(cls, callback, *args):
            cls.callback = callback
            return cls()

        def wait(self):
            entered.set()
            pending.wait(1)
            return 'interrupted'

        def interrupt(self):
            interrupted.append(True)
            pending.set()

    class Element:
        def emit(self, *args):
            entered.set()

    publisher._gst = SimpleNamespace(Promise=Promise, PromiseResult=SimpleNamespace(REPLIED='replied'))

    def run():
        try:
            publisher._promise(Element(), 'create-offer', None)
        except RuntimeError as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(.2)
        publisher._stopping.set()
        worker.join(timeout=.2)
        assert not worker.is_alive(), 'stopping media must interrupt the SDP wait'
        assert interrupted
        assert errors
    finally:
        pending.set()
        worker.join(timeout=1)


def test_rate_controls_are_available_without_importing_gstreamer():
    publisher = importlib.import_module('rosy_media_edge.pipeline').MediaPublisher(
        'https://media.example/robots/r1/front/whip', 'scoped-token')
    assert hasattr(publisher, 'set_rate'), 'D-789 encoder rate controls are missing'
    assert hasattr(publisher, 'stats'), 'D-789 real transport statistics are missing'


def test_only_one_priming_frame_is_queued_before_transport_is_connected(monkeypatch):
    module = importlib.import_module('rosy_media_edge.pipeline')
    publisher = module.MediaPublisher('https://media.example/robots/r1/front/whip', 'scoped-token')
    states, pushed = ['connecting'], []
    clock = iter([1., 2., 3.])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(module, 'stamp_rgb', lambda *args, **kwargs: None)
    publisher._pipeline = object()
    publisher._rtc = SimpleNamespace(get_property=lambda name: states[0])
    publisher._webrtc = SimpleNamespace(WebRTCPeerConnectionState=SimpleNamespace(CONNECTED='connected', FAILED='failed'))
    publisher._gst = SimpleNamespace(
        Buffer=SimpleNamespace(new_allocate=lambda *args: SimpleNamespace(fill=lambda *args: None)),
        FlowReturn=SimpleNamespace(OK='ok'))
    publisher._source = SimpleNamespace(emit=lambda name, buffer: pushed.append(buffer) or 'ok')
    assert publisher.push_rgb(b'frame', epoch=1, sequence=1, captured_ms=1)
    assert not publisher.push_rgb(b'frame', epoch=1, sequence=2, captured_ms=2)
    assert len(pushed) == 1
    states[0] = 'connected'
    publisher._connected.set()
    assert publisher.push_rgb(b'frame', epoch=1, sequence=3, captured_ms=3)
    assert len(pushed) == 2
