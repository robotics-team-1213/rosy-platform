"""호스트 pytest가 colcon 설치 없이 core_common 을 임포트하게 한다(D-61 선례)."""

import sys
import types
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]  # .../src/core/core_common

if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))


@pytest.fixture
def fake_ament(monkeypatch):
    """Install a fake `ament_index_python.packages` whose lookup is `get(name, PackageNotFoundError)` (D-196).

    Path tests must not depend on whether the box has a sourced ROS overlay: on a
    sourced box the real ament share would win over the source-tree fallback.
    """

    def install(get):
        package = types.ModuleType("ament_index_python")
        packages = types.ModuleType("ament_index_python.packages")

        class PackageNotFoundError(KeyError):
            pass

        packages.PackageNotFoundError = PackageNotFoundError
        packages.get_package_share_directory = lambda name: get(name, PackageNotFoundError)
        package.packages = packages
        monkeypatch.setitem(sys.modules, "ament_index_python", package)
        monkeypatch.setitem(sys.modules, "ament_index_python.packages", packages)
        return packages

    return install


@pytest.fixture
def no_ament_share(fake_ament):
    """ament is importable but knows no robot package: the source fallback decides."""

    def missing(name, not_found):
        raise not_found(name)

    return fake_ament(missing)
