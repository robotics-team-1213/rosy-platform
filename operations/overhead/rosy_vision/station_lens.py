"""Installed measurement lens transform; viewer adjustments never enter this path."""
from typing import Annotated, Literal

import cv2
import numpy as np
from pydantic import Field, model_validator

from core_common.protocol.station_charging import Contract, Identifier, Number


class StationLensCalibration(Contract):
    source_id: Identifier
    source_epoch: Identifier
    revision: Identifier
    approved: bool
    model: Literal['pinhole']
    width: Annotated[int, Field(strict=True, ge=32, le=8192)]
    height: Annotated[int, Field(strict=True, ge=32, le=8192)]
    rotation_deg: Annotated[int, Field(strict=True)]
    matrix: tuple[Number, ...]
    distortion: tuple[Number, Number, Number, Number, Number]

    @model_validator(mode='after')
    def measured_intrinsics(self):
        if self.approved is not True or self.rotation_deg not in (0, 90, 180, 270) or len(self.matrix) != 9:
            raise ValueError('STATION_LENS_MATRIX_INVALID')
        k = np.asarray(self.matrix).reshape(3, 3)
        if (k[0, 0] <= 0 or k[1, 1] <= 0 or k[0, 1] != 0 or k[1, 0] != 0
                or tuple(k[2]) != (0., 0., 1.)
                or not 0 <= k[0, 2] < self.width or not 0 <= k[1, 2] < self.height):
            raise ValueError('STATION_LENS_MATRIX_INVALID')
        return self

    def rectifier(self):
        # Revalidate copies/constructed models before building an installed transform.
        cal = StationLensCalibration.model_validate(self.model_dump())
        k = np.asarray(cal.matrix).reshape(3, 3)
        x, y = cv2.initUndistortRectifyMap(k, np.asarray(cal.distortion), None, k,
            (cal.width, cal.height), cv2.CV_32FC1)
        valid = (np.isfinite(x) & np.isfinite(y) & (x >= 0) & (y >= 0)
                 & (x <= cal.width-1) & (y <= cal.height-1))
        x, y = np.where(valid, x, -1).astype(np.float32), np.where(valid, y, -1).astype(np.float32)

        def rectify(jpeg):
            image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None or image.shape != (cal.height, cal.width):
                raise ValueError('STATION_LENS_CAPTURE_GEOMETRY_MISMATCH')
            measured = cv2.remap(image, x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=255)
            ok, encoded = cv2.imencode('.jpg', measured)
            if not ok:
                raise ValueError('STATION_LENS_ENCODING_FAILED')
            return encoded.tobytes()
        return rectify
