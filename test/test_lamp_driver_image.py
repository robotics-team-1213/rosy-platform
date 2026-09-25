"""D-247: the image carries the WS2812 lamp driver (rp1_ws281x_pwm) for its own kernel.

Verified on rosy_18 (Pi 5 rev 1.1, board 0xd04171, 6.8.0-1064-raspi) on
2026-09-26: the pinned rpi_ws281x module builds on 6.8 only with
`.remove_new`, its overlay must target /axi/pcie@120000/rp1 and mux GPIO19 to
pwm0, the driver must run with pwm_channel=3 (channel 2 is GPIO18, the LCD
backlight), and the library needs the Pi 5 rev 1.1 board ids to init.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "deploy" / "image"
CUSTOMIZER = IMAGE / "customize-rootfs.sh"
DEPS = IMAGE / "install-pinky-hardware-deps.sh"
PAYLOAD = IMAGE / "build-native-payload.sh"
LOCK = IMAGE / "inputs.lock.yaml"
OVERLAY = IMAGE / "overlays" / "rosy-ws281x.dts"
PATCH = IMAGE / "patches" / "rpi_ws281x-pi5-rev1.1.patch"
UDEV = ROOT / "deploy" / "robot" / "udev" / "99-rosy-lamp.rules"
MODPROBE = ROOT / "deploy" / "robot" / "modprobe" / "rosy-ws281x.conf"

sys.path.insert(0, str(ROOT / "test"))
from test_image_customization_contract import _valid_root, _verify  # noqa: E402


def _code(path: Path) -> str:
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))


def test_the_lock_pins_the_patch_bytes():
    hardware = yaml.safe_load(LOCK.read_text(encoding="utf-8"))["hardware_dependencies"]
    assert hardware["rpi_ws281x_pi5_patch"] == "patches/rpi_ws281x-pi5-rev1.1.patch"
    assert hashlib.sha256(PATCH.read_bytes()).hexdigest() == hardware["rpi_ws281x_pi5_patch_sha256"]
    assert b"\r\n" not in PATCH.read_bytes()


def test_the_patch_adds_exactly_the_pi5_rev_1_1_board_ids():
    added = [line for line in PATCH.read_text(encoding="utf-8").splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    ids = [line.split("=")[1].strip(" ,") for line in added if ".hwver" in line]
    assert ids == ["0xd04171", "0xc04171", "0xb04171"]
    assert sum("RPI_HWVER_TYPE_PI5" in line for line in added) == 3
    assert all(".periph_base = 0," in line or ".videocore_base = 0," in line
               for line in added if "_base" in line)
    assert not [line for line in PATCH.read_text(encoding="utf-8").splitlines()
                if line.startswith("-") and not line.startswith("---")]


def test_lamp_control_links_the_patched_library():
    source = DEPS.read_text(encoding="utf-8")
    for fragment in ("rpi_ws281x_pi5_patch", "rpi_ws281x_pi5_patch_sha256", "sha256sum \"$WS281X_PATCH\"",
                     'patch --directory="$WORK/source" --strip=1 --forward --batch < "$WS281X_PATCH"',
                     "grep -q '0xd04171'"):
        assert fragment in source, fragment
    # Checked before use, applied after extraction and before the library is built.
    assert source.index("WS281X_PATCH_SHA256\" ]]") < source.index("patch --directory")
    assert source.index('tar -xzf "$WS281X_ARCHIVE"') < source.index("patch --directory") \
        < source.index('cmake -S "$WORK/source"')
    assert "tar cmake patch; do" in source


def test_the_overlay_is_the_one_verified_on_rosy_18():
    text = OVERLAY.read_text(encoding="utf-8")
    assert 'target-path = "/axi/pcie@120000/rp1";' in text
    assert text.count("target-path") == 1  # upstream's /axi/pcie@1000120000/rp1 is gone
    assert 'function = "pwm0";' in text and 'pins = "gpio19";' in text
    assert 'compatible = "rp1-ws281x-pwm";' in text
    assert "reg = <0xc0 0x40098000 0x00 0x100>;" in text
    assert "dmas = <&rp1_dma 0x18>;" in text and 'dma-names = "pwm0";' in text
    assert "pinctrl-0 = <&rosy_ws281x_pins>;" in text
    assert "assigned-clock-rates = <2400000>;" in text
    assert b"\r\n" not in OVERLAY.read_bytes()


def test_the_driver_drives_gpio19_not_the_lcd_backlight():
    lines = [line.strip() for line in MODPROBE.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    assert lines == ["options rp1_ws281x_pwm pwm_channel=3"]
    rule = UDEV.read_text(encoding="utf-8")
    assert 'SUBSYSTEM=="misc", KERNEL=="ws281x_pwm", OWNER="root", GROUP="root", MODE="0600"' in rule
    assert "gpio" not in rule.split("ACTION==", 1)[1]


def test_the_payload_ships_the_rule_and_the_channel():
    source = PAYLOAD.read_text(encoding="utf-8")
    assert 'LAMP_UDEV_RULE_SOURCE="$WORKSPACE/deploy/robot/udev/99-rosy-lamp.rules"' in source
    assert 'LAMP_MODPROBE_SOURCE="$WORKSPACE/deploy/robot/modprobe/rosy-ws281x.conf"' in source
    assert 'cp "$LAMP_UDEV_RULE_SOURCE" "$OVERLAY/etc/udev/rules.d/"' in source
    assert 'cp "$LAMP_MODPROBE_SOURCE" "$OVERLAY/etc/modprobe.d/rosy-ws281x.conf"' in source


def test_the_image_builds_the_module_for_its_own_kernel():
    code = _code(CUSTOMIZER)
    # The kernel the image boots: the only /lib/modules entry, or ROSY_IMAGE_KERNEL.
    assert 'IMAGE_KERNEL="$ROSY_IMAGE_KERNEL"' in code
    assert 'find "$ROOT/lib/modules" -mindepth 1 -maxdepth 1 -type d' in code
    assert "set ROSY_IMAGE_KERNEL" in code
    assert '"linux-headers-$IMAGE_KERNEL" make gcc device-tree-compiler' in code
    # The same locked archive, re-checked here.
    assert '"$(sha256sum "$WS281X_TMP" | awk \'{print $1}\')" == "$WS281X_SHA"' in code
    assert '"rpi_ws281x-$WS281X_COMMIT/rp1_ws281x_pwm"' in code
    # .remove_new only before 6.11, and the edit must have happened.
    guard = code.index("KERNEL_MINOR < 11")
    assert guard < code.index(".remove_new = rp1_ws281x_pwm_remove") < code.index(
        'make -C "/lib/modules/$IMAGE_KERNEL/build" M=/tmp/rosy-ws281x modules')
    assert "could not adapt rp1_ws281x_pwm" in code
    assert '"$ROOT/lib/modules/$IMAGE_KERNEL/extra/rp1_ws281x_pwm.ko"' in code
    assert code.index("extra/rp1_ws281x_pwm.ko") < code.index('depmod "$IMAGE_KERNEL"')
    assert "dtc -@ -I dts -O dtb -o /boot/firmware/overlays/rosy-ws281x.dtbo" in code
    assert '> "$ROOT/usr/local/share/rosy/lamp-driver-kernel"' in code
    # Before the package list is recorded and before the image is accepted.
    build = code.index('depmod "$IMAGE_KERNEL"')
    assert build < code.index("deb-packages.txt") < code.index("verify-mounted-image.py")
    call = 'bash "$BOOT_OVERLAY" --image-root "$ROOT" --overlay "dtoverlay=rosy-ws281x"'
    assert call in code and code.index(call) < code.index("verify-mounted-image.py")
    assert 'rm -rf -- "$ROOT/tmp/rosy-ws281x"' in code  # cleanup on any exit


def test_the_image_purges_the_build_tools_it_added_and_holds_the_kernel():
    code = _code(CUSTOMIZER)
    # Snapshot before the tools arrive; purge only the difference, after the last dtc.
    before = code.index('PACKAGES_BEFORE_LAMP="$(installed_packages)"')
    install = code.index('"linux-headers-$IMAGE_KERNEL" make gcc device-tree-compiler')
    purge = code.index('apt-get purge -y "${LAMP_BUILD_ONLY[@]}"')
    assert before < install < code.index("dtc -@ -I dts") < purge
    assert 'comm -13 <(printf \'%s\\n\' "$PACKAGES_BEFORE_LAMP") <(installed_packages)' in code
    assert "autoremove" not in code  # never removes what something else installed
    # The kernel the module was built for is held; image and modules are required.
    hold = code.index('apt-mark hold "${KERNEL_HOLDS[@]}"')
    assert purge < hold < code.index("deb-packages.txt") < code.index("verify-mounted-image.py")
    assert 'for package in "linux-image-$IMAGE_KERNEL" "linux-modules-$IMAGE_KERNEL"; do' in code
    assert 'for package in "linux-headers-$IMAGE_KERNEL" linux-raspi linux-image-raspi linux-headers-raspi; do' \
        in code


def test_the_remove_new_edit_matches_the_pinned_source_line():
    # The pinned rp1_ws281x_pwm.c has a tab-indented `.remove = rp1_ws281x_pwm_remove,`.
    import re

    code = CUSTOMIZER.read_text(encoding="utf-8")
    sed = re.search(r"sed -i 's/(.+?)/(.+?)/'", code)
    assert sed, "the .remove_new sed is missing"
    pattern = sed.group(1).replace(r"\(", "(").replace(r"\)", ")").replace("[[:space:]]", r"\s")
    assert re.fullmatch(pattern, "\t.remove = rp1_ws281x_pwm_remove,")
    assert sed.group(2) == r"\1.remove_new = rp1_ws281x_pwm_remove,"


def test_the_verifier_accepts_the_lamp_driver(tmp_path):
    completed = _verify(_valid_root(tmp_path))
    assert "lamp" not in completed.stderr, completed.stderr


@pytest.mark.parametrize(("defect", "finding"), [
    (lambda root: (root / "boot/firmware/overlays/rosy-ws281x.dtbo").unlink(),
     "missing lamp overlay: boot/firmware/overlays/rosy-ws281x.dtbo"),
    (lambda root: (root / "lib/modules/6.8.0-1064-raspi/extra/rp1_ws281x_pwm.ko").unlink(),
     "missing lamp driver module: lib/modules/6.8.0-1064-raspi/extra/rp1_ws281x_pwm.ko"),
    (lambda root: (root / "lib/modules/6.8.0-1064-raspi/modules.alias").write_text("", encoding="utf-8"),
     "lamp driver is not in lib/modules/6.8.0-1064-raspi/modules.alias"),
    (lambda root: (root / "lib/modules/6.8.0-1064-raspi/extra/rp1_ws281x_pwm.ko").write_bytes(
        b"\x7fELF\0vermagic=6.8.0-1063-raspi SMP preempt mod_unload aarch64\0"),
     "lamp driver module vermagic 6.8.0-1063-raspi does not match the recorded kernel 6.8.0-1064-raspi"),
    (lambda root: (root / "lib/modules/6.8.0-1064-raspi/extra/rp1_ws281x_pwm.ko").write_bytes(b"\x7fELF"),
     "lamp driver module has no vermagic (recorded kernel 6.8.0-1064-raspi)"),
    (lambda root: (root / "var/lib/dpkg/status").write_text(
        (root / "var/lib/dpkg/status").read_text(encoding="utf-8").replace(
            "Package: linux-image-6.8.0-1064-raspi\nStatus: hold ok installed", "Package: linux-image-6.8.0-1064-raspi\nStatus: install ok installed"),
        encoding="utf-8"),
     "kernel package is not held for the lamp driver: linux-image-6.8.0-1064-raspi"),
    (lambda root: (root / "var/lib/dpkg/status").write_text(
        (root / "var/lib/dpkg/status").read_text(encoding="utf-8").replace(
            "Package: linux-modules-6.8.0-1064-raspi\nStatus: hold ok installed", "Package: linux-modules-6.8.0-1064-raspi\nStatus: install ok installed"),
        encoding="utf-8"),
     "kernel package is not held for the lamp driver: linux-modules-6.8.0-1064-raspi"),
    (lambda root: (root / "var/lib/dpkg/status").write_text(
        (root / "var/lib/dpkg/status").read_text(encoding="utf-8").replace(
            "Package: linux-raspi\nStatus: hold ok installed", "Package: linux-raspi\nStatus: install ok installed"),
        encoding="utf-8"),
     "kernel package is not held for the lamp driver: linux-raspi"),
    (lambda root: (root / "usr/local/share/rosy/lamp-driver-kernel").write_text("6.9.0-1-raspi\n",
                                                                             encoding="utf-8"),
     "lamp driver was built for 6.9.0-1-raspi, which the image does not carry"),
    (lambda root: (root / "usr/local/share/rosy/lamp-driver-kernel").unlink(),
     "missing lamp driver kernel record"),
    (lambda root: (root / "etc/udev/rules.d/99-rosy-lamp.rules").unlink(),
     "missing lamp udev rule: etc/udev/rules.d/99-rosy-lamp.rules"),
    (lambda root: (root / "etc/modprobe.d/rosy-ws281x.conf").write_text(
        "options rp1_ws281x_pwm pwm_channel=2\n", encoding="utf-8"),
     "does not set pwm_channel=3"),
    (lambda root: (root / "boot/firmware/config.txt").write_text(
        (root / "boot/firmware/config.txt").read_text(encoding="utf-8").replace("dtoverlay=rosy-ws281x", ""),
        encoding="utf-8"),
     "does not enable dtoverlay=rosy-ws281x for the Pi 5 (lamp driver)"),
])
def test_the_verifier_names_each_missing_lamp_driver_part(tmp_path, defect, finding):
    root = _valid_root(tmp_path)
    defect(root)
    completed = _verify(root)
    assert completed.returncode != 0
    assert finding in completed.stderr
