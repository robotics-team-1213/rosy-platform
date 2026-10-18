"""Five predeclared diagnostic samples; failures remain failures, never retries."""
import os

import pytest

from test_omx_native_ros_runtime import test_native_ros_runtime as run_native


@pytest.mark.skipif(os.environ.get('ROSY_OMX_FEEDBACK_TRACE') not in ('0', '1'),
                    reason='explicit native feedback diagnostic sampling required')
@pytest.mark.parametrize('sample', range(5))
def test_feedback_timing_sample(sample):
    run_native(113, 'middleware/devices/omx/adapter/test/test_omx_ros_runtime.py'
               '::test_slow_feedback_handling_cannot_starve_the_joint_state_subscription')


@pytest.mark.skipif(os.environ.get('ROSY_OMX_FEEDBACK_TRACE') not in ('0', '1'),
                    reason='explicit native feedback diagnostic sampling required')
@pytest.mark.parametrize('sample', range(5))
def test_feedback_after_full_suite_sample(sample):
    run_native(113, 'middleware/devices/omx/adapter/test/test_omx_ros_runtime.py')
