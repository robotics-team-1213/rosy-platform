"""Resolve bundled Jazzy libraries using the selected SDK's own Python."""
from pathlib import Path
import sysconfig


def library_path(site_packages):
    for extension in ('isaacsim.ros2.core', 'isaacsim.ros2.bridge'):
        candidate = Path(site_packages)/'isaacsim/exts'/extension/'jazzy/lib'
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError('Selected SDK has no bundled Jazzy libraries')


if __name__ == '__main__':
    print(library_path(Path(sysconfig.get_path('purelib'))))
