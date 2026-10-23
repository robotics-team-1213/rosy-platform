"""Bounded failure facts from the teacher's existing gripper read; no new I/O."""
from dataclasses import asdict
import json


def gripper_failure_evidence(observation, *, position_rad, joint_positions_rad, expected, close_rad, contact_rad,
                             checked_owner_s, max_age_s, phase_id, preceding_command_id):
    try:
        evidence = dict(observation=asdict(observation), position_rad=position_rad,
            joint_positions_rad=dict(joint_positions_rad),
            expected=expected, close_rad=close_rad, contact_rad=contact_rad,
            contact_lower_rad=close_rad+(contact_rad-close_rad)/2,
            contact_upper_rad=contact_rad+.015, checked_owner_s=checked_owner_s,
            max_age_s=max_age_s, phase_id=phase_id, preceding_command_id=preceding_command_id)
        json.dumps(evidence, allow_nan=False)
        return evidence
    except Exception as error:
        # Diagnostics must not replace the original verifier exception or cleanup.
        return {'error': type(error).__name__}
