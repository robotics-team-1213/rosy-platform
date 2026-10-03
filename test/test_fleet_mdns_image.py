"""The native image must carry the tools used by FleetAgent discovery."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_image_installs_avahi_browse_and_local_hostname_support():
    source = (ROOT / "deploy/robot/pinky_pro/image/customize-rootfs.sh").read_text(encoding="utf-8")
    install = source.split("apt-get install -y --no-install-recommends", 1)[1].split("\n\n", 1)[0]
    assert {"avahi-daemon", "avahi-utils", "libnss-mdns"} <= set(
        install.replace("\\\n", " ").split())


def test_site_stack_starts_avahi_before_fleet_local_name_resolution():
    # Fleet NSS uses the host Avahi socket. Requires alone does not order start
    # jobs: the daemon must also finish starting before Compose binds its directory.
    source = (ROOT / "deploy/site/rosy-site-stack.service").read_text(encoding="utf-8")
    unit = source.split("[Unit]", 1)[1].split("[Service]", 1)[0]
    dependencies = {}
    for line in unit.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            dependencies.setdefault(key, set()).update(value.split())
    assert {"docker.service", "avahi-daemon.service"} <= dependencies["Requires"]
    assert {"docker.service", "avahi-daemon.service"} <= dependencies["After"]
