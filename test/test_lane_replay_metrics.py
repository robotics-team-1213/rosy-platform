from tools.lane_replay import none_runs


def test_none_runs_count_consecutive_holds_without_ground_truth():
    rows = [{'keep': value} for value in (None, None, {'error': 0}, None, {'error': 0}, None, None, None)]
    assert none_runs(rows, 'keep') == [2, 1, 3]
    assert none_runs([], 'keep') == []
