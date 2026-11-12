from test_omx_guarded_native import *



@pytest.mark.parametrize('failure', ['gripper_torque', 'body_tracking'])
def test_body_only_checks_passive_gripper_torque_and_all_body_guards_each_cycle(guard, failure):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
    motion.send(action(leader))
    if failure == 'gripper_torque':
        follower.torque['gripper'] = 1
    else:
        follower.raw['wrist_flex'] += 57
    clock[0] += 0.1
    before = len([e for e in follower.events if e[0] == 'goal'])
    with pytest.raises(ValueError):
        motion.send(action(leader))
    assert len([e for e in follower.events if e[0] == 'goal']) == before
    assert not any(follower.torque.values())


def test_body_only_pre_enable_gripper_read_cannot_extend_freshness_deadline(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
    prepared = motion.prepare(action(leader))
    read = follower.read
    def delayed_read(register, motor, **kwargs):
        if register == 'Torque_Enable' and motor == 'gripper':
            clock[0] += 0.6
        return read(register, motor, **kwargs)
    follower.read = delayed_read
    with pytest.raises(ValueError, match='stale'):
        motion.commit(prepared)
    assert ('on',) not in follower.events and not any(follower.torque.values())


def phased_pair(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0], label='arm_a')
    motion.send(action(leader))
    def step(dt=0.05):
        clock[0] += dt
        sent = motion.send(action(leader))
        follower.raw.update(follower.goals)
        return sent
    return motion, follower, leader, clock, step


def align_phase(step):
    for _ in range(14):
        step()


def test_body_startup_stays_slow_until_all_five_actual_and_command_targets_settle(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    leader.raw['wrist_flex'] += 200
    for _ in range(20):
        step()
    assert not motion.tracking
    assert follower.goals['wrist_flex'] - 2028 <= guard.TICKS_PER_DEGREE + 1
    leader.raw.update({n: follower.raw[n] for n in guard.BODY})
    for _ in range(6):
        step()
    assert not motion.tracking and motion.aligned_since is not None
    leader.raw['elbow_flex'] += 3 * guard.TICKS_PER_DEGREE
    step()
    assert motion.aligned_since is None and not motion.tracking
    leader.raw.update({n: follower.raw[n] for n in guard.BODY})
    align_phase(step)
    assert motion.tracking


def test_live_leader_target_outside_alignment_window_keeps_startup_phase(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    for _ in range(30):
        leader.raw['shoulder_lift'] = follower.raw['shoulder_lift'] + 3 * guard.TICKS_PER_DEGREE
        step()
    assert not motion.tracking and motion.aligned_since is None
    assert abs(motion.velocity['shoulder_lift']) <= guard.TICKS_PER_DEGREE


def test_measured_static_load_residual_allows_handoff_after_continuous_dwell(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    for index in range(12):
        follower.raw['shoulder_lift'] = leader.raw['shoulder_lift'] - 25  # 2.20 degrees
        step()
        if index < 9:
            assert not motion.tracking
    assert motion.tracking


def test_actual_error_above_two_point_five_resets_startup_dwell(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    for _ in range(6):
        step()
    assert motion.aligned_since is not None
    follower.raw['shoulder_lift'] = leader.raw['shoulder_lift'] - 29  # 2.55 degrees
    step()
    assert motion.aligned_since is None and not motion.tracking
    for _ in range(8):
        step()
    assert not motion.tracking
    align_phase(step)
    assert motion.tracking


def test_command_not_within_half_degree_prevents_startup_handoff(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    for _ in range(20):
        leader.raw['shoulder_lift'] = motion.command['shoulder_lift'] + 7  # 0.62 degrees
        step()
    assert motion.aligned_since is None and not motion.tracking


def test_tracking_phase_slews_to_ten_degrees_per_second_and_prints_once(guard, capsys):
    motion, follower, leader, _, step = phased_pair(guard)
    align_phase(step)
    assert motion.tracking
    leader.raw['wrist_roll'] += 30 * guard.TICKS_PER_DEGREE
    previous_velocity, previous_goal = motion.velocity['wrist_roll'], follower.goals['wrist_roll']
    for _ in range(30):
        step()
        velocity, goal = motion.velocity['wrist_roll'], follower.goals['wrist_roll']
        assert abs(velocity) <= 10 * guard.TICKS_PER_DEGREE + 1e-8
        assert abs(velocity - previous_velocity) <= 10 * guard.TICKS_PER_DEGREE * 0.05 + 1e-8
        assert abs(goal - previous_goal) <= 10 * guard.TICKS_PER_DEGREE * 0.05 + 1
        previous_velocity, previous_goal = velocity, goal
    assert motion.velocity['wrist_roll'] == pytest.approx(10 * guard.TICKS_PER_DEGREE)
    output = capsys.readouterr().out
    changes = [line for line in output.splitlines() if ': aligned; body tracking limit' in line]
    assert len(changes) == 1 and changes[0].startswith('arm_a:') and '10 deg/s' in changes[0]


def test_moving_target_reversal_brakes_without_instant_velocity_flip(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    align_phase(step)
    leader.raw['wrist_roll'] += 40 * guard.TICKS_PER_DEGREE
    for _ in range(24):
        step()
    assert motion.velocity['wrist_roll'] > 0
    leader.raw['wrist_roll'] = follower.raw['wrist_roll'] - 20 * guard.TICKS_PER_DEGREE
    previous = motion.velocity['wrist_roll']
    step()
    assert 0 < motion.velocity['wrist_roll'] < previous
    for _ in range(30):
        before = motion.velocity['wrist_roll']
        step()
        assert abs(motion.velocity['wrist_roll'] - before) <= 10 * guard.TICKS_PER_DEGREE * 0.05 + 1e-8
    assert motion.velocity['wrist_roll'] < 0 and motion.tracking


def test_slew_caps_long_dt_and_zero_dt_never_moves_or_changes_velocity(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    align_phase(step)
    leader.raw['wrist_roll'] += 30 * guard.TICKS_PER_DEGREE
    step(0.4)
    assert motion.velocity['wrist_roll'] == pytest.approx(guard.TICKS_PER_DEGREE)
    command, velocity = dict(motion.command), dict(motion.velocity)
    step(0)
    assert motion.command == command and motion.velocity == velocity


def test_fast_slew_candidate_outside_calibration_fails_before_goal_write(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    follower.raw['wrist_roll'] = leader.raw['wrist_roll'] = motion.command['wrist_roll'] = 4094
    motion.tracking = True
    motion.velocity['wrist_roll'] = 10 * guard.TICKS_PER_DEGREE
    before = len([e for e in follower.events if e[0] == 'goal'])
    with pytest.raises(ValueError, match='range'):
        step()
    assert len([e for e in follower.events if e[0] == 'goal']) == before
    assert not any(follower.torque.values())


def test_five_degree_tracking_guard_and_backward_clock_still_stop_fast_phase(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    align_phase(step)
    assert motion.tracking
    follower.raw['wrist_flex'] += 57
    with pytest.raises(ValueError, match='following error'):
        step()
    assert not any(follower.torque.values())
    motion, follower, leader, clock, step = phased_pair(guard)
    align_phase(step)
    with pytest.raises(ValueError, match='stale'):
        step(-0.1)
    assert not any(follower.torque.values())


def test_alignment_diagnostic_reports_both_blocking_joints_at_most_once_per_second(guard, capsys):
    motion, follower, leader, _, step = phased_pair(guard)
    leader.raw['shoulder_lift'] += 80
    leader.raw['wrist_flex'] += 100
    follower.raw['wrist_flex'] += 25
    for _ in range(25):
        step()
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert all('arm_a' in line and 'phase=aligning' in line for line in lines)
    assert 'actual_joint=shoulder_lift' in lines[0] and 'actual=2028' in lines[0] and 'target=2108' in lines[0]
    assert 'Present_PWM=0' in lines[0] and 'PWM_Limit=330' in lines[0]
    limits = [e[2] for e in follower.events if e[:2] == ('read', 'PWM_Limit')]
    assert sorted(limits) == sorted(guard.BODY)  # actual limits cached once, never passive gripper
    assert 'command_joint=wrist_flex' in lines[0] and 'command=2028' in lines[0] and 'target=2128' in lines[0]
    assert not motion.tracking


def test_slow_alignment_pwm_read_cannot_send_stale_body_command(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    read = follower.read
    def slow_read(register, motor, **kwargs):
        if register == 'Present_PWM':
            clock[0] += 0.6
        return read(register, motor, **kwargs)
    follower.read = slow_read
    before = len([e for e in follower.events if e[0] == 'goal'])
    with pytest.raises(ValueError, match='stale'):
        step()
    assert len([e for e in follower.events if e[0] == 'goal']) == before
    assert not any(follower.torque.values())


def effort_read(bus, *, pwm=300, limit=330):
    original = bus.read
    def read(register, motor, **kwargs):
        value = original(register, motor, **kwargs)
        if register == 'Present_PWM':
            return pwm if motor == 'shoulder_lift' else 0
        return limit if register == 'PWM_Limit' else value
    bus.read = read


def test_sustained_loaded_tracking_error_latches_before_firmware_overload(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    effort_read(follower, pwm=-300)
    for _ in range(10):
        follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - 25
        step()
    with pytest.raises(ValueError, match=r'shoulder_lift.*overload risk.*hold timed out.*PWM=-300.*limit=330.*duration='):
        for _ in range(120):
            follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - 25
            step()
    assert not any(follower.torque.values()) and motion.failed


def overload_into_hold(guard, pwm=-300):
    """A shoulder_lift stalled 25 ticks behind at the cap until the guard takes its one hold."""
    motion, follower, leader, clock, step = phased_pair(guard)
    effort_read(follower, pwm=pwm)
    while 'shoulder_lift' not in motion.held:
        follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - 25
        step()
        assert not motion.failed
    return motion, follower, leader, clock, step


def test_overload_holds_with_torque_on_and_the_goal_set_to_present_once(guard):
    motion, follower, leader, clock, step = overload_into_hold(guard)
    held_goal = motion.command['shoulder_lift']
    assert held_goal == follower.raw['shoulder_lift'] and all(follower.torque[n] for n in guard.BODY)
    for _ in range(20):  # the joint sags under the cap (3.5 deg); the goal must not chase it down (2026-11-09 review)
        follower.raw['shoulder_lift'] -= 2
        step()
    assert motion.command['shoulder_lift'] == held_goal and not motion.failed


def test_a_frozen_hold_still_at_the_cap_times_out_on_pwm_alone(guard):
    # the goal sits on present, so the error-gated overload test reads 0 error and would never fire
    motion, follower, leader, clock, step = overload_into_hold(guard)
    started = clock[0]
    with pytest.raises(ValueError, match=r'shoulder_lift: overload risk; hold timed out at PWM=-300 limit=330'):
        for _ in range(200):
            follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift'])
            step()
    assert clock[0] - started == pytest.approx(guard.HOLD_S, abs=0.3)
    assert not any(follower.torque.values()) and motion.failed


def test_a_hold_never_frees_itself_and_after_release_a_second_overload_ends_the_session(guard):
    motion, follower, leader, clock, step = overload_into_hold(guard)
    held_goal = motion.command['shoulder_lift']
    effort_read(follower, pwm=0)  # off the cap, same target: the joint must not resume into the stall (2026-11-09 review)
    for _ in range(40):
        follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift'])
        step()
    assert 'shoulder_lift' in motion.held and motion.command['shoulder_lift'] == held_goal and not motion.failed
    motion.release_hold()
    assert not motion.held
    effort_read(follower, pwm=-300)
    with pytest.raises(ValueError, match='overload risk.*second overload on this joint'):
        for _ in range(60):
            follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - 25
            step()
    assert not any(follower.torque.values())


@pytest.mark.parametrize('shed_load', [False, True])
def test_a_hold_freezes_every_joint_unless_the_runner_sheds_load(guard, shed_load):
    motion, follower, leader, clock, step = overload_into_hold(guard)
    motion.shed_load = shed_load
    effort_read(follower, pwm=0)
    elbow = motion.command['elbow_flex']
    for _ in range(10):  # the runner's target keeps moving on another joint
        leader.raw['elbow_flex'] += 4
        follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift'])
        follower.raw['elbow_flex'] = int(motion.command['elbow_flex'])
        step()
    assert (motion.command['elbow_flex'] != elbow) == shed_load
    assert 'shoulder_lift' in motion.held and not motion.failed


def test_a_held_joint_that_warms_ends_the_session(guard):
    motion, follower, leader, clock, step = overload_into_hold(guard)
    follower.temps['shoulder_lift'] += guard.HOLD_TEMP_RISE_C
    with pytest.raises(ValueError, match='held joint warmed'):
        for _ in range(10):
            step()
    assert not any(follower.torque.values())


def test_an_error_inside_the_hold_watch_still_turns_torque_off(guard):
    motion, follower, leader, clock, step = overload_into_hold(guard)
    read = follower.read
    def broken(register, motor, **kwargs):
        if register == 'Present_Temperature':
            raise ConnectionError('temperature read failed')
        return read(register, motor, **kwargs)
    follower.read = broken
    with pytest.raises(ConnectionError):
        for _ in range(10):
            step()
    assert not any(follower.torque.values()) and motion.failed


def test_effort_guard_resets_on_clear_and_ignores_passive_gripper(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    effort_read(follower)
    for index in range(50):
        follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - (0 if index % 12 >= 8 else 25)
        follower.raw['gripper'] = 0
        step()
    assert not motion.failed


@pytest.mark.parametrize('limit', [0, 401, float('nan')])
def test_body_invalid_actual_pwm_limit_refuses_before_enable(guard, limit):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    effort_read(follower, limit=limit)
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
    with pytest.raises(ValueError, match='PWM_Limit'):
        motion.send(action(leader))
    assert ('on',) not in follower.events


def test_xl430_joints_admit_600_and_the_xl330_wrist_still_refuses_above_400(guard):
    for limits, admitted in (({'shoulder_lift': 600, 'elbow_flex': 600}, True), ({'shoulder_lift': 601}, False),
                             ({'shoulder_lift': 600, 'wrist_flex': 401}, False)):
        follower, leader, clock = Bus(), Bus(leader=True), [10.0]
        effort_read(follower)
        read = follower.read
        follower.read = lambda register, motor, _read=read, _l=limits, **kw: (
            _l.get(motor, 330) if register == 'PWM_Limit' else _read(register, motor, **kw))
        motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
        if admitted:
            motion.send(action(leader))
            assert motion.pwm_limits['shoulder_lift'] == 600
        else:
            with pytest.raises(ValueError, match='PWM_Limit'):
                motion.send(action(leader))
            assert ('on',) not in follower.events


def test_initial_alignment_deadline_is_fixed_by_admitted_gap_not_later_targets(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    for _ in range(95):
        leader.raw['shoulder_lift'] = motion.command['shoulder_lift'] + 40
        step()
    assert not motion.tracking
    with pytest.raises(ValueError, match='alignment deadline'):
        for _ in range(10):
            step()
    assert not any(follower.torque.values())


def test_large_admitted_gap_gets_slow_alignment_time_budget(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    leader.raw['wrist_roll'] += 900
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
    motion.send(action(leader))
    assert motion.alignment_deadline == pytest.approx(15 + 900 / guard.TICKS_PER_DEGREE)


@pytest.mark.parametrize('body_only', [False, True])
@pytest.mark.parametrize('error_ticks,pwm,stop', [(23, 297, True), (22, 330, False), (25, 296, False)])
def test_effort_boundaries_apply_to_all_commanded_body_modes(guard, body_only, error_ticks, pwm, stop):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, body_only=body_only, clock=lambda: clock[0])
    motion.send(action(leader))
    effort_read(follower, pwm=pwm)
    def run():
        for _ in range(27):  # the overload test fires within 1 s, the hold then times out after HOLD_S
            clock[0] += 0.2
            follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - error_ticks
            motion.send(action(leader))
    if stop:
        with pytest.raises(ValueError, match='overload risk'):
            run()
        assert not any(follower.torque.values())
    else:
        run()
        assert not motion.failed


def test_full_mode_slow_effort_sample_cannot_write_or_credit_timer(guard):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    read = follower.read
    def slow_read(register, motor, **kwargs):
        if register == 'Present_PWM':
            clock[0] += 0.11
        return read(register, motor, **kwargs)
    follower.read = slow_read
    before = len([e for e in follower.events if e[0] == 'goal'])
    with pytest.raises(ValueError, match='stale'):
        motion.send(action(leader))
    assert len([e for e in follower.events if e[0] == 'goal']) == before
    assert not any(follower.torque.values())


