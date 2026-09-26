from types import SimpleNamespace as NS

import pytest

from omx_adapter.camera_contract import CameraFrameGate, CameraStreamConfig


def message(frame="overhead_optical", sec=10, nanosec=20, width=640, height=480):
    header = NS(frame_id=frame, stamp=NS(sec=sec, nanosec=nanosec))
    image = NS(header=header, width=width, height=height)
    info_header = NS(frame_id=frame, stamp=NS(sec=sec, nanosec=nanosec))
    info = NS(
        header=info_header, width=width, height=height,
        distortion_model="plumb_bob", d=[0.0] * 5,
        k=[500.0, 0, 320, 0, 500, 240, 0, 0, 1],
        r=[1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0],
        p=[500.0, 0, 320, 0, 0, 500.0, 240, 0, 0, 0, 1.0, 0],
        binning_x=0, binning_y=0,
        roi=NS(x_offset=0, y_offset=0, width=0, height=0, do_rectify=False),
    )
    return image, info


@pytest.fixture
def gate():
    _, info = message()
    digest = CameraFrameGate.camera_info_fingerprint(info)
    return CameraFrameGate(CameraStreamConfig(
        "usb-by-id:camera-serial", "overhead_optical", "cal-v3", digest
    ))


def test_admits_exact_stamped_calibrated_pair_with_identity_and_revision(gate):
    image, info = message()
    metadata = gate.accept(image, info, received_at=12.5)
    assert metadata.camera_identity == "usb-by-id:camera-serial"
    assert metadata.capture_time_ns == 10_000_000_020
    assert metadata.calibration_revision == "cal-v3"
    assert metadata.sequence == 1
    assert gate.is_fresh(now=12.9)
    assert not gate.is_fresh(now=13.1)


@pytest.mark.parametrize("mutation, error", [
    (lambda i, c: setattr(c.header.stamp, "nanosec", 21), "stamps differ"),
    (lambda i, c: setattr(i.header, "frame_id", "other_optical"), "frame"),
    (lambda i, c: setattr(c, "width", 800), "dimensions differ"),
    (lambda i, c: setattr(c, "k", [0.0] * 9), "uncalibrated"),
])
def test_rejects_unmatched_or_unusable_camera_metadata(gate, mutation, error):
    image, info = message()
    mutation(image, info)
    with pytest.raises(ValueError, match=error):
        gate.accept(image, info, received_at=1.0)
    assert gate.latest is None


def test_rejects_nonfinite_receive_time(gate):
    image, info = message()
    with pytest.raises(ValueError, match="finite monotonic"):
        gate.accept(image, info, received_at=float("nan"))


def test_rejects_camera_info_with_same_revision_label_but_different_digest():
    image, info = message()
    original = CameraFrameGate.camera_info_fingerprint(info)
    gate = CameraFrameGate(CameraStreamConfig(
        "usb-by-id:camera-serial", "overhead_optical", "cal-v3", original
    ))
    info.k[0] += 0.25
    with pytest.raises(ValueError, match="calibration digest"):
        gate.accept(image, info, received_at=1.0)


def test_rejects_replayed_or_out_of_order_capture_timestamp(gate):
    image, info = message()
    gate.accept(image, info, received_at=1.0)
    with pytest.raises(ValueError, match="did not advance"):
        gate.accept(image, info, received_at=1.1)
