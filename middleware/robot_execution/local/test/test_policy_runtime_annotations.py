"""Extracted ROS-free runtime keeps the production annotation semantics."""
from test_policy_runtime_binding import attached


def test_extracted_runtime_keeps_production_postponed_annotations(tmp_path):
    _, runtime, *_ = attached(tmp_path)
    assert runtime.submit.__annotations__ == {
        'command': 'TrajectoryCommand', 'return': 'CommandDecision',
    }
