"""Drawing references carry geometry provenance, never motion authority."""
import importlib
import math

import pytest
from pydantic import ValidationError

from fleet.site_map import SiteMap


def drawing_contract():
    try:
        return importlib.import_module('core_common.protocol.site_drawing')
    except ModuleNotFoundError as exc:
        if exc.name != 'core_common.protocol.site_drawing':
            raise
        pytest.fail('drawing contract is not implemented')


def transform(**changes):
    return {'plane': 'xy', 'unit': 'mm', 'source_origin': [0, 0],
            'map_origin_m': [0, 0], 'heading_rad': 0, 'scale': 1, **changes}


def test_legacy_map_dump_is_unchanged():
    body = {'schema': 'rosy.site_map/1', 'map_id': 'site', 'places': [], 'edges': [],
            'turn_bans': []}
    assert SiteMap.model_validate(body).body() == body


def test_optional_road_name_roundtrips_without_changing_legacy_edges():
    old = SiteMap.model_validate({'map_id': 'site', 'places': [
        {'id': 'a', 'name': 'A', 'x': 0, 'y': 0},
        {'id': 'b', 'name': 'B', 'x': 1, 'y': 0}], 'edges': [
        {'id': 'ab', 'from': 'a', 'to': 'b', 'polyline': [[0, 0], [1, 0]],
         'width_m': .2, 'speed_cap_mps': .2}]})
    body = old.body()
    assert 'name' not in body['edges'][0] and 'drawing' not in body
    for name in ('출입구 도로', '길' * 64):
        named = {**body, 'edges': [{**body['edges'][0], 'name': name}]}
        restored = SiteMap.model_validate(named)
        assert restored.body() == named
        assert restored.edges[0].id == 'ab' and restored.edges[0].to == 'b'
    for name in ('', '  ', 'x' * 65):
        with pytest.raises(ValidationError):
            SiteMap.model_validate({**body, 'edges': [{**body['edges'][0], 'name': name}]})
    assert SiteMap.model_validate(body).body() == body


def test_drawing_hashes_and_transform_are_bounded():
    model = drawing_contract()
    reference = model.DrawingReference(asset_sha256='a' * 64, projection_sha256='b' * 64)
    assert reference.model_dump() == {'asset_sha256': 'a' * 64, 'projection_sha256': 'b' * 64}
    assert model.DrawingTransform(**transform()).scale == 1
    for changes in ({'asset_sha256': '../x'}, {'projection_sha256': 'B' * 64},
                    {'asset_sha256': 'a' * 63}, {'unknown': True}):
        with pytest.raises(ValidationError):
            model.DrawingReference(**{**reference.model_dump(), **changes})


@pytest.mark.parametrize('changes', [
    {'scale': 0}, {'scale': -1}, {'scale': math.inf}, {'unit': 'guess'}, {'plane': 'auto'},
    {'source_origin': [math.nan, 0]}, {'map_origin_m': [0, math.inf]},
    {'map_origin_m': [1001, 0]}, {'heading_rad': math.tau + .01}, {'unknown': True},
])
def test_invalid_drawing_transform_is_rejected(changes):
    model = drawing_contract()
    with pytest.raises(ValidationError):
        model.DrawingTransform(**transform(**changes))


@pytest.mark.parametrize('plane', ['xy', 'xz', 'yz'])
@pytest.mark.parametrize('unit', ['m', 'cm', 'mm'])
def test_drawing_transform_retains_explicit_registration(plane, unit):
    model = drawing_contract()
    value = model.DrawingTransform(**transform(plane=plane, unit=unit, source_origin=[10, 20],
                                               map_origin_m=[1, 2], heading_rad=math.pi / 2))
    assert value.plane == plane and value.unit == unit
    assert value.source_origin == (10, 20) and value.map_origin_m == (1, 2)
    with pytest.raises(ValidationError):
        value.scale = 2
