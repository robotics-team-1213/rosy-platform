import os
from pathlib import Path
import runpy

from setuptools import find_packages, setup


support = Path('_build/fleet_sources.py')
if not support.is_file():
    support = Path(__file__).resolve().parents[2] / 'tools/packaging/fleet_sources.py'
packaging = runpy.run_path(str(support))
roots, package_dirs = packaging['roots'], packaging['package_dirs']

package_name = 'fleet'

setup(
    name=package_name,
    version='0.1.4',
    packages=(find_packages(exclude=['test']) + list(package_dirs)
              + ['fleet.server.web.' + name for name in find_packages(where=str(roots['console']))]),
    package_dir={name: os.path.relpath(folder) for name, folder in package_dirs.items()},
    cmdclass={'sdist': packaging['HolderSource'], 'build_py': packaging['PureAssessment'],
              'develop': packaging['HolderDevelop']},
    package_data={'fleet.server.web': [
        'assets.json',
        '*.html', '*.css', '*.js',
        '*/*.html', '*/*.css', '*/*.js',  # every console subpackage: shared/, cell/, work/
    ]},
    include_package_data=True,
    exclude_package_data={'fleet.server': [
        name + '/*.py' for name in packaging['layout']['SERVER_HOLDERS']
    ]},
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'core_common>=0.0.2', 'rosy-world==0.1.1', 'rosy-execution==0.1.2',
                      'rosy-contracts-learning>=0.1.12', 'oauthlib==4.0.0'],
    extras_require={'learning': []},
    zip_safe=True,
    maintainer='rosy',
    maintainer_email='dev@rosy.local',
    description='ROSY FLEET seed: formation geometry, slot assignment, relay, FOR-004 session',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'fleet=fleet.cli:main',
        ],
    },
)
