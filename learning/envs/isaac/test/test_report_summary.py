"""One command answers what each container run did, from the report alone."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapped_stack_fixture as f
from test_container_stack import bodies


def report():
    fixture = f.container_fixture(layers=3, case='nominal')
    sample = dict(tick=900, boxes=copy.deepcopy(bodies(fixture)))
    sample['boxes'][1]['position'][1] += .002   # moved past the 1.5 mm tolerance
    sample['boxes'][2]['velocity'] = [.02, 0., 0.]
    sample['boxes'][3]['position'][2] += .1   # the held fourth box
    trial = dict(layers=[{'opened_sample': {}}] * 3 + [{'item': 3}], error='Prior stack did not establish a stable window within ten seconds [box2 ...]',
                 failures=['first_layer_not_completed'], failure_sample=sample, task_success=False)
    return dict(fixture=fixture, trials=[trial], task_success=False, video=dict(frames=120))


def test_summary_names_placements_error_gaps_and_why_each_box_is_unstable(tmp_path):
    import mapped_stack_report as m
    summary = m.summarize(report())
    assert summary['placed'] == 3 and summary['planned'] == 9 and summary['task_success'] is False
    assert summary['error'].startswith('Prior stack') and summary['failures'] == ['first_layer_not_completed']
    # Only the three released boxes count: box 3 is still held, so only the first floor's two gaps exist.
    assert summary['row_gaps_mm'] == pytest.approx([1.5, 3.5])
    assert summary['unstable'] == [
        dict(box=1, position_error_mm=pytest.approx(2.0), speed_m_s=0., angular_rad_s=0.),
        dict(box=2, position_error_mm=0., speed_m_s=pytest.approx(.02), angular_rad_s=0.)]
    path = tmp_path / 'mapped-stack-report.json'
    path.write_text(json.dumps(report()))
    out = subprocess.run([sys.executable, str(Path(m.__file__)), 'summary', str(path)], capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)['placed'] == 3
