"""D-649 source holders; installed feature identities remain unchanged."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
BEHAVIOR_ROOT = (PACKAGE_ROOT / '_source_roots/behaviors'
                 if (PACKAGE_ROOT / '_source_roots/behaviors').is_dir()
                 else PACKAGE_ROOT.parents[1] / 'control/drive/behaviors')
NAMES = ('line_follow', 'docking', 'navigation', 'localization', 'swarm',
         'road_behaviour', 'traffic_policy')
PACKAGE_DIRS = {'core_features.' + name: BEHAVIOR_ROOT / name for name in NAMES}
