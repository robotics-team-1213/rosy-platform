"""D-969 step 5: act_policy_server checks its arguments before importing LeRobot, which test hosts do not have."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import act_policy_server  # noqa: E402


def test_server_refuses_to_start_without_a_checkpoint():
    with pytest.raises(SystemExit) as exit_info:
        act_policy_server.main([])
    assert exit_info.value.code == 2
