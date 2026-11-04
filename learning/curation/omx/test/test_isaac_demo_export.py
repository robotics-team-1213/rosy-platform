"""D-969 step 2: Isaac two-arm demonstrations become an ACT experiment dataset in the real arm's units."""
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import isaac_demo_export as export  # noqa: E402


def run(root, name, items, views=export.CAMERAS):
    """A recorded run: two rows per container item plus an idle row, one 640x480 video per view with one frame per row."""
    path = root/name
    path.mkdir()
    rows = [dict(item=None, state=[0.]*12, action=[0.]*12)]
    for item in items:
        other = .05*(name == 'run-b')  # runs differ, as real seeds do: the loader refuses duplicate episode bytes
        rows += [dict(item=item, state=[.1*item]*5+[.3]+[other]*6, action=[.1*item+.01]*5+[.3]+[other]*6)]*2
    (path/'demo.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
    for camera in views:
        video = cv2.VideoWriter(str(path/f'demo-{camera}.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 10, (640, 480))
        for i in range(len(rows)):
            video.write(np.full((480, 640, 3), 20*i, np.uint8))
        video.release()
    return path


def test_each_container_is_one_episode_in_arm_units_and_a_run_stays_in_one_split(tmp_path):
    runs = [run(tmp_path, 'run-a', [0, 1]), run(tmp_path, 'run-b', [0, 1])]
    data = export.export(tmp_path/'out', runs, every=1, size=(32, 24), eval_runs=1)
    document = json.loads((tmp_path/'out/dataset.json').read_text(encoding='utf-8'))
    assert document['source'] == 'scripted_teacher' and [a['id'] for a in document['profile']['arms']] == ['arm_a', 'arm_b']
    assert {(e['id'], e['split']) for e in document['episodes']} == {
        ('run-a-0', 'train'), ('run-a-1', 'train'), ('run-b-0', 'eval'), ('run-b-1', 'eval')}
    episode = next(e for e in data.episodes if e.metadata['id'] == 'run-a-1')
    state, action = episode.arrays['observation.state'], episode.arrays['action']
    assert state.shape == action.shape == (2, 12) and episode.arrays['observation.images.top'].shape == (2, 3, 24, 32)
    assert state[0, 0] == pytest.approx(export.rad_to_norm(.1)) and action[0, 0] == pytest.approx(export.rad_to_norm(.11))
    assert 0 <= state[0, 5] <= 100 and state[0, 5] == pytest.approx(export.gap_m(.3)/export.OPEN_GAP_M*100, abs=1e-3)
    assert state[0, 6] == pytest.approx(export.rad_to_norm(0.)) and not math.isnan(float(state.sum()))


def test_a_video_shorter_than_its_rows_is_refused(tmp_path):
    path = run(tmp_path, 'run-a', [0])
    with (path/'demo.jsonl').open('a', encoding='utf-8') as rows:
        rows.write(json.dumps(dict(item=0, state=[0.]*12, action=[0.]*12))+'\n')
    with pytest.raises(ValueError, match='frames for'):
        list(export.episodes(path, 1, (32, 24)))


def test_the_same_episodes_become_a_lerobot_dataset_for_the_official_act_trainer(tmp_path):
    lerobot = pytest.importorskip('lerobot')  # only the isolated lerobot==0.4.4 environment has it
    runs = [run(tmp_path, 'run-a', [0, 1])]
    reader = export.export_lerobot(tmp_path/'lerobot', runs, every=1, size=(32, 24))
    assert reader.meta.total_episodes == 2 and reader.meta.total_frames == 4 and reader.meta.robot_type == 'bi_omx_follower'
    frame = reader[0]
    assert tuple(frame['observation.state'].shape) == (12,) and tuple(frame['observation.images.top'].shape) == (3, 24, 32)


def test_wrist_views_are_exported_per_arm_when_every_run_recorded_them(tmp_path):
    views = export.CAMERAS+export.WRIST
    data = export.export(tmp_path/'out', [run(tmp_path, 'run-a', [0], views), run(tmp_path, 'run-b', [0], views)], every=1)
    document = json.loads((tmp_path/'out'/'dataset.json').read_text(encoding='utf-8'))
    wrist = [c for c in document['profile']['cameras'] if c['placement'] == 'wrist']
    assert len(data.episodes) == 2 and [(c['id'], c['arm_id'], c['role']) for c in wrist] == [
        ('arm_a_wrist', 'arm_a', 'front'), ('arm_b_wrist', 'arm_b', 'front')]


def test_runs_with_and_without_wrist_views_are_not_mixed(tmp_path):
    runs = [run(tmp_path, 'run-a', [0], export.CAMERAS+export.WRIST), run(tmp_path, 'run-b', [0])]
    with pytest.raises(ValueError, match='wrist'):
        export.export(tmp_path/'out', runs, every=1)
