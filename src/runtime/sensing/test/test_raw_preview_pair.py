"""Run the producer callback without ROS and decode its actual JPEG outputs."""
import ast
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from control.sensing.perception.camera_visibility import visibility_reason


@pytest.mark.parametrize('brightness,reason', [(20, 'low_light'), (255, 'overexposed')])
def test_raw_pair_preserves_pixels_capture_identity_and_raw_quality(brightness, reason):
    source = Path(__file__).parents[1] / 'control/road_observer_node.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RoadObserverNode')
    callback = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == '_publish_preview')
    callback.returns = None
    for arg in callback.args.args:
        arg.annotation = None
    raw_messages, annotated_messages = [], []
    evidence = SimpleNamespace(for_frame=lambda *a: None, recent=lambda *a: None)
    node = SimpleNamespace(
        _preview_rate=SimpleNamespace(allow=lambda *a: True), _preview_evidence=evidence,
        _preview_config=SimpleNamespace(source='ROSY', max_width=64, jpeg_quality=95, max_bytes=512000),
        preview_pub=SimpleNamespace(publish=annotated_messages.append),
        raw_preview_pub=SimpleNamespace(publish=raw_messages.append),
        get_logger=lambda: SimpleNamespace(warning=lambda *a: None))
    namespace = dict(cv2=cv2, np=np, time=SimpleNamespace(monotonic=lambda: 10),
                     CompressedImage=SimpleNamespace, visibility_reason=visibility_reason,
                     render_road_preview=lambda frame, *a, **kw: np.full_like(frame, 255),
                     detect_visual_tags=lambda *a: [], DETECTION_JOIN_S=.6)
    exec(compile(ast.Module(body=[callback], type_ignores=[]), str(source), 'exec'), namespace)
    frame = np.full((48, 64, 3), brightness, dtype=np.uint8)
    header = SimpleNamespace(stamp=SimpleNamespace(sec=100, nanosec=123), frame_id='front')
    namespace['_publish_preview'](node, SimpleNamespace(header=header), frame, None, 100.0)
    assert len(raw_messages) == len(annotated_messages) == 1
    raw, annotated = raw_messages[0], annotated_messages[0]
    assert raw.header is annotated.header is header
    assert 'overlay=none' in raw.format and 'overlay=follow-road-v2' in annotated.format
    assert 'quality_valid=false' in raw.format and ('quality_reason=' + reason) in annotated.format
    decoded_raw = cv2.imdecode(np.frombuffer(raw.data, np.uint8), cv2.IMREAD_COLOR)
    decoded_annotated = cv2.imdecode(np.frombuffer(annotated.data, np.uint8), cv2.IMREAD_COLOR)
    assert decoded_raw.shape == decoded_annotated.shape == frame.shape
    assert abs(float(decoded_raw.mean()) - brightness) < 2
    assert decoded_annotated.mean() > 250
    assert np.all(frame == brightness)
