"""The drivable preview shows what the drivable keep steered from, not the legacy lane picture."""
from types import SimpleNamespace

import numpy as np

from control.sensing.perception.drivable_preview import (
    MAX_RUNS, chain_rows, drivable, floor_px, way_mask, way_runs)
from control.sensing.perception.follow_preview import draw_follow_evidence
from control.sensing.perception.lane_keep import LaneKeeper

PROJECTION = dict(height_m=0.0549, pitch_rad=0.2115, focal_px=281.6, principal_x=160.0, principal_y=120.0,
                  max_range_m=0.6, camera_x_offset_m=0.03317)


def _way():
    way = np.zeros((240, 320), np.uint8)
    way[140:, 100:220] = 1
    return way


def _keep(**extra):
    keep = dict(image_size=[320, 240], stamp=1.0, paint_source_used='learned_drivable',
                paint_target_requested='drivable', paint_model_revision='lane-seg-20261010-71edcb6d',
                paint_drivable=dict(reason='ok', branches=1, near_fraction=0.94), strategy='drivable_centre',
                error=0.02, confidence=0.9, target_m=[0.25, 0.0], ground_projection=PROJECTION,
                drivable_steer=dict(ahead_m=0.3, exit=None, exit_point_m={}),
                drivable_way=way_runs(_way(), 0.1),
                boundaries=[dict(side='left', selected=True, ends_px=[[10, 230], [60, 120]])])
    keep.update(extra)
    return keep


def test_way_round_trips_sampled_and_stays_small():
    doc = way_runs(_way(), 0.25)
    assert (way_mask(doc) == (_way()[2::4, 2::4] > 0)).all()
    assert doc['age_s'] == 0.25 and len(doc['runs']) <= MAX_RUNS
    assert way_mask(dict(doc, runs=doc['runs'][:-1])) is None   # a short document never draws


def test_a_ragged_way_falls_back_to_coarser_samples_or_none():
    checker = (np.indices((240, 320)).sum(axis=0) // 4) % 2
    assert way_runs(checker, 0.0)['w'] == 40   # too ragged at 4 px, plain at 8 px
    stripes = np.indices((240, 320))[1] % 16 < 8   # every 8 px sample flips: ragged at both steps
    assert way_runs(stripes, 0.0) is None


def test_floor_px_is_the_keepers_projection():
    keeper = LaneKeeper(camera_x_offset_m=PROJECTION['camera_x_offset_m'])
    ground = SimpleNamespace(**PROJECTION)
    for x, y in ((0.192, 0.085), (0.3, -0.05), (0.2, 0.0)):
        assert np.allclose(floor_px(PROJECTION, x, y), keeper.to_pixel(ground, x, y), atol=0.06)
    assert floor_px(PROJECTION, 0.01, 0.0) is None


def test_drivable_mode_comes_from_keep_debug():
    assert drivable(_keep()) and drivable(_keep(paint_source_used='denoise_fallback'))
    assert not drivable(dict(paint_source_used='learned', paint_target_requested='lane_marking'))
    assert not drivable(None)


def test_the_headline_names_the_layer_that_stops():
    (headline, _), rows = chain_rows(_keep())
    assert headline.startswith('CAMERA STEERS') and rows[0][0].startswith('1 PERCEPTION learned_drivable')
    (headline, _), _ = chain_rows(_keep(strategy='none', error=None, reason='drivable_way_stale'))
    assert headline == 'STOPPED BY: STEERING - drivable_way_stale'
    (headline, _), _ = chain_rows(_keep(paint_source_used='denoise_fallback'))
    assert headline.startswith('STOPPED BY: PERCEPTION - denoise_fallback')


def test_drivable_preview_tints_the_way_dims_the_rest_and_skips_legacy_lanes():
    image = np.full((240, 320, 3), 100, np.uint8)
    draw_follow_evidence(image, scale=1.0, keep=_keep())
    assert image[170, 130, 1] > image[170, 130, 0]          # on the way: green tint
    assert image[100, 20].max() <= 60                       # off the way: dimmed
    assert image[125:175, 30:60, 1].max() <= 60             # the legacy left boundary is not drawn
    legacy = np.full((240, 320, 3), 100, np.uint8)
    draw_follow_evidence(legacy, scale=1.0, keep=_keep(paint_source_used='learned', paint_target_requested='lane_marking'))
    assert legacy[125:175, 30:60, 1].max() > 200            # ...but is in the lane view


def test_keep_step_puts_the_steered_way_into_keep_debug():
    from control.sensing.perception.drivable_keep import keep_step
    worker = SimpleNamespace(used_crosswalk=None, latest_way=lambda _age: (_way(), 0.75))
    steer = SimpleNamespace(update=lambda *a, **k: (0.1, 0.9, dict(strategy='drivable_centre', target_m=(0.25, 0.0))),
                            crosswalk=lambda _pose: None)
    last = {}
    assert keep_step(steer, worker, last, None, 0.03, 0.0925, lambda _s: None, 1.0, None) == ((0.1, 0.9), True)
    assert last['drivable_way']['age_s'] == 0.25 and (way_mask(last['drivable_way']) == (_way()[2::4, 2::4] > 0)).all()


def test_the_target_is_marked_where_it_lies_on_either_side():
    for target in ([0.25, -0.05], [0.22, 0.06]):
        image = np.full((240, 320, 3), 100, np.uint8)
        draw_follow_evidence(image, scale=1.0, keep=_keep(target_m=target))
        col, row = (int(round(v)) for v in floor_px(PROJECTION, *target))
        patch = image[row - 8:row + 9, col - 8:col + 9].reshape(-1, 3).astype(int)
        assert ((patch[:, 0] > 180) & (patch[:, 2] > 180) & (patch[:, 1] < 100)).any(), target   # magenta ring
