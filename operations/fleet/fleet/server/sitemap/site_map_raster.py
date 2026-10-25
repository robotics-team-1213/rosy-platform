"""Normalized raster reference geometry; source pixels never imply navigable roads."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import sys
import warnings

from core_common.protocol.site_drawing import RasterDrawingTransform
from fleet.server.site_map_projection import DrawingLimitError, MAX_SOURCE_BYTES, canonical

RASTER_VERSION = 'rosy.raster_projection/1'
MAX_PIXELS = 16_000_000
MAX_AXIS = 8192


def _image(path):
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Path(path).open('rb') as stream:
                data = stream.read(MAX_SOURCE_BYTES + 1)
            if not data or len(data) > MAX_SOURCE_BYTES:
                raise DrawingLimitError('raster source exceeds 16 MiB')
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('PNG', 'JPEG') or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('only single-frame PNG and JPEG are supported')
                width, height = image.size
                if max(width, height) > MAX_AXIS or width * height > MAX_PIXELS:
                    raise DrawingLimitError('raster dimensions exceed limits')
                format_name = image.format.lower()
                oriented = ImageOps.exif_transpose(image).convert('RGBA')
                background = Image.new('RGBA', oriented.size, 'white')
                result = Image.alpha_composite(background, oriented).convert('RGB')
                result.info.clear()
                return data, format_name, result
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError('invalid raster source') from exc


def normalized_png(path: Path) -> bytes:
    _, _, image = _image(path)
    output = io.BytesIO()
    image.save(output, format='PNG')
    if output.tell() > MAX_SOURCE_BYTES:
        raise DrawingLimitError('normalized raster exceeds 16 MiB')
    return output.getvalue()


def inspect_raster(path: Path) -> dict:
    data, format_name, image = _image(path)
    return {'asset_sha256': hashlib.sha256(data).hexdigest(), 'format': format_name,
            'width_px': image.width, 'height_px': image.height}


def pixel_to_map(point, transform: RasterDrawingTransform):
    x = (point[0] - transform.source_origin_px[0]) * transform.meters_per_pixel
    y = (transform.source_origin_px[1] - point[1]) * transform.meters_per_pixel
    c, s = math.cos(transform.heading_rad), math.sin(transform.heading_rad)
    result = [transform.map_origin_m[0] + c * x - s * y, transform.map_origin_m[1] + s * x + c * y]
    if any(not math.isfinite(v) or abs(v) > 1000 for v in result):
        raise ValueError('registered raster exceeds map bounds')
    return [0.0 if v == 0 else v for v in result]


def project_raster(path: Path, transform: RasterDrawingTransform) -> dict:
    info = inspect_raster(path)
    width, height = info['width_px'], info['height_px']
    if not (0 <= transform.source_origin_px[0] <= width and 0 <= transform.source_origin_px[1] <= height):
        raise ValueError('pixel origin is outside normalized raster')
    corners = [pixel_to_map(p, transform) for p in ((0, 0), (width, 0), (0, height), (width, height))]
    body = {**info, 'kind': 'raster', 'transform': transform.model_dump(mode='json'), 'segments': [],
            'render_sha256': hashlib.sha256(normalized_png(path)).hexdigest(),
            'bounds_m': [[min(p[a] for p in corners) for a in (0, 1)],
                         [max(p[a] for p in corners) for a in (0, 1)]]}
    return {'projection_sha256': hashlib.sha256(canonical({'version': RASTER_VERSION, **body})).hexdigest(), **body}


def main():
    """One bounded request, no model framework or external inference dependency."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        request = json.load(sys.stdin)
        path = Path(request['path'])
        operation = request['operation']
        if operation == 'inspect':
            result = inspect_raster(path)
        elif operation == 'normalize':
            import base64
            result = {'png': base64.b64encode(normalized_png(path)).decode('ascii')}
        elif operation == 'project':
            result = project_raster(path, RasterDrawingTransform.model_validate(request['transform']))
        elif operation == 'extract':
            from core_common.protocol.site_drawing import DrawingExtractionRequest
            from fleet.server.site_map_extract import extract_geometry, EXTRACTOR_VERSION
            import cv2
            spec = DrawingExtractionRequest.model_validate(request['transform'])
            result = {'candidates': extract_geometry(path, spec),
                      'extractor_version': EXTRACTOR_VERSION, 'library_version': cv2.__version__}
        else:
            raise ValueError('unknown raster operation')
        sys.stdout.buffer.write(canonical({'result': result}))
    except DrawingLimitError:
        sys.stdout.buffer.write(canonical({'error': 'limit'}))
    except (ValueError, OSError, KeyError, MemoryError):
        sys.stdout.buffer.write(canonical({'error': 'invalid'}))


if __name__ == '__main__':
    main()
