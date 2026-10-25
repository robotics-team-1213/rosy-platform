"""MAP-206: reproducible pixel candidates and explicit review, never inferred road topology."""
import importlib
import io
import math
import random

from PIL import Image, ImageDraw
import pytest

from test_site_map_raster import transform


def extractor():
    try:
        return importlib.import_module('fleet.server.site_map_extract')
    except ModuleNotFoundError as exc:
        if exc.name != 'fleet.server.site_map_extract':
            raise
        pytest.fail('geometry extractor is not implemented')


def diagram():
    image = Image.new('RGB', (160, 120), 'white')
    drawing = ImageDraw.Draw(image)
    drawing.line([(20, 30), (140, 30)], fill='black', width=2)
    drawing.rectangle((40, 60, 100, 100), outline='black', width=2)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def options(**changes):
    from core_common.protocol.site_drawing import DrawingExtractionRequest
    return DrawingExtractionRequest(**{'crop_px': [0, 0, 160, 120], 'method': 'lines', **changes})


def test_lines_are_in_source_pixels_with_crop_offset_and_deterministic_ids(tmp_path):
    module = extractor()
    path = tmp_path / 'drawing.png'; path.write_bytes(diagram())
    spec = options(crop_px=[10, 10, 150, 50])
    result = module.extract_geometry(path, spec)
    assert result and result == module.extract_geometry(path, spec)
    for candidate in result:
        assert candidate['closed'] is False and len(candidate['geometry_px']) == 2
        assert all(10 <= x <= 150 and 10 <= y <= 50 for x, y in candidate['geometry_px'])
    assert any(abs(p[1] - 30) <= 2 for c in result for p in c['geometry_px'])


def test_contours_and_empty_image_are_successful_distinct_results(tmp_path):
    module = extractor()
    path = tmp_path / 'drawing.png'; path.write_bytes(diagram())
    result = module.extract_geometry(path, options(method='contours', crop_px=[30, 50, 110, 110]))
    assert result and all(c['closed'] and len(c['geometry_px']) >= 3 for c in result)
    Image.new('RGB', (160, 120), 'white').save(path)
    assert module.extract_geometry(path, options()) == []


def test_limits_and_invalid_roi_are_not_truncated_or_reported_as_empty(tmp_path, monkeypatch):
    module = extractor()
    path = tmp_path / 'drawing.png'; path.write_bytes(diagram())
    for crop in ([0, 0, 161, 120], [10, 0, 1, 120], [0, 0, 0, 120]):
        with pytest.raises(ValueError):
            module.extract_geometry(path, options(crop_px=crop))
    monkeypatch.setattr(module, 'MAX_CANDIDATES', 0)
    with pytest.raises(ValueError, match='limit|budget'):
        module.extract_geometry(path, options())


def test_extraction_http_keeps_map_unchanged_and_provenance_durable(tmp_path, monkeypatch):
    extractor()
    from test_site_map_drawing_api import setup_assets, UPLOAD
    import test_site_map_trip as trip
    client, store, assets = setup_assets(tmp_path, monkeypatch)
    source = client.post(UPLOAD, headers={**trip.OPERATOR, 'Content-Type': 'image/png'}, content=diagram()).json()
    projection = assets.project(source['asset_sha256'], transform())
    url = f"/api/fleet/site-map/drawing-projections/{projection['projection_sha256']}/extractions"
    before = store.active_view(), store.draft_view()
    assert client.post(url, headers=trip.VIEWER, json=options().model_dump()).status_code == 403
    response = client.post(url, headers=trip.OPERATOR, json=options().model_dump())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['candidates'] and result['projection_sha256'] == projection['projection_sha256']
    assert result['asset_sha256'] == source['asset_sha256']
    assert assets.extraction(result['extraction_sha256']) == result
    assert (store.active_view(), store.draft_view()) == before
    assets.slot.acquire()
    try:
        assert client.post(url, headers=trip.OPERATOR, json=options().model_dump()).status_code == 429
    finally:
        assets.slot.release()


def test_candidate_map_validation_retains_facility_provenance_without_writing(tmp_path, monkeypatch):
    extractor()
    from test_site_map_drawing_api import setup_assets, UPLOAD
    import test_site_map_trip as trip
    client, store, assets = setup_assets(tmp_path, monkeypatch)
    source = client.post(UPLOAD, headers={**trip.OPERATOR, 'Content-Type': 'image/png'}, content=diagram()).json()
    projection = assets.project(source['asset_sha256'], transform())
    result = assets.extract(projection['projection_sha256'], options())
    candidate = result['candidates'][0]['candidate_id']
    evidence = {'source': 'operator', 'status': 'observed', 'reference_revision': projection['projection_sha256'],
                'note': f"extraction:{result['extraction_sha256']} candidate:{candidate}"}
    body = {'map_id': 'new-candidate-frame', 'places': [], 'edges': [],
            'drawing': {k: projection[k] for k in ('asset_sha256', 'projection_sha256')},
            'survey': {'revision': projection['projection_sha256'], 'origin': [2, 3], 'heading_rad': 0,
                       'scale_source': 'measured', 'measured_distance_m': 1, 'description': 'measured baseline'},
            'facilities': [{'id': 'zone', 'kind': 'exclusion', 'name': 'Zone',
                            'geometry': [[0, 0], [1, 0], [1, 1]], 'evidence': evidence}]}
    url = f"/api/fleet/site-map/drawing-extractions/{result['extraction_sha256']}/validate"
    before = store.active_view(), store.draft_view()
    response = client.post(url, headers=trip.OPERATOR, json={'map': body})
    assert response.status_code == 200, response.text
    assert response.json()['map']['facilities'][0]['evidence'] == evidence
    body['facilities'][0]['geometry'] = [[0, 0], [1, 1], [0, 1], [1, 0]]
    assert client.post(url, headers=trip.OPERATOR, json={'map': body}).status_code == 422
    assert (store.active_view(), store.draft_view()) == before


@pytest.mark.parametrize('angle,noise', [(0, False), (math.pi / 6, False), (0, True)],
                         ids=['orthogonal', 'rotated', 'noise'])
def test_synthetic_line_accuracy_baseline(tmp_path, angle, noise):
    module = extractor()
    image = Image.new('RGB', (160, 160), 'white')
    drawing = ImageDraw.Draw(image)
    def rotate(point):
        x, y = point[0] - 80, point[1] - 80
        return [80 + math.cos(angle) * x - math.sin(angle) * y,
                80 + math.sin(angle) * x + math.cos(angle) * y]
    truth = [[rotate(a), rotate(b)] for a, b in [((20, 30), (140, 30)), ((80, 70), (80, 145))]]
    for a, b in truth:
        drawing.line([tuple(a), tuple(b)], fill='black', width=1)
    if noise:
        rng = random.Random(835)
        for _ in range(60):
            image.putpixel((rng.randrange(160), rng.randrange(160)), (0, 0, 0))
    path = tmp_path / 'baseline.png'; image.save(path)
    result = module.extract_geometry(path, options(crop_px=[0, 0, 160, 160]))
    assert result
    def matches(candidate, segment):
        a, b = segment
        length = math.dist(a, b)
        return all(abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) / length <= 2
                   for p in candidate['geometry_px'])
    precision = sum(any(matches(c, segment) for segment in truth) for c in result) / len(result)
    recall = sum(any(matches(c, segment) for c in result) for segment in truth) / len(truth)
    assert precision >= .9 and recall >= .9, (precision, recall)
