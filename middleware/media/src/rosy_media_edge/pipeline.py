"""Single H.264/WHIP publisher, fed packed RGB by the existing camera owner.

GStreamer imports are lazy: installing this module does not make CORE or
perception startup depend on a media runtime. This process never opens a camera.
"""

import threading
import time

from .watermark import stamp_rgb
from .whip import WhipSession


class MediaPublisher:
    def __init__(self, endpoint, token, *, ca_file=None, allow_loopback_http=False):
        self._session = WhipSession(endpoint, token, ca_file=ca_file,
                                    allow_loopback_http=allow_loopback_http)
        self._connected = threading.Event()
        self._negotiating = False
        self._failure = None
        self._pipeline = None
        self._loop = None
        self._thread = None
        self._signaling = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._fps, self._last_push = 15, None
        self._queue_overrun = False

    def start(self):
        if self._pipeline is not None or self._stopping.is_set():
            raise RuntimeError('create a fresh publisher for each media session')
        import gi
        gi.require_version('Gst', '1.0')
        gi.require_version('GstWebRTC', '1.0')
        gi.require_version('GstSdp', '1.0')
        from gi.repository import GLib, Gst, GstSdp, GstWebRTC
        self._gst, self._sdp, self._webrtc = Gst, GstSdp, GstWebRTC
        Gst.init(None)
        self._pipeline = Gst.parse_launch(
            'appsrc name=frames is-live=true do-timestamp=true format=time '
            'max-buffers=1 leaky-type=downstream block=false '
            'caps=video/x-raw,format=RGB,width=640,height=480,framerate=15/1 '
            '! videoconvert ! x264enc name=encoder tune=zerolatency '
            'speed-preset=ultrafast bitrate=800 key-int-max=5 bframes=0 '
            'vbv-buf-capacity=200 option-string=vbv-maxrate=1000 '
            '! video/x-h264,profile=baseline '
            '! queue name=encoded_queue max-size-time=200000000 '
            'max-size-bytes=0 max-size-buffers=0 leaky=no ! h264parse '
            '! rtph264pay config-interval=-1 pt=96 '
            '! application/x-rtp,media=video,encoding-name=H264,payload=96 '
            '! webrtcbin name=rtc bundle-policy=max-bundle')
        self._source = self._pipeline.get_by_name('frames')
        self._encoder = self._pipeline.get_by_name('encoder')
        self._queue = self._pipeline.get_by_name('encoded_queue')
        self._queue.connect('overrun', self._on_queue_overrun)
        self._rtc = self._pipeline.get_by_name('rtc')
        self._rtc.connect('on-negotiation-needed', self._on_negotiation)
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message::error', self._on_error)
        self._loop = GLib.MainLoop()
        self._thread = threading.Thread(target=self._loop.run, daemon=True)
        self._thread.start()
        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.stop()
            raise RuntimeError('media pipeline failed to start')

    def _on_error(self, bus, message):
        # Pipeline diagnostics can contain remote addresses; expose only a fixed error.
        self._failure = RuntimeError('media pipeline error')
        self._connected.set()

    def _on_queue_overrun(self, queue):
        # Never discard arbitrary encoded reference frames: the worker restarts at IDR.
        self._queue_overrun = True

    def _on_negotiation(self, rtc):
        with self._lock:
            if self._negotiating or self._stopping.is_set():
                return
            self._negotiating = True
        self._signaling = threading.Thread(target=self._negotiate, daemon=True)
        self._signaling.start()

    def _promise(self, element, action, *args):
        ready = threading.Event()
        promise = self._gst.Promise.new_with_change_func(lambda *_: ready.set(), None, None)
        element.emit(action, *args, promise)
        deadline = time.monotonic() + 3
        while not ready.wait(.02):
            if self._stopping.is_set() or time.monotonic() >= deadline:
                promise.interrupt()
                raise RuntimeError('media operation cancelled or timed out')
        if promise.wait() != self._gst.PromiseResult.REPLIED:
            raise RuntimeError('media SDP negotiation failed')
        return promise

    def _negotiate(self):
        try:
            # Keep the promise alive while its boxed SDP description is consumed.
            promise = self._promise(self._rtc, 'create-offer', None)
            reply = promise.get_reply()
            offer = reply.get_value('offer')
            if offer is None or offer.sdp is None:
                raise RuntimeError('media offer is missing SDP')
            self._promise(self._rtc, 'set-local-description', offer)
            until = time.monotonic() + 8
            while self._rtc.get_property('ice-gathering-state') != self._webrtc.WebRTCICEGatheringState.COMPLETE:
                if time.monotonic() >= until or self._stopping.wait(0.02):
                    raise RuntimeError('media ICE gathering did not finish')
            description = self._rtc.get_property('local-description').sdp.as_text()
            answer = self._session.open(description)
            if self._stopping.is_set():
                self._session.close()
                return
            _, sdp = self._sdp.SDPMessage.new_from_text(answer)
            answer = self._webrtc.WebRTCSessionDescription.new(self._webrtc.WebRTCSDPType.ANSWER, sdp)
            self._promise(self._rtc, 'set-remote-description', answer)
        except Exception as exc:
            self._failure = RuntimeError('media negotiation failed: ' + type(exc).__name__)
            self._failure.__cause__ = exc
        finally:
            self._connected.set()

    def wait_connected(self, timeout=12):
        if not self._connected.wait(timeout):
            raise RuntimeError('media signaling timeout')
        if self._failure:
            raise self._failure

    def ready(self):
        if self._failure:
            raise self._failure
        if self._pipeline is None or self._stopping.is_set():
            return False
        state = self._rtc.get_property('connection-state')
        if state == self._webrtc.WebRTCPeerConnectionState.FAILED:
            raise RuntimeError('media transport failed')
        return state == self._webrtc.WebRTCPeerConnectionState.CONNECTED

    def push_rgb(self, rgb, *, epoch, sequence, captured_ms):
        if self._stopping.is_set() or self._pipeline is None:
            return False
        if self._failure:
            raise self._failure
        now = time.monotonic()
        with self._lock:
            # One primer exposes codec caps; negotiation must not accumulate encoded video.
            if self._last_push is not None and not self.ready():
                return False
            if self._last_push is not None and now - self._last_push < 1 / self._fps:
                return False
            self._last_push = now
        frame = bytearray(rgb)
        stamp_rgb(frame, 640, 480, epoch=epoch, sequence=sequence, captured_ms=captured_ms)
        buffer = self._gst.Buffer.new_allocate(None, len(frame), None)
        buffer.fill(0, frame)
        return self._source.emit('push-buffer', buffer) == self._gst.FlowReturn.OK

    def set_rate(self, *, fps, bitrate):
        if type(fps) is not int or fps not in (5, 10, 15) or type(bitrate) is not int or not 100000 <= bitrate <= 1000000:
            raise ValueError('media rate is outside the D-789 profile')
        if self._pipeline is None or self._stopping.is_set():
            raise RuntimeError('media publisher is not running')
        self._encoder.set_property('bitrate', bitrate // 1000)
        self._source.set_property('caps', self._gst.Caps.from_string(
            f'video/x-raw,format=RGB,width=640,height=480,framerate={fps}/1'))
        with self._lock:
            self._fps = fps

    def stats(self):
        if self._pipeline is None or self._stopping.is_set():
            raise RuntimeError('media publisher is not running')
        promise = self._promise(self._rtc, 'get-stats', None)
        reply = promise.get_reply()
        sent_bytes, sent_packets, loss = 0, 0, []
        for index in range(reply.n_fields()):
            name = reply.nth_field_name(index)
            report = reply.get_value(name)
            if name.startswith('rtp-outbound-stream-stats_'):
                sent_bytes += report.get_value('bytes-sent') or 0
                sent_packets += report.get_value('packets-sent') or 0
            elif name.startswith('rtp-remote-inbound-stream-stats_') and report.has_field('fraction-lost'):
                loss.append(report.get_value('fraction-lost'))
        return {'rtp_bytes_sent': sent_bytes, 'rtp_packets_sent': sent_packets,
                'loss_fraction': max(loss) if loss else None,
                'feedback_available': bool(loss),
                'encoded_queue_ms': self._queue.get_property('current-level-time') / self._gst.MSECOND,
                'encoded_queue_overrun': self._queue_overrun,
                'encoder_bitrate': self._encoder.get_property('bitrate') * 1000,
                'encoder_key_interval': self._encoder.get_property('key-int-max'), 'fps_limit': self._fps}

    def stop(self):
        self._stopping.set()
        if self._pipeline is not None:
            self._pipeline.set_state(self._gst.State.NULL)
        if self._loop is not None:
            self._loop.quit()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._signaling is not None:
            self._signaling.join(timeout=5)
        self._session.close()
