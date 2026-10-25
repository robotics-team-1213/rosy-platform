"""MAP-205: immutable raster sources and one measured normalized-pixel transform."""
import hashlib
import importlib
import io
import math

from PIL import Image
import pytest

from fleet.server.site_map_assets import SiteMapAssetStore


def raster():
    try:
        return importlib.import_module('fleet.server.site_map_raster')
    except ModuleNotFoundError as exc:
        if exc.name != 'fleet.server.site_map_raster':
            raise
        pytest.fail('raster adapter is not implemented')


def image_bytes(size=(100, 50), mode='RGB', color='white', format='PNG', **save):
    stream = io.BytesIO()
    Image.new(mode, size, color).save(stream, format=format, **save)
    return stream.getvalue()


def transform(**changes):
    from core_common.protocol.site_drawing import RasterDrawingTransform
    return RasterDrawingTransform(**{'source_origin_px': [0, 0], 'map_origin_m': [2, 3],
                                    'heading_rad': 0, 'meters_per_pixel': .02, **changes})


def test_normalization_preserves_source_and_composites_alpha(tmp_path):
    module = raster()
    source = tmp_path / 'input.png'
    data = image_bytes(mode='RGBA', color=(255, 0, 0, 0))
    source.write_bytes(data)
    result = module.inspect_raster(source)
    assert result['asset_sha256'] == hashlib.sha256(data).hexdigest()
    assert (result['width_px'], result['height_px']) == (100, 50)
    assert result['format'] == 'png'
    assert source.read_bytes() == data
    normalized = module.normalized_png(source)
    assert Image.open(io.BytesIO(normalized)).getpixel((0, 0)) == (255, 255, 255)


def test_exif_orientation_is_applied_once(tmp_path):
    module = raster()
    exif = Image.Exif()
    exif[274] = 6
    source = tmp_path / 'input.jpg'
    source.write_bytes(image_bytes(size=(100, 50), format='JPEG', exif=exif))
    assert module.inspect_raster(source)['width_px'] == 50
    rendered = Image.open(io.BytesIO(module.normalized_png(source)))
    assert rendered.size == (50, 100) and rendered.getexif().get(274) is None


@pytest.mark.parametrize('data', [b'<svg/>', b'\x89PNG\r\n\x1a\ninvalid',
    image_bytes(size=(8193, 1)), image_bytes(size=(4001, 4000))],
    ids=['wrong-format', 'corrupt', 'axis-limit', 'pixel-limit'])
def test_invalid_or_oversized_raster_is_rejected(tmp_path, data):
    module = raster()
    source = tmp_path / 'untrusted'
    source.write_bytes(data)
    with pytest.raises(ValueError):
        module.inspect_raster(source)


def test_registration_flips_pixels_and_binds_content(tmp_path):
    module = raster()
    source = tmp_path / 'input.png'
    source.write_bytes(image_bytes())
    result = module.project_raster(source, transform())
    assert result['bounds_m'] == [[2, 2], [4, 3]]
    assert result['kind'] == 'raster' and result['segments'] == []
    assert module.pixel_to_map([100, 0], transform()) == pytest.approx([4, 3], abs=1e-6)
    assert module.pixel_to_map([0, 50], transform(heading_rad=math.pi / 2)) == pytest.approx([3, 3])
    assert result == module.project_raster(source, transform())
    with pytest.raises(ValueError):
        module.project_raster(source, transform(meters_per_pixel=100))


def test_raster_assets_survive_restart_and_verify_hashes(tmp_path):
    raster()
    source = tmp_path / 'input.png'
    data = image_bytes()
    source.write_bytes(data)
    assets = SiteMapAssetStore(tmp_path / 'assets')
    info = assets.put_raster(source)
    result = assets.project(info['asset_sha256'], transform())
    assets = SiteMapAssetStore(assets.root)
    assert assets.source(info['asset_sha256']).read_bytes() == data
    assert assets.projection(result['projection_sha256']) == result
    assets.validate_reference(type('Reference', (), result)(), result['projection_sha256'])
    rendered = assets.render(result['projection_sha256'])
    assert Image.open(rendered).size == (100, 50)
    rendered.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash|content'):
        assets.render(result['projection_sha256'])


def test_multiframe_is_not_a_flat_drawing(tmp_path):
    module = raster()
    output = io.BytesIO()
    Image.new('RGB', (10, 10), 'white').save(output, format='PNG', save_all=True,
        append_images=[Image.new('RGB', (10, 10), 'black')])
    path = tmp_path / 'animation.png'
    path.write_bytes(output.getvalue())
    with pytest.raises(ValueError):
        module.inspect_raster(path)


def test_raster_http_guards_registration_and_render(tmp_path, monkeypatch):
    from test_site_map_drawing_api import setup_assets, UPLOAD
    import test_site_map_trip as trip
    client, store, _ = setup_assets(tmp_path, monkeypatch)
    data = image_bytes()
    before = store.active_view(), store.draft_view()
    assert client.post(UPLOAD, headers=trip.VIEWER, content=data).status_code == 403
    wrong = client.post(UPLOAD, headers={**trip.OPERATOR, 'Content-Type': 'image/jpeg'}, content=data)
    assert wrong.status_code == 422
    uploaded = client.post(UPLOAD, headers={**trip.OPERATOR, 'Content-Type': 'image/png'}, content=data)
    assert uploaded.status_code == 200, uploaded.text
    digest = uploaded.json()['asset_sha256']
    projected = client.post(f'{UPLOAD}/{digest}/projections', headers=trip.OPERATOR,
                            json=transform().model_dump(mode='json'))
    assert projected.status_code == 200, projected.text
    result = projected.json()
    url = f"/api/fleet/site-map/drawing-projections/{result['projection_sha256']}/render"
    assert client.get(url).status_code == 401
    rendered = client.get(url, headers=trip.VIEWER)
    assert rendered.status_code == 200 and rendered.headers['content-type'] == 'image/png'
    assert rendered.headers['x-content-type-options'] == 'nosniff'
    assert 'no-store' in rendered.headers['cache-control']
    assert Image.open(io.BytesIO(rendered.content)).size == (100, 50)
    downloaded = client.get(f'{UPLOAD}/{digest}/source', headers=trip.OPERATOR)
    assert downloaded.content == data and 'attachment' in downloaded.headers['content-disposition']
    assert (store.active_view(), store.draft_view()) == before
