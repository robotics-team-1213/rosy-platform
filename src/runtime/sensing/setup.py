import os
from glob import glob

from setuptools import find_packages, setup

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
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'web'), glob('web/*.html')),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ] + map_data_files,
    install_requires=['setuptools'],
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
            'dock_observer_node = control.dock_observer_node:main',
            'road_observer_node = control.road_observer_node:main',
            'obstacle_observer_node = control.obstacle_observer_node:main',
            'watch_node = control.watch_node:main',
            'goal_node = control.goal_node:main',
            'localization_node = control.localization_node:main',
            'web_node = control.web_node:main',
        ],
        'rosy.sensor_provider': [
            # D-126 S1: CORE resolves the sensor worker through this entry
            # point and never imports control statically.
            'control = control.sensor_provider:PROVIDER',
        ],
    },
)
