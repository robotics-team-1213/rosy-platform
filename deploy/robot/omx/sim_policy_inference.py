"""Explicit SIM caller: preserve original ACT input and return an unadmitted candidate."""
from dataclasses import replace
from time import perf_counter_ns
from act_owner_capture import infer_captured
from rosy.execution.local.omx_policy import PolicyCandidate


def infer_for_owner(engine, session, camera, *, timings=None):
    # Keep inference outside the owner's lock; never refresh a queued result's clocks.
    started=perf_counter_ns()
    with session._lock:
        locked=perf_counter_ns()
        lease = session.lease
        doc = session.policy.recheck()
        if engine.metadata != doc:
            raise ValueError('different installed policy')
        checked=perf_counter_ns()
        with camera.capture() as packet:
            captured=perf_counter_ns()
            observation = session.capture_inference_input(packet.rgb, packet.metadata)
    frozen=perf_counter_ns()
    result = infer_captured(engine, observation, expected_revision=lease.policy_revision,
                            monotonic=session._clock)
    inferred=perf_counter_ns()
    with session._lock:
        relocked=perf_counter_ns()
        current=session.lease
        if (replace(current,issued_at_ns=lease.issued_at_ns,expires_at_ns=lease.expires_at_ns)!=lease
                or current.issued_at_ns<lease.issued_at_ns or current.expires_at_ns<lease.expires_at_ns):
            raise ValueError('lease or model changed during inference')
        current_doc, _, _=session._guard()
        if current_doc!=doc:
            raise ValueError('lease or model changed during inference')
    finished=perf_counter_ns()
    if timings is not None:
        stamps=(started,locked,checked,captured,frozen,inferred,relocked,finished)
        timings.update(zip(('initial_lock_wait','installed_binding','camera_lock_wait',
            'guarded_input_capture','numerical_inference','final_lock_wait','final_guard'),
            ((end-begin)/1e6 for begin,end in zip(stamps,stamps[1:]))))
    return PolicyCandidate(**result.candidate_fields()), result
