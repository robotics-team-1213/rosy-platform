"""Static source holders; installed Fleet keeps its existing resource paths."""

from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = {
    name: (PACKAGE_ROOT / '_source_roots' / name
           if (PACKAGE_ROOT / '_source_roots' / name).is_dir()
           else PACKAGE_ROOT.parent / relative)
    for name, relative in (('decision', 'decision'), ('console', 'ui/console'), ('assessment', 'situation'), ('execution', 'execution'))
}


def bootstrap_sources():
    for folder in (SOURCE_ROOTS['decision'] / 'src', SOURCE_ROOTS['assessment'], SOURCE_ROOTS['execution'] / 'src'):
        root = str(folder)
        if root not in sys.path:
            sys.path.insert(0, root)


def console_root():
    if (PACKAGE_ROOT / 'package.xml').is_file():
        return SOURCE_ROOTS['console']
    return PACKAGE_ROOT / 'fleet/server/web'
