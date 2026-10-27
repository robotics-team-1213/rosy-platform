"""Factory images must ship the pinned verifier without upstream open D-Bus service policy."""
import re

import pytest
import yaml

from test_image_customization_contract import _valid_root, _verify, IMAGE, CUSTOMIZER


def test_native_customizer_installs_the_locked_rauc_binary_package():
    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text())
    assert lock["os_updates"]["rauc_package_version"] == "1.11.3-2"
    source = CUSTOMIZER.read_text()
    assert "lock_value os_updates rauc_package_version" in source
    assert '"rauc=$RAUC_PACKAGE_VERSION"' in source
    assert "rauc-service" not in source


@pytest.mark.parametrize("case", ["absent", "wrong_version", "upstream_service"])
def test_mounted_image_refuses_missing_or_incompatible_rauc(tmp_path, case):
    root = _valid_root(tmp_path)
    status = root / "var/lib/dpkg/status"
    text = status.read_text()
    if case == "absent":
        text = re.sub(r"Package: rauc\n.*?\n\n", "", text, flags=re.S)
        (root / "usr/bin/rauc").unlink(missing_ok=True)
    elif case == "wrong_version":
        text += "Package: rauc\nStatus: install ok installed\nVersion: 1.10.0\n\n"
    else:
        text += "Package: rauc-service\nStatus: install ok installed\nVersion: 1.11.3-2\n\n"
    status.write_text(text)
    result = _verify(root)
    assert result.returncode != 0
    assert "RAUC" in result.stderr
