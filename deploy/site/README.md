# Ubuntu site server: Fleet and camera middleware

This Compose stack is the site control-plane host. It provides Fleet's browser
console and display-only sightings ingestion, plus camera frame reception and
ArUco projection. It does not replace the ROS 2 Jazzy/Pi product runtime. Fleet
does not join DDS, and sightings do not issue robot motion or pick commands.

## Contract path

```text
Ceiling phone -- WSS /overhead/v1/frames --> Vision (OpenCV + calibration)
Browser -- HTTPS --> Caddy --> Fleet console / sighting API
Vision -- HTTPS POST /api/fleet/sightings --> Caddy --> Fleet SQLite
Fleet -- existing CORE REST/WSS contracts --> robot CORE
```

## Same-LAN ROSY discovery

The shared service naming and trust rules are in
[`site-lan-discovery-profile.md`](../../docs/reference/site-lan-discovery-profile.md).
The robot and site host have separate DNS-SD service types. Other SERION
middleware can adopt the same public TXT keys under its own service type; a
discovered address does not enroll a device or grant a command path.

Each robot's boot-status service already advertises `_rosy._tcp.local` through
Avahi. The Ubuntu host runs `mdns-bridge.py` every 15 seconds and sends a full
resolved scan to Fleet. Fleet expires that read-only scan after 45 seconds. A
new device appears as **registration pending**; an endpoint already in
`robots.yaml` appears as **pairing pending** until its separately authenticated
FleetAgent HELLO confirms the same device name and an online device UID. A
duplicate name or mismatch appears as **conflict**. Discovery never grants
motion, changes a robot number, writes `robots.yaml`, or copies a token.

Install `avahi-daemon` and `avahi-utils` on the Ubuntu site host. Create a
distinct high-entropy `discovery_token` file in `${ROSY_SITE_SECRETS_DIR}`;
the same file is mounted as a Compose secret and read by the host bridge.
Keep it out of the checkout and grant read access only to root and the
`rosy-mdns` group. The tracked
`discovery-token.template.txt` describes its format, not its value. Install
`mdns-bridge.py` at `/opt/rosy/site/mdns-bridge.py`, and copy the supplied
`.service` and `.timer` files to `/etc/systemd/system/`. Create a system user
and group `rosy-mdns` with no login shell. Grant that group read access to
`discovery_token`; `site-ca.crt` is already public to the host service. Put
only the TLS URL in `/etc/rosy/site/mdns-bridge.env`, for example:

```ini
ROSY_SITE_DISCOVERY_URL=https://<site-fqdn>:8443/api/fleet/discovery/scan
```

The site FQDN must resolve from the Ubuntu host, its certificate must match,
and the Compose proxy must bind an address reachable through that FQDN.
Check `avahi-browse -rtpk _rosy._tcp` on the host, then start the timer with
`systemctl enable --now rosy-mdns-bridge.timer`. Check
`systemctl status rosy-mdns-bridge.service` and the Fleet discovery panel.
When Avahi or TLS fails, the bridge must not replace the last good scan with
an empty result; Fleet marks the scanner offline after its lease expires.
AP advertisements are excluded. On a VLAN or Wi-Fi with multicast/client
isolation, use the existing manual endpoint and outbound FleetAgent path.

For a 4–10 robot site, boot all cards on the same LAN and confirm one distinct
row per device, no duplicate-name conflict, all configured devices eventually
show **confirmed**, and newly initialized cards remain **registration pending**.
Reboot one robot, change its DHCP address, disconnect the site host, then
repeat the scan. A registered `.local` endpoint follows the changed address;
an IP-pinned `robots.yaml` entry needs an operator update and is never
silently rewritten from untrusted mDNS. The LAN test does not replace pairing, CORE health, or
physical motion acceptance.

All HTTPS hops verify the configured site CA. The same site certificate must
contain these DNS SANs: the operator-facing FQDN, the stable Ubuntu host's
`<hostname>.local`, `proxy`, `fleet`, and
`vision`. The phone pairing link uses that FQDN and explicit TLS:
`rosyov://<site-fqdn>:8443/?t=<phone-token>&s=ceiling_north&tls=1`.
Treat the URI as a credential: do not paste it into tickets, logs, or shell
history. Use the QR/pairing screen over a trusted local channel.

## Advertise and locate the Ubuntu Fleet PC

Choose a stable Ubuntu hostname before issuing the certificate. Install
`avahi-daemon` and `avahi-utils`, and check that TCP 8443 is reachable from
the intended robot/operator LAN. The site proxy's
`ROSY_SITE_BIND_ADDRESS` must name an approved LAN interface instead of
loopback when LAN clients need access. Set the same
`ROSY_SITE_HTTPS_PORT` in the private `/etc/rosy/site/.env` and the Compose
environment. Install `fleet-mdns.py` at `/opt/rosy/site/fleet-mdns.py`, copy
`rosy-fleet-advertise.service` to `/etc/systemd/system/`, then run:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now avahi-daemon rosy-fleet-advertise.service
avahi-browse -rtpk _rosy-fleet._tcp
python3 /opt/rosy/site/fleet-mdns.py discover
python3 /opt/rosy/site/fleet-mdns.py discover --expect-hostname <hostname>.local \
  --ca-file /etc/rosy/site/secrets/site-ca.crt
```

The final command prints an HTTPS URL only if exactly one matching site is
present and the certificate and `/healthz` response validate against the
separately installed CA. It connects to the Avahi resolved IP with TLS SNI set
to the expected hostname. Do not use the mDNS advertisement to supply the CA,
the expected hostname, Fleet pairing credentials, SSH identity, or robot
number. The SD's Fleet endpoint and trust profile populate only the robot's
expected `.local` hostname and site CA path. The one-time SD
`pairing_credential` is never a FleetAgent token. Install the separately
issued site CA at `/etc/rosy/trust/<trust_profile>.crt`, then provision the
same persistent pairing token as `fleet.pairing_token` in the robot CORE's
private `/var/lib/rosy/core/.rosy/rosy.yaml` and `fleet_pairing_token` in the
site's root-owned `robots.yaml`. Apply the token during a controlled CORE
restart after pairing approval. With the token in place, FleetAgent discovers
the site and reconnects over WSS automatically; without it, the robot stays
in registration/pairing wait. If a site is unreachable or multicast is
isolated, use the existing explicit endpoint.

## Prepare an Ubuntu host

Install Docker Engine and the Compose plugin from the approved Ubuntu package
source. Check `docker version` and `docker compose version`, then build the
two project images and pull the pinned Caddy image. Keep this deployment on a
host with a stable address and managed power; set host startup to run
`docker compose up -d` after Docker is ready. Do not install the site stack on
the robot Pi or enable robot motion through this stack.

Create `/etc/rosy/site` and `/etc/rosy/site/secrets` outside the checkout. Copy
`site-cameras.yaml.example`, `robots.yaml.example`, and
`site-users.yaml.example` there, then replace every map/calibration/device
placeholder with reviewed site data. `robots.yaml` contains CORE credentials
and must be owned by root with mode `0600`. Keep configuration read-only to the
containers. `site-users.yaml` contains only SHA-256 digests of individual user
tokens, never raw tokens; keep it owned by root and readable only by the Fleet
service group (`0440`, group `10001`).

Provision one independent high-entropy bearer token per named person through the
approved secret manager. Record that person's `principal_id`, one of `viewer`,
`operator`, or `policy-admin`, and the lowercase SHA-256 digest of the token in
`site-users.yaml`. Deliver each raw token through the secret manager; do not put
it in YAML, `.env`, command arguments, images, or logs. Rotate or revoke a user
by replacing or removing their digest and restarting Fleet. The API hashes the
presented bearer token and compares it against the configured digests. A viewer
can read Fleet state and task history. An operator can request, cancel, and stop
work. `policy-admin` is reserved for future policy endpoints; no policy mutation
route is exposed yet. All roles remain subject to CORE's local safety checks.

Generate independent high-entropy credentials with the approved secret
manager: Fleet registry access, phone-ingress, and vision-to-Fleet. Set each token
to a different value. Write one token per file (`operator_token`,
`phone_ingress_token`, `fleet_sighting_token`) without a trailing newline.
Tokens are mounted as Compose secrets; the process bootstrap reads them before
dropping to UID/GID `10001`. Do not put secret values in YAML, `.env`, command
arguments, images, or logs.

The `operator_token` protects the separate CORE registry readback endpoint. It
does not grant browser access to Fleet control APIs when `site-users.yaml` is
configured. The browser uses the individual token assigned to its user.

Issue a site TLS certificate and private key from the site's trusted CA. Include
the FQDN and service SANs above. Store `site.crt`, `site.key`, and
`site-ca.crt` in the secrets directory. On Linux, use root ownership; make the
private key readable only to root and group `10001` (`0440`, group `10001`),
and make the certificate and CA readable by UID/GID `10001` (`0444`). Never
commit these files. Provision the CA on ceiling phones and operator browsers.

## Durable task queue smoke check

Fleet stores operator tasks in SQLite at `/var/lib/rosy/fleet.sqlite3`, on the
same named `sighting_data` volume used by the site Compose service. The Compose
command passes this path with `--tasks-db`; do not move the SQLite file onto a
network share or mount it into a second writer.

On a development host, validate the rendered Compose configuration and build
the Fleet image before exercising an isolated local container:

```sh
docker compose -f deploy/site/compose.yaml config --quiet
docker compose -f deploy/site/compose.yaml build fleet
```

The 2026-09-26 Windows/Docker Desktop smoke test also started the built Fleet
image bound to loopback, submitted a task against a synthetic unreachable CORE
endpoint, restarted the container with the same named volume, and read the same
task back as `QUEUED`. This confirms local image startup, HTTP task intake, and
SQLite persistence across container restart. It does not prove full Compose,
Ubuntu, TLS, camera, real CORE, robot, GPU, or field acceptance. See
[`2026-09-26-site-task-scheduler-local.md`](../../docs/validation/2026-09-26-site-task-scheduler-local.md)
for the bounded evidence record.

Copy `.env.example` to a private operator-controlled env file and set
`ROSY_SITE_CONFIG_DIR` and `ROSY_SITE_SECRETS_DIR`. Leave the bind address at
`127.0.0.1` when access is through a local trusted reverse proxy or SSH tunnel;
otherwise use the site's approved interface address and restrict TCP 8443 at
the host firewall to operator and camera networks. Do not expose Fleet's
8090/8095 ports; only the HTTPS proxy port is published.

## Build and start

From this directory, with the private environment loaded. For a field candidate,
set `ROSY_SITE_IMAGE_TAG` to an immutable source revision; the `local` default
is for workstation smoke tests only. Build a transferable candidate from a
clean source checkout with Docker Buildx and Docker Scout installed:

```sh
candidate_dir="/secure/artifacts/rosy-site/$(git rev-parse HEAD)"
python3 deploy/site/build_candidate.py --output-dir "$candidate_dir"
```

The builder refuses a dirty checkout or an output directory inside the source
tree. It builds all three `linux/amd64` images using the full source commit as
their tag, exports `images.tar`, emits one SPDX SBOM per image, and records image
IDs plus SHA-256 hashes for the archive and deployment files in `release.json`.
The candidate contains only deployment instructions, the Compose/Caddy files,
and placeholder config templates; it never includes site credentials or filled
camera/robot configuration. Copy the candidate to the approved Ubuntu host using
the site's controlled transfer path and verify its archive hash against
`release.json` before loading:

```sh
cd /opt/rosy/candidate
sha256sum images.tar
docker image load --input images.tar
cp deploy/site/.env.example /etc/rosy/site/site.env
```

Set the image tag and private config paths in the operator-managed env file,
then run Compose with `--no-build` so the host uses the exact loaded candidate.
The bundle hash detects transfer damage; it does not authenticate the bundle's
origin. Do not treat this workstation-built candidate as field accepted until
the target host's loaded image IDs, GPU, phone, CORE robot, and recovery checks
are recorded.

For a local workstation smoke test, the commands below build the images in
place and start the local Compose stack:

```sh
docker compose --env-file /etc/rosy/site/site.env config --quiet
docker compose --env-file /etc/rosy/site/site.env build
docker compose --env-file /etc/rosy/site/site.env up -d
docker compose --env-file /etc/rosy/site/site.env ps
```

Inspect logs only for service health and error classes. Do not enable request
body/header logging or paste pairing URIs. Check `https://<site-fqdn>:8443/healthz`
from an authorized client and verify the browser console. Confirm Fleet sighting
readback through the authenticated API with a surveyed source. Record image
digests, config revision, calibration revision, backup location, and recovery
test in the deployment record.

Fleet stores sightings and authenticated CORE Agent event history in the same
named SQLite volume with WAL and full synchronous commit. Pairing a CORE Agent
requires `--events-db`; the Compose stack points it at
`/var/lib/rosy/fleet.sqlite3`. Read the event audit through the authenticated
`GET /api/fleet/events` cursor API. Back it up with `SightingStore.backup()` or
a quiesced SQLite-aware backup; do not copy only the live main DB file while
WAL is active. Protect the backup as operational data, test restore to a
separate volume, and define site retention before production operation.

The same named volume stores operator task requests, append-only task status
history, and per-user mutation audit (`--tasks-db`). An externally reachable
Fleet console requires `site-users.yaml` and this persistent database. Browser
navigation requests to `/api/fleet/robots/{robot_id}/goal` or navigation intents
through `/api/fleet/do` include an `Idempotency-Key`; read task status and
history through `GET /api/fleet/tasks/{task_id}`. Mutations are audited before
dispatch; an audit storage failure blocks the CORE request. Ambiguous command
results remain `UNKNOWN` and are never retried automatically. Policy-generated
navigation remains `HOLD` until the D-268 acceptance contract is approved;
D-177 command correlation and CORE ACK/final-result reconciliation remain
outstanding.

## Current acceptance boundary

The stack is local-testable, but installing and running it on an Ubuntu control
PC requires a real site hostname, trusted certificate/CA, operator and camera
credentials, surveyed camera geometry, CORE endpoint credentials, host access,
and an approved network/firewall rule. Successful container health checks do
not prove phone pairing, site calibration, CORE connectivity, robot behavior,
or field acceptance. D-257/D-268 remain at their recorded status; autonomous
movement and pick are disabled pending those gates.

## RTX 5080 GPU preflight

The current `vision` image runs the CPU ArUco pipeline. The site Compose file
does not reserve a GPU, and the current candidate contains no CUDA inference
model. Treat the following as a host/runtime preflight only; passing it does not
accept vision accuracy, model latency, or autonomous-task evidence.

On the target Ubuntu host, record the hostname, Ubuntu release, and the full
`nvidia-smi` output. Confirm that it identifies the expected RTX 5080 and a
loaded NVIDIA driver. Install the NVIDIA Container Toolkit using its official
Ubuntu instructions, configure Docker, and restart the daemon:

```sh
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker version
docker compose version
```

Then verify that a container can see the GPU, using NVIDIA's
[CUDA 12.8.1 Ubuntu 24.04 base image](https://hub.docker.com/r/nvidia/cuda/tags?name=12.8.1-base-ubuntu24.04):

```sh
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
```

Record the resolved test-image digest and output in the private host evidence.
If the host or container cannot identify the GPU, stop the GPU deployment gate;
do not mark the CPU vision service as GPU-accepted. NVIDIA documents the driver
and Docker runtime setup in its [Container Toolkit install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

Before adding a GPU reservation to Compose, select the inference framework,
model, and immutable image revision. Confirm the deployed application contains
[Blackwell-compatible GPU code](https://docs.nvidia.com/cuda/archive/12.8.1/pdf/Blackwell_Compatibility_Guide.pdf)
(native cubin for compute capability 10.0 or compatible PTX), then record
model/framework/CUDA versions, image digest, peak
VRAM, thermal behavior, and measured frame-to-sighting latency under expected
load. Docker Compose GPU device reservations require a GPU-capable host and
configured daemon; add one only to the selected inference service, with an
explicit GPU capability ([Docker Compose GPU support](https://docs.docker.com/compose/how-tos/gpu-support/)).
Keep the current CPU ArUco sighting path distinct from any future GPU-model
result. If the GPU/model is unavailable, mark GPU-dependent evidence `DEGRADED`
and do not silently substitute CPU ArUco results. These measurements do not
enable automatic movement; D-257/D-268 and the separate freshness and
false-trigger gates still apply.
