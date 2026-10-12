"""Root composition of registry read ports and existing Fleet config; no activation."""
from dataclasses import asdict
import json

from rosy.decision.deliberation.calibration import CalibrationArtifact
from rosy.decision.deliberation.profiles import incident_profiles


def registry_calibration_config(config, registry, *, domain):
    if (type(config) is not dict or type(domain) is not str
            or any(name in config for name in ('calibration_artifacts', 'approved_artifacts'))
            or any(not callable(getattr(registry, name, None))
                   for name in ('approved_candidate', 'approved_artifacts'))):
        raise ValueError('EXPLICIT_UNCONFIGURED_INCIDENT_REGISTRY_PORTS_REQUIRED')
    profiles = incident_profiles(config.get('profiles'))
    if any(p.calibration_revision is None or domain not in p.domains for p in profiles):
        raise ValueError('EXPLICIT_CALIBRATED_DOMAIN_PROFILES_REQUIRED')
    def artifact(profile):
        candidate = registry.approved_candidate(asdict(profile), domain)
        return CalibrationArtifact(json.dumps(candidate['calibration_report'], sort_keys=True,
                                             separators=(',', ':'), allow_nan=False))
    return {**config, 'calibration_artifacts': artifact, 'approved_artifacts': registry.approved_artifacts}
