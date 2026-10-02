# D-410 device twin: a systemd container standing in for a Pinky Pro robot.
# Twin-only; never part of the device image or a payload. run_twin.py builds it
# from a context it assembles under X:\DevTemp\d406-twin\ctx (LF content from
# `git archive HEAD`).
FROM ubuntu:24.04 AS base
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends systemd systemd-sysv dbus python3 openssl tar curl \
      iproute2 sudo ca-certificates udev kmod \
 && rm -rf /var/lib/apt/lists/*

FROM base AS twin
COPY . /tmp/twin-ctx/
RUN bash /tmp/twin-ctx/twin/image/install_twin.sh /tmp/twin-ctx && rm -rf /tmp/twin-ctx
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
