"""The native image must carry the tools used by FleetAgent discovery."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_image_installs_avahi_browse_and_local_hostname_support():
    source = (ROOT / "deploy/image/customize-rootfs.sh").read_text(encoding="utf-8")
    install = source.split("apt-get install -y --no-install-recommends", 1)[1].split("\n\n", 1)[0]
    assert {"avahi-daemon", "avahi-utils", "libnss-mdns"} <= set(
        install.replace("\\\n", " ").split())
