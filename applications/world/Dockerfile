FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libnss-mdns avahi-utils \
    && sed -i 's/^hosts:.*/hosts: files mdns4_minimal [NOTFOUND=return] dns mdns4/' /etc/nsswitch.conf \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir zeroconf==0.151.5 \
    && groupadd --gid 10001 rosy \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin rosy

WORKDIR /world
EXPOSE 8140
USER 10001:10001
