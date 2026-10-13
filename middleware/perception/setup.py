import os
from pathlib import Path
import runpy
import shutil
from glob import glob

from setuptools import find_packages, setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist


layout = runpy.run_path('control/_source_layout.py')
package_dirs = layout['PACKAGE_DIRS']
flat_roots = layout['FLAT_ROOTS']
packages = ['control', 'control.control']
for name, folder in package_dirs.items():
    packages.append(name)
    packages.extend(name + '.' + child for child in find_packages(where=str(folder)))


class HolderBuild(build_py):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        if package == 'control':
            relative = Path(os.path.relpath(layout['RUNTIME_ROOT']))
            modules.extend((package, path.stem, str(path))
                           for path in sorted(relative.glob('*.py')))
            names = [name for _, name, _ in modules]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate control runtime source module')
        if package == 'control.control':
            for folder in flat_roots:
                relative = Path(os.path.relpath(folder))
                modules.extend((package, path.stem, str(path))
                               for path in sorted(relative.glob('*.py'))
                               if path.name != '__init__.py')
            names = [name for _, name, _ in modules]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate control.control source module')
        return modules


class HolderSource(sdist):
    def add_defaults(self):
        super().add_defaults()
        self.filelist.extend('control/' + name + '/__init__.py'
                             for name in ('sensing', 'planning', 'safety', 'wander'))

    def make_release_tree(self, base_dir, files):
        root = Path.cwd().resolve()
        super().make_release_tree(base_dir, [name for name in files
            if (root / name).resolve().is_relative_to(root)])
        snapshot = Path(base_dir) / '_source_roots/drive'
        for relative in ('safety', 'recovery', 'tracking', 'calibration', 'planning/grid', 'runtime'):
            shutil.copytree(layout['DRIVE_ROOT'] / relative, snapshot / relative,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        manifest = Path(base_dir) / 'control.egg-info/SOURCES.txt'
        text = manifest.read_text(encoding='utf-8').replace(
            '../control/drive/', '_source_roots/drive/')
        manifest.unlink()  # The release tree may hard-link its source manifest.
        manifest.write_text(text, encoding='utf-8')

package_name = 'control'
map_bundles = (
    os.path.join('map', 'map_260905_update_v2'),
    os.path.join('map', 'map_v2_fleet'),
)
map_data_files = [
    (
        os.path.join('share', package_name, os.path.dirname(path)),
        [path],
    )
    for bundle in map_bundles
    for path in glob(os.path.join(bundle, '**', '*'), recursive=True)
    if os.path.isfile(path)
]

setup(
    name=package_name,
    version='0.1.1',
    packages=packages,
    package_dir={name: os.path.relpath(folder) for name, folder in package_dirs.items()},
    cmdclass={'build_py': HolderBuild, 'sdist': HolderSource},
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'web'), glob('web/*.html')),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ] + map_data_files,
    install_requires=['setuptools', 'core_common>=0.0.1'],
    zip_safe=True,
    maintainer='livsbittt',
    maintainer_email='56295815+livsbittt@users.noreply.github.com',
    description='Rosy OS absorbed sensing, OpenCV, calibration, planning, and safety subjects',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'control_node = control.control_node:main',
            'safety_node = control.safety_node:main',
            'wander_node = control.wander_node:main',
            'calib_node = control.calib_node:main',
            'startup_calibration_node = control.startup_calibration_node:main',
            'camera_detect_node = control.camera_detect_node:main',
            'ir_adc_node = control.ir_adc_node:main',
            'line_observer_node = control.line_observer_node:main',
            'learned_lane_node = control.learned_lane_node:main',
            'object_detector_node = control.object_detector_node:main',
            'capture_trigger_node = control.capture_trigger_node:main',
            'pilot_recorder_node = control.pilot_recorder_node:main',
            'road_state_node = control.road_state_node:main',
            'record_session = control.record_session:main',
            'line_observer_overrides = control.line_observer_overrides:main',
            'dock_observer_node = control.dock_observer_node:main',
            'road_observer_node = control.road_observer_node:main',
            'obstacle_observer_node = control.obstacle_observer_node:main',
            'watch_node = control.watch_node:main',
            'goal_node = control.goal_node:main',
            'localization_node = control.localization_node:main',
            'loc_assist_node = control.loc_assist_node:main',
            'web_node = control.web_node:main',
        ],
        'rosy.sensor_provider': [
            # D-126 S1: CORE resolves the sensor worker through this entry
            # point and never imports control statically.
            'control = control.sensor_provider:PROVIDER',
        ],
    },
)
