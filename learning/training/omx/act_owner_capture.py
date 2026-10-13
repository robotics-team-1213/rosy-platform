"""Pure ACT study input boundary. No owner imports, callbacks or execution."""
from act_inference import ACTInference, InferenceObservation


def infer_captured(engine, observation, *, expected_revision, monotonic):
    """Return original queue provenance from already frozen input, never a grant."""
    if (type(engine) is not ACTInference or type(observation) is not InferenceObservation
            or engine._clock is not monotonic
            or engine.metadata['revision'] != expected_revision):
        raise ValueError('exact ACT/input/revision with same caller clock required')
    return engine.infer(observation)
