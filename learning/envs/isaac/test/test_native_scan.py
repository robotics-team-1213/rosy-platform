"""Native range evidence must preserve unknown rays and robot identity."""
from pathlib import Path
from types import SimpleNamespace
import math
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tools/sim/isaac'))


def test_native_scan_rotates_sensor_rays_and_excludes_only_own_robot():
    from native_scan import scan_sample
    rays = []
    def cast(direction, report):
        rays.append(direction)
        for path, distance in [('/World/Imported/base', .01),
                               ('/World/ImportedOther/base', .3), ('/World/Wall', .7)]:
            assert report(SimpleNamespace(collision=path, distance=distance)) is True
    sample = scan_sample(cast, lambda ray: (-ray[1], ray[0], ray[2]),
                         robot_path='/World/Imported', stamp_ns=123)
    assert len(rays) == len(sample['ranges']) == 640
    assert rays[0] == pytest.approx((0., -1., 0.), abs=1e-12)
    assert sample['ranges'] == [.3] * 640
    assert sample['source_stamp_ns'] == sample['source_now_ns'] == 123
    assert sample['angle_max'] - sample['angle_min'] + sample['angle_increment'] == pytest.approx(2 * math.pi)


def test_no_hit_is_unknown_and_near_hit_is_not_hidden_by_range_min():
    from native_scan import scan_sample
    count = [0]
    def cast(direction, report):
        if count[0] == 0:
            report(SimpleNamespace(collision='/World/Obstacle', distance=.02))
        count[0] += 1
    sample = scan_sample(cast, lambda ray: ray, robot_path='/World/Imported', stamp_ns=1)
    assert sample['ranges'][0] == .02 < sample['range_min']
    assert all(math.isinf(value) for value in sample['ranges'][1:])


@pytest.mark.parametrize('hit', [SimpleNamespace(collision='', distance=.1),
                                SimpleNamespace(collision='/World/Wall', distance=float('nan'))])
def test_malformed_native_hit_fails_instead_of_becoming_free(hit):
    from native_scan import scan_sample
    with pytest.raises(ValueError):
        scan_sample(lambda direction, report: report(hit), lambda ray: ray,
                    robot_path='/World/Imported', stamp_ns=1)
