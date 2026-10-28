"""PC calibration/capture tools keep reading the relocated accepted store."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("relative,expected", [
    ("tools/calibration/store_cli.py", {"--root": "calibration"}),
    ("tools/calibration/run_calibration.py", {"STORE": "calibration", "RAW": "perception/raw"}),
    ("tools/calibration/camera_board.py", {"--store-root": "calibration"}),
    ("tools/calibration/analyze_session.py", {"--out": "calibration", "--store": "calibration"}),
    ("tools/capture/edge_drive.py", {"STORE": "calibration"}),
])
def test_host_tool_defaults_follow_external_store_without_device_calls(tmp_path, relative, expected):
    paths = [str(ROOT / p) for p in ["tools", "tools/calibration", "learning/curation/perception",
                                  "middleware/perception", "contracts/foundation"]]
    program = '''
import argparse,contextlib,importlib.util,io,json,pathlib,sys
sys.path[:0]=PATHS
spec=importlib.util.spec_from_file_location('host_probe',FILE)
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
observed={key:str(getattr(module,key)) for key in EXPECTED if not key.startswith('--')}
original=argparse.ArgumentParser.add_argument
def capture(self,*args,**kwargs):
    for flag in args:
        if flag in EXPECTED:observed[flag]=str(kwargs.get('default'))
    return original(self,*args,**kwargs)
argparse.ArgumentParser.add_argument=capture
with contextlib.redirect_stdout(io.StringIO()):
    try:module.main(['--help'])
    except SystemExit as stopped:assert stopped.code==0
print(json.dumps(observed))
'''.replace('PATHS', repr(paths)).replace('FILE', repr(str(ROOT / relative))).replace('EXPECTED', repr(expected))
    result = subprocess.run([sys.executable, '-c', program], env=dict(os.environ, ROSY_DATA_ROOT=str(tmp_path)),
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {key: str(tmp_path / path) for key, path in expected.items()}
    assert not list(tmp_path.iterdir())
