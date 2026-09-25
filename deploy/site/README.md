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
Fleet -- existing CORE REST/DDS contracts --> robot CORE
```

All HTTPS hops verify the configured site CA. The same site certificate must
contain these DNS SANs: the operator-facing FQDN, `proxy`, `fleet`, and
`vision`. The phone pairing link uses that FQDN and explicit TLS:
`rosyov://<site-fqdn>:8443/?t=<phone-token>&s=ceiling_north&tls=1`.
Treat the URI as a credential: do not paste it into tickets, logs, or shell
history. Use the QR/pairing screen over a trusted local channel.

## Prepare an Ubuntu host

Install Docker Engine and the Compose plugin from the approved Ubuntu package
source. Check `docker version` and `docker compose version`, then build the
two project images and pull the pinned Caddy image. Keep this deployment on a
host with a stable address and managed power; set host startup to run
`docker compose up -d` after Docker is ready. Do not install the site stack on
the robot Pi or enable robot motion through this stack.

Create `/etc/rosy/site` and `/etc/rosy/site/secrets` outside the checkout. Copy
`site-cameras.yaml.example` and `robots.yaml.example` there, then replace every
map/calibration/device placeholder with reviewed site data. `robots.yaml`
contains CORE credentials and must be owned by root with mode `0600`.
Keep configuration read-only to the containers.

Generate three independent high-entropy credentials with the approved secret
manager: operator-console, phone-ingress, and vision-to-Fleet. Set each token
to a different value. Write one token per file (`operator_token`,
`phone_ingress_token`, `fleet_sighting_token`) without a trailing newline.
Tokens are mounted as Compose secrets; the process bootstrap reads them before
dropping to UID/GID `10001`. Do not put secret values in YAML, `.env`, command
arguments, images, or logs.

Issue a site TLS certificate and private key from the site's trusted CA. Include
the FQDN and service SANs above. Store `site.crt`, `site.key`, and
`site-ca.crt` in the secrets directory. On Linux, use root ownership; make the
private key readable only to root and group `10001` (`0440`, group `10001`),
and make the certificate and CA readable by UID/GID `10001` (`0444`). Never
commit these files. Provision the CA on ceiling phones and operator browsers.

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

The same named volume stores operator task requests and append-only status
history (`--tasks-db`). An externally reachable Fleet console requires both an
operator token and this persistent task database. Browser navigation requests
to `/api/fleet/robots/{robot_id}/goal` or navigation intents through
`/api/fleet/do` include an `Idempotency-Key`; read status and audit history through the
authenticated `GET /api/fleet/tasks/{task_id}` route. The shared console token
is currently recorded as `site-console`, so this does not provide per-user
identity or role based access. Ambiguous command results remain `UNKNOWN` and
are never retried automatically. Policy generated navigation remains `HOLD`
until the D-268 acceptance contract is approved; D-177 command correlation and
CORE ACK/final-result reconciliation are still outstanding.

## Current acceptance boundary

The stack is local-testable, but installing and running it on an Ubuntu control
PC requires a real site hostname, trusted certificate/CA, operator and camera
credentials, surveyed camera geometry, CORE endpoint credentials, host access,
and an approved network/firewall rule. Successful container health checks do
not prove phone pairing, site calibration, CORE connectivity, robot behavior,
or field acceptance. D-257/D-268 remain at their recorded status; autonomous
movement and pick are disabled pending those gates.
