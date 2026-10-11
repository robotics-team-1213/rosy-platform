import os
from pathlib import Path
import runpy
import shutil

from setuptools import find_packages, setup
from setuptools.command.sdist import sdist


layout = runpy.run_path('fleet/_source_layout.py')
roots = layout['SOURCE_ROOTS']
package_dirs = {
    'rosy.decision': roots['decision'] / 'src/rosy/decision',
    'fleet.server.web': roots['console'],
}


class HolderSource(sdist):
    def make_release_tree(self, base_dir, files):
        root = Path.cwd().resolve()
        super().make_release_tree(base_dir, [name for name in files
            if (root / name).resolve().is_relative_to(root)])
        for name, folder in roots.items():
            shutil.copytree(folder, Path(base_dir) / '_source_roots' / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        manifest = Path(base_dir) / 'fleet.egg-info/SOURCES.txt'
        text = manifest.read_text(encoding='utf-8')
        for name, folder in roots.items():
            text = text.replace(os.path.relpath(folder).replace(os.sep, '/') + '/',
                                '_source_roots/' + name + '/')
        manifest.unlink()  # Release trees may hard-link the source manifest.
        manifest.write_text(text, encoding='utf-8')

package_name = 'fleet'

setup(
    name=package_name,
    version='0.1.0',
    packages=(find_packages(exclude=['test']) + list(package_dirs)
              + ['fleet.server.web.' + name for name in find_packages(where=str(roots['console']))]),
    package_dir={name: os.path.relpath(folder) for name, folder in package_dirs.items()},
    cmdclass={'sdist': HolderSource},
    package_data={'fleet.server.web': [
        '*.html', '*.css', '*.js',
        'shared/*.css', 'shared/*.js',
        'cell/*.html', 'cell/*.css', 'cell/*.js',
    ]},
    include_package_data=True,
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'rosy-world==0.1.0'],
    extras_require={'learning': ['rosy-contracts-learning>=0.1.9']},
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
