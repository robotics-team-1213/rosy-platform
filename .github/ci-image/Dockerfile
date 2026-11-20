# Prebuilt CI image (user 11-20, GitHub landing migration): everything ci.yml used to install per job.
# Built by .github/workflows/build-ci-image.yml with the repository root as the build context.
FROM ros:jazzy-ros-base@sha256:00b8d47a6e6384a2834e3d01fa87ae767876543baa574f2d64a75c04ea33c698

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PIP_BREAK_SYSTEM_PACKAGES=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    ROSY_TEST_RAUC_DEB=/opt/rosy-ci/debs/rauc_1.11.3-2_amd64.deb \
    PYTHONPATH=/opt/rosy-ci/receiver-crypto

COPY deploy/robot/pinky_pro/image/device-python-requirements.txt /opt/rosy-ci/src/device-python-requirements.txt
COPY deploy/robot/pinky_pro/image/receiver-crypto-requirements.txt /opt/rosy-ci/src/receiver-crypto-requirements.txt
COPY deploy/robot/omx/requirements-cell.lock /opt/rosy-ci/src/requirements-cell.lock

# openssl: the release signing contract requires OpenSSL 3 raw Ed25519.
# python3-opencv: the lane live viewer imports cv2 at module top (main red since 650fad89, 2026-09-24).
# The rauc and slam_toolbox debs are only downloaded: the RAUC fixtures verify the exact package bytes,
# and the boot smoke needs slam_toolbox absent from the image (ci.yml unpacks it for the SaveMap guard).
RUN set -eux; \
    sed -i 's|http://archive.ubuntu.com|http://azure.archive.ubuntu.com|g; s|http://security.ubuntu.com|http://azure.archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list 2>/dev/null || true; printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\n' > /etc/apt/apt.conf.d/80-ci-retries; \
    apt-get update -qq; \
    apt-get install -y -qq nodejs python3-colcon-common-extensions python3-pip python3-wheel openssl openssh-client zstd python3-opencv python3-pil rauc=1.11.3-2 squashfs-tools ros-jazzy-xacro ros-jazzy-realtime-tools ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-nav2-msgs ros-jazzy-control-msgs ros-jazzy-controller-manager-msgs fonts-noto-cjk; \
    mkdir -p /opt/rosy-ci/debs; cd /opt/rosy-ci/debs; apt-get download -qq rauc=1.11.3-2 ros-jazzy-slam-toolbox; \
    rm -rf /var/lib/apt/lists/*

# D-189: the CORE runtime is the hash-locked set the device image carries; --ignore-installed as in ci.yml before.
RUN pip3 install --ignore-installed --require-hashes --no-deps --only-binary=:all: -r /opt/rosy-ci/src/device-python-requirements.txt
# Test tools use the locked set as constraints (a hashed file as constraints would force hash mode: name==version lines only).
RUN grep -o '^[A-Za-z0-9._-]*==[^ ]*' /opt/rosy-ci/src/device-python-requirements.txt > /opt/rosy-ci/runtime-constraints.txt
# playwright is pinned: 1.65.0 (2026-11-09) enforces the inert attribute and turned the ui-confirm browser tests red.
RUN pip3 install -c /opt/rosy-ci/runtime-constraints.txt flake8 httpx==0.28.1 pyyaml jsonschema ext4 playwright==1.64.1 pytest-xdist
# Account authority imports oauthlib and joserfc at module top; tests that run python3 -I need them system-wide.
RUN pip3 install --no-deps oauthlib==4.0.0 joserfc==1.7.5
# D-456: the same hash-locked receiver crypto as the signed ARM payload (AMD64 wheel hashes), kept off the system path.
RUN pip3 install --require-hashes --no-deps --only-binary=:all: --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --target /opt/rosy-ci/receiver-crypto -r /opt/rosy-ci/src/receiver-crypto-requirements.txt \
 && pip3 install --no-deps --target /opt/rosy-ci/receiver-crypto joserfc==1.7.5
# The OMX cell lock's OpenCV 4.12 and NumPy 2.2 (apt python3-opencv is 4.6); ci.yml adds the path only for test/test_omx_cell.
RUN grep -E '^(numpy|opencv-python-headless)==' /opt/rosy-ci/src/requirements-cell.lock > /tmp/cell-vision.txt \
 && pip3 install --target /opt/rosy-ci/omx-cell-vision -r /tmp/cell-vision.txt && rm /tmp/cell-vision.txt
RUN python3 -m playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
