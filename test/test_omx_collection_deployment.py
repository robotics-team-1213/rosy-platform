"""Collection deployment stays disabled and never restarts a failed physical run."""
import configparser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/robot/omx'))


def test_examples_cannot_be_used_as_field_admission():
    from collection_profile import validate_profile,validate_teacher
    profile=json.loads((ROOT/'deploy/robot/omx/collection-profile.json.example').read_text())
    teacher=json.loads((ROOT/'deploy/robot/omx/collection-teacher.json.example').read_text())
    receipt=json.loads((ROOT/'deploy/robot/omx/collection-acceptance.json.example').read_text())
    assert profile['enabled'] is False and not teacher['steps']
    assert receipt['physical_stop_verified'] is False and receipt['expires_ns']==0
    with pytest.raises(ValueError): validate_profile(profile,mode='hardware',acceptance=receipt,teacher=teacher)
    with pytest.raises(ValueError): validate_teacher(teacher,profile)


def test_service_has_finite_runtime_and_no_restart_after_abort():
    parser=configparser.ConfigParser(interpolation=None)
    parser.read(ROOT/'deploy/robot/omx/rosy-omx-collection.service')
    service=parser['Service']
    assert service['Restart']=='no' and service['KillSignal']=='SIGINT'
    assert 0<int(service['RuntimeMaxSec'])<=120 and 0<int(service['TimeoutStopSec'])<=5
    assert service['EnvironmentFile']=='%h/.config/rosy/omx-collection.env'
    assert '[Install]' not in (ROOT/'deploy/robot/omx/rosy-omx-collection.service').read_text()


@pytest.mark.skipif(shutil.which('bash') is None,reason='Linux shell contract')
def test_launcher_fails_before_sourcing_ros_without_explicit_private_inputs():
    clean={key:value for key,value in os.environ.items() if not key.startswith(('ROSY_','ROS_DOMAIN_ID'))}
    result=subprocess.run(['bash',str(ROOT/'deploy/robot/omx/run_collection.sh')],
                          env=clean,capture_output=True,text=True,timeout=5)
    assert result.returncode!=0 and 'immutable source root required' in result.stderr
