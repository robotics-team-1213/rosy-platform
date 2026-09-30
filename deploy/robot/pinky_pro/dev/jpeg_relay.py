#!/usr/bin/env python3
"""Bench-only camera JPEG relay for compact recordings.

Subscribes <ns>/camera/front (sensor_msgs/Image) and republishes
<ns>/camera/front/compressed (sensor_msgs/CompressedImage, format "jpeg")
with the same header. Standalone: needs rclpy + numpy and simplejpeg or cv2,
no repo imports. Not part of the product install.

  python3 jpeg_relay.py [--ns /pinky_8kcn] [--quality 85] [--max-fps 0]
"""

from __future__ import annotations

import argparse
import os
import statistics
import time

import numpy as np

_CHANNELS = {"bgr8": 3, "rgb8": 3, "mono8": 1}


def resolve_encoder(backend: str = "auto"):
    """Pick the JPEG backend once: ("simplejpeg", module) or ("cv2", module)."""
    if backend in ("auto", "simplejpeg"):
        try:
            import simplejpeg

            return "simplejpeg", simplejpeg
        except ImportError:
            if backend == "simplejpeg":
                raise
    import cv2

    return "cv2", cv2


def encode_jpeg(
    data: bytes,
    width: int,
    height: int,
    step: int,
    encoding: str,
    quality: int,
    encoder,
) -> bytes:
    """Encode one raw sensor_msgs/Image payload with an encoder from resolve_encoder()."""
    ch = _CHANNELS.get(encoding)
    if ch is None:
        raise ValueError(f"unsupported encoding {encoding!r}")
    rows = np.frombuffer(data, dtype=np.uint8, count=step * height).reshape(height, step)
    img = np.ascontiguousarray(rows[:, : width * ch].reshape(height, width, ch))
    name, mod = encoder
    if name == "simplejpeg":
        space = {"bgr8": "BGR", "rgb8": "RGB", "mono8": "GRAY"}[encoding]
        sub = "Gray" if ch == 1 else "420"
        return mod.encode_jpeg(img, quality=quality, colorspace=space, colorsubsampling=sub)
    if encoding == "rgb8":
        img = img[:, :, ::-1]
    ok, buf = mod.imencode(".jpg", img, [int(mod.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return buf.tobytes()


class Decimator:
    """Pass at most max_fps frames per second; max_fps <= 0 passes all.

    Spacing is measured from the last passed frame, so a late frame after a gap is
    never followed by another one sooner than 0.9 period (0.1 absorbs input jitter).
    """

    def __init__(self, max_fps: float) -> None:
        self.min_gap = 0.9 / max_fps if max_fps > 0 else 0.0
        self.last: float | None = None

    def accept(self, t: float) -> bool:
        if self.min_gap <= 0:
            return True
        if self.last is not None and t - self.last < self.min_gap:
            return False
        self.last = t
        return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ns", default="/" + os.environ.get("ROSY_NAMESPACE", "").strip("/"))
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--max-fps", type=float, default=0.0)
    ap.add_argument("--backend", default="auto", choices=["auto", "simplejpeg", "cv2"])
    args = ap.parse_args()

    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import CompressedImage, Image

    ns = args.ns.rstrip("/")
    rclpy.init()
    node = Node("jpeg_relay")
    log = node.get_logger()
    encoder = resolve_encoder(args.backend)
    sub_qos = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.BEST_EFFORT)
    pub = node.create_publisher(CompressedImage, f"{ns}/camera/front/compressed", 5)
    dec = Decimator(args.max_fps)
    stats = {"in": 0, "out": 0, "errors": 0, "ms": [], "bytes": 0}

    def on_image(msg: Image) -> None:
        stats["in"] += 1
        if not dec.accept(time.monotonic()):
            return
        t0 = time.perf_counter()
        try:
            jpg = encode_jpeg(bytes(msg.data), msg.width, msg.height, msg.step, msg.encoding, args.quality, encoder)
            stats["ms"].append((time.perf_counter() - t0) * 1000.0)
            out = CompressedImage()
            out.header = msg.header
            out.format = "jpeg"
            out.data = jpg
            pub.publish(out)
        except Exception as exc:  # one bad frame must not kill the relay
            stats["errors"] += 1
            log.warning(f"frame dropped: {type(exc).__name__}: {exc}", throttle_duration_sec=10.0)
            return
        stats["out"] += 1
        stats["bytes"] += len(jpg)

    def report() -> None:
        ms, n = stats["ms"], stats["out"]
        if n:
            log.info(
                f"in={stats['in']} out={n} errors={stats['errors']} encode_ms_p50={statistics.median(ms):.2f} "
                f"encode_ms_max={max(ms):.2f} bytes_per_frame={stats['bytes'] // n}"
            )
        else:
            log.info(f"in={stats['in']} out=0 errors={stats['errors']}")
        stats.update({"in": 0, "out": 0, "errors": 0, "ms": [], "bytes": 0})

    node.create_subscription(Image, f"{ns}/camera/front", on_image, sub_qos)
    node.create_timer(10.0, report)
    log.info(f"relay {ns}/camera/front -> compressed q={args.quality} max_fps={args.max_fps} backend={encoder[0]}")
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
