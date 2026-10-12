"""Root composition of registry read ports and existing Fleet config; no activation."""
from dataclasses import asdict, fields
import hashlib
import json
from pathlib import Path
import re

from rosy.decision.deliberation.calibration import CalibrationArtifact
from rosy.decision.deliberation.profiles import AdapterCapabilities, ModelProfile, incident_profiles
from rosy.decision.deliberation import canonical


def registry_calibration_config(config, registry, *, domain):
    if (type(config) is not dict or type(domain) is not str
            or any(name in config for name in ('calibration_artifacts', 'approved_artifacts'))
            or any(not callable(getattr(registry, name, None))
                   for name in ('approved_candidate', 'approved_artifacts'))):
        raise ValueError('EXPLICIT_UNCONFIGURED_INCIDENT_REGISTRY_PORTS_REQUIRED')
    if 'profile_workers' in config:
        variants = config['profile_workers']
        if (set(config) - {'profile_workers', 'clock'} or type(variants) not in (tuple, list)
                or not 1 <= len(variants) <= 8 or any(type(v) is not dict
                or 'profile_workers' in v or 'clock' in v for v in variants)):
            raise ValueError('EXPLICIT_PROFILE_WORKER_CONFIGS_REQUIRED')
        return {**config, 'profile_workers': tuple(registry_calibration_config(v, registry, domain=domain)
                                                 for v in variants)}
    profiles = incident_profiles(config.get('profiles'))
    if any(p.calibration_revision is None or domain not in p.domains for p in profiles):
        raise ValueError('EXPLICIT_CALIBRATED_DOMAIN_PROFILES_REQUIRED')
    def artifact(profile):
        candidate = registry.approved_candidate(asdict(profile), domain)
        return CalibrationArtifact(json.dumps(candidate['calibration_report'], sort_keys=True,
                                             separators=(',', ':'), allow_nan=False))
    return {**config, 'calibration_artifacts': artifact, 'approved_artifacts': registry.approved_artifacts}


def _unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs): raise ValueError('DUPLICATE_MANIFEST_FIELD')
    return result


def load_incident_profile_config(source, *, expected_sha256, installed, clock):
    """Bind a deployment-pinned file to existing provider objects without calling them."""
    try:
        if (type(expected_sha256) is not str or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None
                or not callable(clock) or type(installed) not in (tuple, list) or not 1 <= len(installed) <= 8):
            raise ValueError('EXPLICIT_INSTALLED_PROFILE_INPUTS_REQUIRED')
        with Path(source).open('rb') as stream: raw = stream.read(65537)
        if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError('FROZEN_PROFILE_FILE_DIFFERS')
        manifest = json.loads(raw, object_pairs_hook=_unique_fields)
        if (type(manifest) is not dict or set(manifest) != {'schema', 'profile_sets'}
                or manifest['schema'] != 'rosy.incident.profiles/1'
                or type(manifest['profile_sets']) is not list or not 1 <= len(manifest['profile_sets']) <= 8):
            raise ValueError('INVALID_PROFILE_FILE')
        bindings = {}
        for config in installed:
            if type(config) is not dict or 'clock' in config or 'profile_workers' in config:
                raise ValueError('EXPLICIT_INSTALLED_PROFILE_CONFIG_REQUIRED')
            profiles = incident_profiles(config.get('profiles'))
            providers = config.get('providers')
            if type(providers) is not tuple or len(providers) != len(profiles):
                raise ValueError('INSTALLED_PROFILE_PROVIDER_DIFFERS')
            for profile, provider in zip(profiles, providers):
                adapter = getattr(provider, 'adapter', None)
                if (not callable(provider) or type(getattr(provider, 'profile', None)) is not ModelProfile
                        or canonical(asdict(provider.profile)) != canonical(asdict(profile))
                        or type(adapter) is not AdapterCapabilities
                        or any(getattr(adapter, name) != getattr(profile, name) for name in
                               ('provider_kind', 'model_id', 'model_revision', 'adapter', 'schema_version'))
                        or not set(profile.domains) <= set(adapter.domains)
                        or not set(profile.modalities) <= set(adapter.modalities)):
                    raise ValueError('INSTALLED_PROFILE_PROVIDER_DIFFERS')
            key = canonical([asdict(p) for p in profiles])
            if key in bindings: raise ValueError('AMBIGUOUS_INSTALLED_PROFILE_SET')
            bindings[key] = dict(config)
        configs, seen = [], set()
        required = {field.name for field in fields(ModelProfile)}
        for profile_set in manifest['profile_sets']:
            if (type(profile_set) is not list or len(profile_set) not in (1, 2)
                    or any(type(p) is not dict or set(p) != required for p in profile_set)):
                raise ValueError('INVALID_PROFILE_FILE')
            profiles = incident_profiles(tuple(ModelProfile(**p) for p in profile_set))
            key = canonical([asdict(p) for p in profiles])
            if key in seen or key not in bindings: raise ValueError('PROFILE_SET_NOT_UNIQUELY_INSTALLED')
            seen.add(key); configs.append(bindings[key])
        return dict(profile_workers=tuple(configs), clock=clock)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('INCIDENT_PROFILE_INSTALLATION_BINDING_FAILED') from None
