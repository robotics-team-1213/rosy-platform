"""Explicit software rehearsal inputs; they cannot be prepared as hardware demonstrations."""
import time
from collection_profile import normalize


def profile():
    return dict(schema='rosy.omx-collection-profile.v1', enabled=False, workcell_id='rehearsal',
        instance_id='rehearsal', rig_revision='synthetic-rig', calibration_revision='synthetic-cal',
        task='software fixture only', fps=10, max_image_age_s=.5, max_sample_gap_s=.3,
        max_state_age_s=.2, max_reference_age_s=.2, max_skew_s=.1, max_session_s=5., max_frame_jitter_s=.2,
        free_disk_bytes=1024*1024, camera_shapes={r: [32, 32, 3] for r in ('top', 'front')},
        joint_names=['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1'],
        normalization=[[-1., 1.] for _ in range(6)], reach_tolerance_rad=[.01]*6)


def teacher():
    return dict(schema='rosy.omx-collection-teacher.v1', steps=[dict(positions=[.1]*6, duration_s=.35)])


class RehearsalBackend:
    mode = 'rehearsal'
    def __init__(self, config, *, fault='none'):
        self.profile, self.fault = config, fault
        self.started, self.sequence, self.target, self.stopped = None, 0, [0.]*6, False
        self.hardware_connections, self.submissions = 0, 0

    def observe(self):
        self.sequence += 1
        now = time.time_ns()
        bad = self.started is not None
        if bad and self.fault == 'disconnect':
            raise ValueError('injected sensor disconnection')
        condition = 'UNDEREXPOSED' if bad and self.fault == 'dark' else 'NORMAL'
        state_age = 1. if bad and self.fault == 'stale_reference' else 0.
        env = dict(policy='omx-photometric-v3', recorded_ns=now, expires_ns=now+750_000_000,
            run_id='synthetic-rehearsal-run', profile_sha256='a'*64, physical_acceptance=False,
            motion_admitted=False, photometric_ready=condition == 'NORMAL', environment={}, observations={})
        for role in ('top', 'front'):
            env['environment'][role] = dict(state='NORMAL', condition='NORMAL', pending='NORMAL', confirmations=3,
                source_after=0., environment_epoch=1, control_generation=0)
            env['observations'][role] = dict(fresh=True, source_stamp=now/1e9, sequence=self.sequence,
                receipt_age_s=0., source_age_s=0., quality=dict(policy='omx-photometric-v3', condition=condition,
                usable=condition == 'NORMAL', mean_intensity=90., spatial_contrast=20., p5=10., p95=180.,
                dark_fraction=.1, clipped_fraction=.01))
        values = normalize(self.target, self.profile)
        # no_motion: the controller reports success while the joints stay where they started.
        joints = [0.]*6 if self.fault == 'no_motion' else list(self.target)
        return dict(time_ns=now, environment=env, observation_state=values, action=values, joint_positions=joints,
            joint_source_stamp=now/1e9, reference_source_stamp=now/1e9, state_age_s=0., reference_age_s=state_age,
            images={r: dict(data=bytes([self.sequence % 255])*32*32*3, width=32, height=32,
                            source_stamp=now/1e9) for r in ('top', 'front')})

    def submit(self, step, command_id):
        self.started, self.target = time.monotonic(), list(step['positions'])
        self.duration = step['duration_s']
        self.submissions += 1
        return dict(accepted=self.fault != 'reject', command_id=command_id, reason='software_fixture')

    def terminal(self):
        if self.started is None or time.monotonic()-self.started < self.duration:
            return None
        return dict(succeeded=self.fault != 'terminal_failure', source='software_fixture')

    def drain_events(self):
        return []

    def stop(self, reason):
        self.stopped = True
        return dict(hold_requested=True, reason=reason, physical_stop_verified=False, hardware_connections=0)
