"""Explicit SIM caller: preserve original ACT input and return an unadmitted candidate."""
from dataclasses import replace
from act_owner_capture import infer_captured
from rosy.execution.local.omx_policy import PolicyCandidate


def infer_for_owner(engine, session, camera):
    # Keep inference outside the owner's lock; never refresh a queued result's clocks.
    with session._lock:
        lease = session.lease
        doc = session.policy.recheck()
        if engine.metadata != doc:
            raise ValueError('different installed policy')
        with camera.capture() as packet:
            observation = session.capture_inference_input(packet.rgb, packet.metadata)
    result = infer_captured(engine, observation, expected_revision=lease.policy_revision,
                            monotonic=session._clock)
    with session._lock:
        current=session.lease
        if (replace(current,issued_at_ns=lease.issued_at_ns,expires_at_ns=lease.expires_at_ns)!=lease
                or current.issued_at_ns<lease.issued_at_ns or current.expires_at_ns<lease.expires_at_ns):
            raise ValueError('lease or model changed during inference')
        current_doc, _, _=session._guard()
        if current_doc!=doc:
            raise ValueError('lease or model changed during inference')
    return PolicyCandidate(**result.candidate_fields()), result
