"""Explicit SIM caller: preserve original ACT input and return an unadmitted candidate."""
from act_owner_capture import infer_captured
from rosy.execution.local.omx_policy import PolicyCandidate


def infer_for_owner(engine, session, packet):
    # Keep inference outside the owner's lock; never refresh a queued result's clocks.
    with session._lock:
        lease = session.lease
        doc = session.policy.recheck()
        if engine.metadata != doc:
            raise ValueError('different installed policy')
        observation = session.capture_inference_input(packet.rgb, packet.metadata)
    result = infer_captured(engine, observation, expected_revision=lease.policy_revision,
                            monotonic=session._clock)
    with session._lock:
        if session.lease is not lease or session.policy.recheck() != doc:
            raise ValueError('lease or model changed during inference')
    return PolicyCandidate(**result.candidate_fields()), result
