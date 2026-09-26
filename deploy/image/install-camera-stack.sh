#!/usr/bin/env bash
# D-287: build the official Raspberry Pi PiSP stack inside the mounted ARM64 image.
set -euo pipefail

ROOT="${1:?mounted image root is required}"
SOURCES="${2:?camera source lock is required}"
REQUIREMENTS="${3:?camera Python lock is required}"
[[ "$(uname -m)" == aarch64 && $EUID -eq 0 ]] || { echo "native ARM64 root required" >&2; exit 1; }
[[ -d "$ROOT/usr" && -f "$SOURCES" && -f "$REQUIREMENTS" ]] || exit 1
BUILD="$ROOT/tmp/rosy-camera-build"
[[ ! -e "$BUILD" ]] || { echo "camera build directory already exists" >&2; exit 1; }
mkdir -p "$BUILD"
cleanup() { rm -rf -- "$BUILD"; }
trap cleanup EXIT

# Build inputs are only accepted from these four official repositories. The
# archive hash is checked before extraction, so a moved Git ref cannot alter it.
mapfile -t INPUTS < <(python3 - "$SOURCES" <<'PY'
import json
import re
import sys

lock = json.load(open(sys.argv[1], encoding="utf-8"))
names = ("libpisp", "libcamera", "rpicam-apps", "picamera2")
sources = lock.get("sources", [])
if lock.get("schema_version") != 1 or [s.get("name") for s in sources] != list(names):
    raise SystemExit("unexpected camera source lock")
for source in sources:
    name, commit, digest = (source.get(key, "") for key in ("name", "commit", "sha256"))
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SystemExit("invalid camera source pin")
    print(f"{name} {commit} {digest}")
PY
)
(( ${#INPUTS[@]} == 4 )) || { echo "camera source lock is incomplete" >&2; exit 1; }
for entry in "${INPUTS[@]}"; do
    read -r name commit digest <<< "$entry"
    archive="$BUILD/$name.tar.gz"
    curl --fail --location --proto '=https' --proto-redir '=https' --retry 3 \
        --output "$archive" "https://codeload.github.com/raspberrypi/$name/tar.gz/$commit"
    [[ "$(sha256sum "$archive" | cut -d' ' -f1)" == "$digest" ]] \
        || { echo "camera archive checksum mismatch: $name" >&2; exit 1; }
    mkdir -p "$BUILD/$name"
    tar -xzf "$archive" --strip-components=1 -C "$BUILD/$name"
done
cp "$REQUIREMENTS" "$BUILD/camera-python-requirements.txt"

# Keep runtime libraries and Python imports before taking the build-tool
# snapshot. Only packages introduced afterwards may be purged.
chroot "$ROOT" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    libboost-program-options1.83.0 libdrm2 libexif12 libjpeg-turbo8 libpng16-16t64 \
    libtiff6 libyaml-0-2 libgnutls30t64 python3-piexif python3-prctl
installed_packages() {
    chroot "$ROOT" dpkg-query -W -f='${db:Status-Status} ${Package}\n' \
        | awk '$1 == "installed" {print $2}' | LC_ALL=C sort -u
}
PACKAGES_BEFORE="$(installed_packages)"
chroot "$ROOT" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential meson ninja-build pkg-config python3-dev python3-setuptools python3-wheel \
    python3-ply python3-jinja2 pybind11-dev nlohmann-json3-dev \
    libboost-program-options-dev libgnutls28-dev libssl-dev libyaml-dev libudev-dev \
    libjpeg-dev libtiff-dev libpng-dev libexif-dev libdrm-dev

BUILD_IN_IMAGE=/tmp/rosy-camera-build
meson_build() {
    local project="$1"; shift
    chroot "$ROOT" env PKG_CONFIG_PATH=/usr/local/lib/aarch64-linux-gnu/pkgconfig \
        meson setup "$BUILD_IN_IMAGE/$project/build" "$BUILD_IN_IMAGE/$project" \
        --prefix=/usr/local --libdir=lib/aarch64-linux-gnu --buildtype=release "$@"
    chroot "$ROOT" meson compile -C "$BUILD_IN_IMAGE/$project/build" -j 2
    chroot "$ROOT" meson install -C "$BUILD_IN_IMAGE/$project/build"
    chroot "$ROOT" ldconfig
}
meson_build libpisp -Dlogging=disabled
meson_build libcamera -Dpipelines=rpi/pisp,rpi/vc4 -Dipas=rpi/pisp,rpi/vc4 \
    -Dpycamera=enabled -Dgstreamer=disabled -Dcam=disabled -Dqcam=disabled \
    -Dtest=false -Dlc-compliance=disabled -Ddocumentation=disabled -Dv4l2=false
meson_build rpicam-apps -Denable_libav=disabled -Denable_drm=disabled \
    -Denable_egl=disabled -Denable_qt=disabled -Denable_opencv=disabled \
    -Denable_tflite=disabled -Denable_hailo=disabled -Denable_imx500=disabled

# Ubuntu's /usr/local/dist-packages precedes apt's /usr/lib/python3 path.
# libcamera's Meson binding uses upstream site-packages, so expose that exact
# directory through a .pth file instead of copying the extension module.
PY_BINDING="$(find "$ROOT/usr/local/lib" -type d -name libcamera -path '*/python3.12/*-packages/libcamera' -print -quit)"
[[ -n "$PY_BINDING" ]] || { echo "libcamera Python binding missing" >&2; exit 1; }
PY_SITE="${PY_BINDING%/libcamera}"
install -d -m 0755 "$ROOT/usr/local/lib/python3.12/dist-packages"
printf '%s\n' "${PY_SITE#"$ROOT"}" \
    > "$ROOT/usr/local/lib/python3.12/dist-packages/rosy-libcamera.pth"
(umask 022 && chroot "$ROOT" python3 -m pip install --no-cache-dir --break-system-packages \
    --no-build-isolation --no-deps --require-hashes \
    -r "$BUILD_IN_IMAGE/camera-python-requirements.txt")
(umask 022 && chroot "$ROOT" python3 -m pip install --no-cache-dir --break-system-packages \
    --no-build-isolation --no-deps "$BUILD_IN_IMAGE/picamera2")
chroot "$ROOT" python3 -c 'import libcamera, picamera2, av, simplejpeg, pidng, v4l2'
chroot "$ROOT" /usr/local/bin/rpicam-still --version

# Preserve provenance in the image. The mounted-image verifier compares this
# record with the lock and checks the installed userspace files.
install -d -m 0755 "$ROOT/usr/local/share/rosy"
install -m 0644 "$SOURCES" "$ROOT/usr/local/share/rosy/camera-sources.lock.json"
sha256sum "$REQUIREMENTS" | cut -d' ' -f1 \
    > "$ROOT/usr/local/share/rosy/camera-python-runtime.sha256"
chmod 0644 "$ROOT/usr/local/share/rosy/camera-python-runtime.sha256"
mapfile -t BUILD_ONLY < <(comm -13 <(printf '%s\n' "$PACKAGES_BEFORE") <(installed_packages))
if (( ${#BUILD_ONLY[@]} > 0 )); then
    chroot "$ROOT" env DEBIAN_FRONTEND=noninteractive apt-get purge -y "${BUILD_ONLY[@]}"
fi
chroot "$ROOT" ldconfig
chroot "$ROOT" python3 -c 'import libcamera, picamera2, av, simplejpeg, pidng, v4l2'
chroot "$ROOT" /usr/local/bin/rpicam-still --version
