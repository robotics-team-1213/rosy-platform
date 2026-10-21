"""Fleet build-time source composition; excluded from installed runtime packages."""

import os
from pathlib import Path
import runpy
import shutil
import sys

from setuptools.command.sdist import sdist
from setuptools.command.build_py import build_py
from setuptools.command.develop import develop


layout = runpy.run_path('fleet/_source_layout.py')
roots = layout['SOURCE_ROOTS']
package_dirs = {
    'fleet.server.assistant': Path('fleet/server/work/assistant'),
    'rosy.decision': roots['decision'] / 'src/rosy/decision',
    'rosy.decision.conversation': roots['decision'] / 'src/rosy/decision/conversation',
    'rosy.decision.deliberation': roots['decision'] / 'src/rosy/decision/deliberation',
    'rosy.decision.deliberation.contracts': roots['decision'] / 'src/rosy/decision/deliberation/contracts',
    'rosy.decision.deliberation.providers': roots['decision'] / 'src/rosy/decision/deliberation/providers',
    'rosy.decision.deliberation.evaluation': roots['decision'] / 'src/rosy/decision/deliberation/evaluation',
    'fleet.server.web': roots['console'],
    'rosy_situation': roots['assessment'] / 'rosy_situation',
    'rosy_discord': roots['discord'] / 'rosy_discord',
}
ASSESSMENT_MODULES = ('__init__', 'assessment', 'snapshot_assessment', 'wait_graph', 'fact_rules')


class HolderDevelop(develop):
    # Colcon editable cleanup would unlink external source holders; use its full-install fallback.
    user_options = [option for option in develop.user_options
                    if option[0] != 'editable' or '--uninstall' in sys.argv]


class PureAssessment(build_py):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        if package == 'fleet.server':
            for name in layout['SERVER_HOLDERS']:
                modules.extend(super().find_package_modules(package, str(Path(package_dir) / name)))
            names = [item[1] for item in modules]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate Fleet server source module')
        return [item for item in modules if package != 'rosy_situation' or item[1] in ASSESSMENT_MODULES]


class HolderSource(sdist):
    def make_release_tree(self, base_dir, files):
        root = Path.cwd().resolve()
        super().make_release_tree(base_dir, [name for name in files
            if (root / name).resolve().is_relative_to(root)])
        support = Path(base_dir) / '_build/fleet_sources.py'
        support.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(__file__, support)
        for name, folder in roots.items():
            destination = Path(base_dir) / '_source_roots' / name
            if name == 'assessment':
                destination = destination / 'rosy_situation'
                destination.mkdir(parents=True, exist_ok=True)
                for module in ASSESSMENT_MODULES:
                    shutil.copy2(folder / 'rosy_situation' / (module + '.py'), destination)
            else:
                shutil.copytree(folder, destination,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        manifest = Path(base_dir) / 'fleet.egg-info/SOURCES.txt'
        text = manifest.read_text(encoding='utf-8')
        for name, folder in roots.items():
            text = text.replace(os.path.relpath(folder).replace(os.sep, '/') + '/',
                                '_source_roots/' + name + '/')
        manifest.unlink()  # Release trees may hard-link the source manifest.
        manifest.write_text(text, encoding='utf-8')
