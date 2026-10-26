"""The installed wheel owns one namespace and imports without Fleet or ROS."""

from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def test_installed_monitoring_wheel_is_independent(tmp_path):
    wheelhouse, installed = tmp_path / "wheelhouse", tmp_path / "installed"
    for relative in ("contracts/foundation", "operations/monitoring"):
        source = tmp_path / Path(relative).name
        shutil.copytree(ROOT / relative, source,
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "dist"))
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                        "--wheel-dir", str(wheelhouse), str(source)],
                       check=True, capture_output=True, text=True, timeout=120)
    wheels = list(wheelhouse.glob("*.whl"))
    assert len(wheels) == 2
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
                    "--target", str(installed), *map(str, wheels)],
                   check=True, capture_output=True, text=True, timeout=60)
    result = subprocess.run([sys.executable, "-I", "-c", """
from pathlib import Path
from importlib.metadata import distribution
import sys
sys.path.insert(0, sys.argv[1])
from rosy.monitoring import cache, config, models, service
dist = distribution('rosy-monitoring')
assert dist.version == '0.1.0'
files = {str(p) for p in dist.files}
assert 'rosy/monitoring/cache.py' in files
assert 'rosy/monitoring/__main__.py' in files
assert any(entry.name == 'rosy-monitoring' and entry.value == 'rosy.monitoring.__main__:main'
           for entry in dist.entry_points)
assert 'rosy/__init__.py' not in files
assert all(Path(m.__file__).is_relative_to(Path(sys.argv[1])) for m in (cache, config, models, service))
assert not any(name.split('.')[0] in {'fleet', 'rclpy', 'rospy'} for name in sys.modules)
assert not any('fleet' in requirement.lower() or 'rclpy' in requirement.lower()
               for requirement in dist.requires or [])
""", str(installed)], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
