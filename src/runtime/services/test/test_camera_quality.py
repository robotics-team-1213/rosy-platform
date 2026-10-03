"""Raw exposure quality is display evidence and blocks camera-driven recovery."""
import pytest
from core_features.vision import VisionFrameStore, accept_preview
from core_features.line_follow import LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation


@pytest.mark.parametrize('reason', ['low_light', 'overexposed'])
def test_preview_quality_follows_its_jpeg_and_expires(reason):
    store = VisionFrameStore()
    metadata = accept_preview('jpeg; quality_valid=false; quality_reason=' + reason)
    store.publish(b'\xff\xd8\xff\xd9', captured_at=100, received_at=10, frame_id='front', **metadata)
    assert store.status(now=10.5)['available']
    assert store.status(now=10.5)['quality'] == dict(valid=False, reason=reason)
    assert store.status(now=12.01)['quality'] is None
    store.publish(b'\xff\xd8\xff\xd9', captured_at=101, received_at=11, frame_id='front', source='front')
    assert store.status(now=11)['quality'] is None  # legacy frame clears older low-light report


@pytest.mark.parametrize('suffix', ['quality_valid=0; quality_reason=low_light',
    'quality_valid=false; quality_reason=obstacle', 'quality_reason=low_light'])
def test_malformed_quality_does_not_invent_a_low_light_report(suffix):
    assert accept_preview('jpeg; '+suffix).get('quality') is None


@pytest.mark.parametrize('reason', ['low_light', 'overexposed'])
def test_camera_invalid_exposure_prevents_obstacle_backoff_and_latches_loss(reason):
    class Events:
        def publish(self, *args, **kwargs): pass
    manager = LineFollowManager(Events(), clock=lambda: 10.)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, 10., False, None, 0.,
                                    quality_reason=reason), received_at=10., source_now=10.)
    manager.observe_clearance(.1, received_at=10.)
    def recovery_must_not_run(_now):
        raise AssertionError('low-light must not authorize obstacle recovery')
    manager._obstacle_hold = recovery_must_not_run
    decision = manager.tick(10.1)
    assert (decision.linear, decision.angular) == (0., 0.)
    assert manager.status().reason == 'camera_' + reason
    assert manager.tick(13.1).linear == 0.
    assert manager.status().state == 'LOST'


@pytest.mark.parametrize('reason', ['low_light', 'overexposed'])
def test_invalid_exposure_marker_cannot_coexist_with_visible_lane_or_ir(reason):
    with pytest.raises(ValueError):
        LineObservation(LineFollowMode.CAMERA_LINE, 1., True, 0., .9, quality_reason=reason)
    with pytest.raises(ValueError):
        LineObservation(LineFollowMode.IR_LINE, 1., False, None, 0., quality_reason=reason)


@pytest.mark.parametrize('reason', ['low_light', 'overexposed'])
def test_invalid_exposure_lost_never_enters_recovery_with_backoff_guards_satisfied(reason):
    class Events:
        def publish(self, *args, **kwargs): pass
    config = LineFollowConfig(recovery_local_enabled=True, body_lidar_x_m=-.017,
                             body_rear_x_m=-.076, body_rotation_radius_m=.08257)
    manager = LineFollowManager(Events(), config=config, clock=lambda: 0.)
    manager.bind_recovery(console_linked=lambda: False, calibration_active=lambda: False,
                          linear_ceiling=lambda: .15, preview_seq=lambda: 42)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    for i in range(60):
        t = i / 10.
        manager.observe_clearance(.5, received_at=t)
        manager.observe_body_points([(.5, 0.), (-.359, 0.)], range_min=0., received_at=t)
        manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, t, False, None, 0.,
                                        quality_reason=reason), received_at=t, source_now=t)
        decision = manager.tick(t + .01)
        assert (decision.linear, decision.angular) == (0., 0.)
        assert manager.status().state != 'RECOVERING'
    assert manager.status().state == 'LOST'


@pytest.mark.parametrize('reason', ['low_light', 'overexposed'])
def test_invalid_frame_cancels_active_backoff_and_rejects_precomputed_motion(reason):
    class Events:
        def publish(self, *args, **kwargs): pass
    config = LineFollowConfig(recovery_local_enabled=True, body_lidar_x_m=-.017,
                             body_rear_x_m=-.076, body_rotation_radius_m=.08257)
    manager = LineFollowManager(Events(), config=config, clock=lambda: 0.)
    manager.bind_recovery(console_linked=lambda: False, calibration_active=lambda: False,
                          linear_ceiling=lambda: .15)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, 0., False, None, 0.),
                    received_at=0., source_now=0.)
    manager.tick(0.)
    manager.observe_body_points([], range_min=.03, received_at=3.1)
    backing = manager.tick(3.1)
    assert backing.linear < 0. and manager.status().state == 'RECOVERING'
    manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, 3.1, False, None, 0.,
                                    quality_reason=reason), received_at=3.1, source_now=3.1)
    applied = []
    assert not manager.apply_if_current(backing, applied.append)
    assert not applied
    stopped = manager.tick(3.11)
    assert (stopped.linear, stopped.angular) == (0., 0.)
    assert manager.status().state == 'LOST'
    assert manager._recovery.stuck_id is None
