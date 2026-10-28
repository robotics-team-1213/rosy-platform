"""Load observation registration without granting map, calibration or command authority."""
import os
from pathlib import Path

from pydantic import ValidationError
import yaml

from core_common.protocol.workcell_observations import WorkcellObservationManifest
from fleet.server.workcell_observations import WorkcellObservations


def load_workcell_observations(path, *, environ=None):
    try:
        manifest = WorkcellObservationManifest.model_validate(
            yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except (ValidationError, yaml.YAMLError, UnicodeError):
        raise ValueError("invalid workcell observation manifest") from None
    env = os.environ if environ is None else environ
    tokens = {}
    for cell in manifest.workcells:
        for arm in cell.arms:
            token = env.get(arm.token_env)
            if not isinstance(token, str) or not token:
                raise ValueError(f"observation credential {arm.token_env} is required")
            tokens[arm.source_id] = token
    return WorkcellObservations(manifest, tokens)
