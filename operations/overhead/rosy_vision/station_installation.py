"""Strict non-secret station profiles and explicit existing-worker composition."""
import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from core_common.protocol.station_charging import Contract, Identifier, Nonnegative, Number, Pose2D, Positive
from . import protocol
from .station_lens import StationLensCalibration
from .station_map_worker import StationMapCalibration, create_station_map_worker
from .station_observation import StationCameraCalibration
from .station_worker import create_station_worker

EnvironmentName = Annotated[str, Field(pattern=r'^[A-Z_][A-Z0-9_]*$')]


class RelativeCalibration(Contract):
    station_id: Identifier
    source_id: Identifier
    source_epoch: Identifier
    revision: Identifier
    marker_id: Annotated[int, Field(strict=True, ge=0)]
    marker_side_m: Positive
    marker_mount: Pose2D
    image_to_station: tuple[Number, ...]
    plane: Literal['robot_marker']
    lens_rectified: bool
    approved: bool
    uncertainty_m: Nonnegative
    uncertainty_rad: Nonnegative

    def measurement(self):
        return StationCameraCalibration(**(self.model_dump() | {'marker_mount': self.marker_mount}))

    @model_validator(mode='after')
    def approved_plane(self):
        self.measurement()
        return self


class CameraSource(Contract):
    phone_token_env: EnvironmentName
    token_env: EnvironmentName
    fleet_base_url: str
    max_age_s: Positive
    lens: StationLensCalibration

    @model_validator(mode='after')
    def installed_scope(self):
        url = urlsplit(self.fleet_base_url)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment or url.port == 0):
            raise ValueError('STATION_FLEET_URL_INVALID')
        if not protocol.SOURCE_PATTERN.fullmatch(self.calibration.source_id):
            raise ValueError('STATION_CAMERA_SOURCE_INVALID')
        if any(getattr(self.calibration, name) != getattr(self.lens, name)
               for name in ('source_id', 'source_epoch', 'revision')):
            raise ValueError('STATION_LENS_INSTALLATION_SCOPE_MISMATCH')
        return self


class RelativeSource(CameraSource):
    kind: Literal['relative']
    calibration: RelativeCalibration
    robot_id: Identifier


class MapSource(CameraSource):
    kind: Literal['map']
    calibration: StationMapCalibration
    robot_id: None = None


class StationVisionProfile(Contract):
    version: Annotated[int, Field(strict=True, ge=1, le=1)]
    sources: Annotated[tuple[Annotated[RelativeSource | MapSource, Field(discriminator='kind')], ...],
                       Field(min_length=1, max_length=2)]

    @model_validator(mode='after')
    def one_station(self):
        if (len({row.calibration.station_id for row in self.sources}) != 1
                or len({row.calibration.source_id for row in self.sources}) != len(self.sources)
                or len({row.kind for row in self.sources}) != len(self.sources)):
            raise ValueError('STATION_CAMERA_INSTALLATION_AMBIGUOUS')
        return self


@dataclass(frozen=True)
class InstalledCameraSource:
    profile: RelativeSource | MapSource
    phone_token: SecretStr
    token: SecretStr

    def create_worker(self, *, ingest, publisher, clock=time.time):
        profile = type(self.profile).model_validate(self.profile.model_dump())
        lens = profile.lens
        class GeometryIngest:
            def latest_frame(self, source):
                frame = ingest.latest_frame(source)
                if frame is None:
                    return None
                header = copy.copy(frame.header)
                if any(type(getattr(header, key, None)) is not int or getattr(header, key) != getattr(lens, key)
                       for key in ('width', 'height', 'rotation_deg')):
                    return None
                return SimpleNamespace(header=header, jpeg=frame.jpeg,
                    captured_at=frame.captured_at, received_at=frame.received_at)
        common = dict(ingest=GeometryIngest(), rectify=lens.rectifier(), publisher=publisher,
                      clock=clock, max_age_s=profile.max_age_s)
        if profile.kind == 'relative':
            return create_station_worker(calibration=profile.calibration.measurement(),
                robot_id=profile.robot_id, **common)
        return create_station_map_worker(calibration=profile.calibration, **common)


@dataclass(frozen=True)
class StationInstallation:
    sources: tuple[InstalledCameraSource, ...]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('STATION_INSTALLATION_DUPLICATE_KEY')
        result[key] = value
    return result


def load_station_installation(path, *, environ=None):
    try:
        text = Path(path).read_text(encoding='utf-8')
        json.loads(text, object_pairs_hook=_unique_object)
        profile = StationVisionProfile.model_validate_json(text, strict=True)
        env = os.environ if environ is None else environ
        used, installed = set(), []
        for row in profile.sources:
            values = [env.get(row.phone_token_env), env.get(row.token_env)]
            for value in values:
                if not isinstance(value, str) or not value.strip() or value in used:
                    raise ValueError('STATION_SOURCE_CREDENTIAL_REQUIRED_OR_REUSED')
                used.add(value)
            installed.append(InstalledCameraSource(row, SecretStr(values[0]), SecretStr(values[1])))
        return StationInstallation(tuple(installed))
    except (OSError, UnicodeError, ValueError, TypeError):
        # ValidationErrors include rejected input values; never expose inline secrets.
        raise ValueError('STATION_INSTALLATION_INVALID') from None
