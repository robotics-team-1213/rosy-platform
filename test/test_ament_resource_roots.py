"""The marker repair visits current ROS holders without executing package setup."""

from pathlib import Path
import shutil
import subprocess


def test_marker_repair_uses_current_roots_and_declared_package_name(tmp_path):
    root = Path(__file__).resolve().parents[1]
    tools = tmp_path / 'tools'
    tools.mkdir()
    script = tools / 'fix_ament_resource.sh'
    shutil.copyfile(root / 'tools/fix_ament_resource.sh', script)
    for name in ('contracts', 'middleware', 'operations', 'integrations', 'learning'):
        (tmp_path / name).mkdir()
    package = tmp_path / 'middleware/devices/robot arm/adapter'
    package.mkdir(parents=True)
    (package / 'setup.py').write_text('raise RuntimeError("must not execute")\n')
    (package / 'package.xml').write_text('<package><name>arm_adapter</name></package>')
    marker = package / 'resource/arm_adapter'
    marker.parent.mkdir()
    marker.write_text('preserved')
    library = tmp_path / 'operations/library'
    library.mkdir()
    (library / 'setup.py').write_text('raise RuntimeError("not a ROS package")\n')
    result = subprocess.run(['bash', str(script)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text() == 'preserved'
    assert not (library / 'resource').exists()
