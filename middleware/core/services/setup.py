import os
from pathlib import Path
import runpy
import shutil

from setuptools import find_packages, setup
from setuptools.command.sdist import sdist

layout = runpy.run_path('core_features/_source_layout.py')
package_dirs = layout['PACKAGE_DIRS']
packages = find_packages(exclude=['test'])
for name, folder in package_dirs.items():
    packages.append(name)
    packages.extend(name + '.' + child for child in find_packages(where=str(folder)))


class HolderSource(sdist):
    def make_release_tree(self, base_dir, files):
        root = Path.cwd().resolve()
        super().make_release_tree(base_dir, [name for name in files
            if (root / name).resolve().is_relative_to(root)])
        shutil.copytree(layout['BEHAVIOR_ROOT'], Path(base_dir) / '_source_roots/behaviors',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        manifest = Path(base_dir) / 'core_features.egg-info/SOURCES.txt'
        text = manifest.read_text(encoding='utf-8').replace(
            '../../control/drive/behaviors/', '_source_roots/behaviors/')
        manifest.unlink()  # Do not write through a source-manifest hard link.
        manifest.write_text(text, encoding='utf-8')

package_name = 'core_features'

setup(
    name=package_name,
    version='0.0.0',
    packages=packages,
    package_dir={name: os.path.relpath(folder) for name, folder in package_dirs.items()},
    cmdclass={'sdist': HolderSource},
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Dev',
    maintainer_email='dev@rosy.com',
    description='Core Features',
    license='Proprietary',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [],
    },
)
