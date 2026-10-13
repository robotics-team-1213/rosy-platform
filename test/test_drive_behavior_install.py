"""D-649: an isolated source release preserves one installed feature identity."""

import importlib
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('line_follow', 'docking', 'navigation', 'localization', 'swarm',
         'road_behaviour', 'traffic_policy')


def run(*args, cwd):
    result = subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True,
                            text=True, encoding='utf-8', timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


def test_source_imports_resolve_to_one_canonical_drive_implementation():
    sys.path.insert(0, str(ROOT / 'middleware/core/services'))
    for name in NAMES:
        module = importlib.import_module('core_features.' + name)
        assert Path(module.__file__).resolve() == (
            ROOT / 'middleware/drive/behaviors' / name / '__init__.py').resolve()
        assert not (ROOT / 'middleware/core/services/core_features' / name).exists()


def test_sdist_alone_builds_independent_wheel_with_original_imports(tmp_path):
    copied = tmp_path / 'source/middleware/core/services'
    ignore = shutil.ignore_patterns('__pycache__', '*.egg-info', 'build', 'dist')
    shutil.copytree(ROOT / 'middleware/core/services', copied, ignore=ignore)
    shutil.copytree(ROOT / 'middleware/drive/behaviors',
                    tmp_path / 'source/middleware/drive/behaviors', ignore=ignore)
    dist = tmp_path / 'dist'
    run('setup.py', 'sdist', '--dist-dir', str(dist), cwd=copied)
    with tarfile.open(next(dist.glob('*.tar.gz'))) as archive:
        assert all('..' not in Path(member.name).parts and not member.issym()
                   and not member.islnk() for member in archive.getmembers())
        archive.extractall(tmp_path / 'unpacked', filter='data')
    unpacked = next((tmp_path / 'unpacked').iterdir())
    shutil.rmtree(tmp_path / 'source')  # Prove the source archive has no sibling dependency.
    run('setup.py', 'bdist_wheel', '--dist-dir', str(dist), cwd=unpacked)
    installed = tmp_path / 'installed'
    with zipfile.ZipFile(next(dist.glob('*.whl'))) as wheel:
        names = wheel.namelist()
        for name in NAMES:
            assert names.count('core_features/' + name + '/__init__.py') == 1
        assert not any('_source_roots' in name for name in names)
        wheel.extractall(installed)
    foundation = tmp_path / 'foundation'
    shutil.copytree(ROOT / 'contracts/foundation/core_common', foundation / 'core_common', ignore=ignore)
    run('-I', '-c', """
import importlib, importlib.metadata
from pathlib import Path
import sys
sys.path[:0] = sys.argv[1:3]
root = Path(sys.argv[1]).resolve()
for name in ('line_follow.manager', 'docking.manager', 'navigation.manager',
             'localization.assist', 'swarm.manager', 'road_behaviour.machine', 'traffic_policy.manager'):
    module = importlib.import_module('core_features.' + name)
    assert Path(module.__file__).resolve().is_relative_to(root), name
assert importlib.metadata.distribution('core_features').version == '0.0.0'
""", str(installed), str(foundation), cwd=tmp_path)
