"""Every script a Gazebo rig starts must exist in this tree (D-171).

run_calibration_spaces.py launched tools/gz/run_track260905.sh for months
after the absorption left that script in the archived Rosy Control checkout,
so the calibration ROS-SIM path could not run at all. The rigs are not host
tests, but what they reference is plain text a host test can check.
"""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
GZ = PKG / 'tools' / 'gz'

PATH_REF = re.compile(r"tools/gz/([A-Za-z0-9_]+\.(?:py|sh|yaml|sdf))")
MODULE_REF = re.compile(r"\btools\.gz\.([A-Za-z0-9_]+)")
CONTROL_MODULE_REF = re.compile(r"python3 -m (control(?:\.[A-Za-z0-9_]+)+)")


def _sources():
    return sorted(p for p in GZ.iterdir() if p.suffix in ('.py', '.sh'))


def test_rig_scripts_are_present():
    assert (GZ / 'run_track260905.sh').is_file()
    assert (GZ / 'run_calibration_spaces.py').is_file()


def test_every_rig_reference_resolves():
    missing = []
    for source in _sources():
        text = source.read_text(encoding='utf-8')
        for name in PATH_REF.findall(text):
            if not (GZ / name).is_file():
                missing.append(f'{source.name} -> tools/gz/{name}')
        for module in MODULE_REF.findall(text):
            if not (GZ / f'{module}.py').is_file():
                missing.append(f'{source.name} -> tools.gz.{module}')
        for module in CONTROL_MODULE_REF.findall(text):
            if not (PKG / (module.replace('.', '/') + '.py')).is_file():
                missing.append(f'{source.name} -> {module}')
    assert missing == [], missing


def test_rig_runner_has_no_pre_absorption_paths():
    lines = (GZ / 'run_track260905.sh').read_text(encoding='utf-8').splitlines()
    text = '\n'.join(line for line in lines if not line.lstrip().startswith('#'))
    assert 'rosy_control' not in text
    for config in re.findall(r"config/([a-z_]+\.yaml)", text):
        assert (PKG / 'config' / config).is_file(), config
