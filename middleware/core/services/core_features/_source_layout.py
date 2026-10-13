"""D-649 source holders; installed feature identities remain unchanged."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
BEHAVIOR_ROOT = (PACKAGE_ROOT / '_source_roots/behaviors'
                 if (PACKAGE_ROOT / '_source_roots/behaviors').is_dir()
                 else PACKAGE_ROOT.parents[1] / 'drive/behaviors')
NAMES = ('line_follow', 'docking', 'navigation', 'localization', 'swarm',
         'road_behaviour', 'traffic_policy')
PACKAGE_DIRS = {'core_features.' + name: BEHAVIOR_ROOT / name for name in NAMES}

SUBJECTS = {'decision': 'action_rules', 'safety': 'safety_gate', 'vision': 'preview'}
PACKAGE_DIRS.update({'core_features.' + name: PACKAGE_ROOT / 'core_features' / holder
                     for name, holder in SUBJECTS.items()})


def load_source_package(namespace):
    folder = PACKAGE_DIRS[namespace['__name__']]
    source = folder / '__init__.py'
    namespace['__path__'] = [str(folder)]
    namespace['__file__'] = str(source)
    exec(compile(source.read_bytes(), str(source), 'exec'), namespace)
