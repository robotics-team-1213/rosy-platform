"""Explicit SIM caller: preserve original ACT input and return an unadmitted candidate."""
from dataclasses import replace
from time import perf_counter_ns, sleep
from act_owner_capture import infer_captured
from rosy.execution.local.omx_policy import PolicyCandidate


def infer_for_owner(engine, session, camera, *, timings=None, require_live=None):
    # Keep inference outside the owner's lock; never refresh a queued result's clocks.
    started=perf_counter_ns()
    # Let joint intake advance during the initial installed-file verification.
    doc = session.policy.recheck()
    if engine.metadata != doc:
        raise ValueError('different installed policy')
    checked=perf_counter_ns()
    budget_ns=doc['timing']['max_observation_age_ns']
    capture_deadline=started+budget_ns
    capture_times=dict(initial_lock_wait=0.,camera_lock_wait=0.,guarded_input_capture=0.,capture_retry_wait=0.)
    while True:
        if require_live is not None:require_live()
        waiting=perf_counter_ns()
        with session._lock:
            locked=perf_counter_ns()
            lease = session.lease
            with camera.capture() as packet:
                captured=perf_counter_ns()
                observation = session.capture_inference_input(packet.rgb, packet.metadata)
            age=int(session._clock()*1e9)-min(observation.observed_at_ns,observation.camera_received_at_ns)
        frozen=perf_counter_ns()
        capture_times['initial_lock_wait']+=(locked-waiting)/1e6
        capture_times['camera_lock_wait']+=(captured-locked)/1e6
        capture_times['guarded_input_capture']+=(frozen-captured)/1e6
        # Reserve time for computation and final admission before creating a candidate.
        # The actor can bound acquisition while original input age stays unchanged.
        if require_live is not None:require_live()
        elif frozen>=capture_deadline:raise TimeoutError('fresh inference capture margin unavailable')
        if 0<=age<=budget_ns//4:break
        sleep(.01)  # Release both locks so real joint/camera intake can advance.
        capture_times['capture_retry_wait']+=(perf_counter_ns()-frozen)/1e6
    result = infer_captured(engine, observation, expected_revision=lease.policy_revision,
                            monotonic=session._clock)
    inferred=perf_counter_ns()
    with session._lock:
        relocked=perf_counter_ns()
        current=session.lease
        if (replace(current,issued_at_ns=lease.issued_at_ns,expires_at_ns=lease.expires_at_ns)!=lease
                or current.issued_at_ns<lease.issued_at_ns or current.expires_at_ns<lease.expires_at_ns):
            raise ValueError('lease or model changed during inference')
        # This is an unadmitted proposal; submit/calibration performs the full final guard.
    finished=perf_counter_ns()
    if require_live is not None:require_live()
    if timings is not None:
        timings.update(capture_times,capture_selected_input_age=age/1e6,
            installed_binding=(checked-started)/1e6,
            numerical_inference=(inferred-frozen)/1e6,
            final_lock_wait=(relocked-inferred)/1e6,lease_context_check=(finished-relocked)/1e6)
    return PolicyCandidate(**result.candidate_fields()), result
