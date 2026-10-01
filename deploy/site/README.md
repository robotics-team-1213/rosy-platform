# Ubuntu site server: Fleet and camera middleware

This Compose stack is the site control-plane host. It provides Fleet's browser
console and display-only sightings ingestion, plus camera frame reception and
ArUco projection. It does not replace the ROS 2 Jazzy/Pi product runtime. Fleet
does not join DDS, and sightings do not issue robot motion or pick commands.

## Where the control console runs

| Role | Installation and current responsibility |
|---|---|
| Ubuntu site host | Runs this Compose stack: Caddy, Fleet `/console` and task SQLite, and Vision. It is the current site control server. |
| Operator PC | Opens `https://<site-fqdn>:8443/console` after the site endpoint is configured, using a named Fleet user credential and the site CA. It does not need Fleet, Docker, or ROS 2 installed. It may be the same physical PC as the site host. |
| Pinky Pi | Runs local CORE and its own `/console` at the robot origin. Fleet submits accepted CORE API requests; CORE keeps final motion and stop authority. |
| OMX workcell host | Local controller per arm/workcell remains a separate placement and acceptance gate (D-281/D-282). Current Fleet console does not operate OMX arms. |
| Future GPU host | May run separate perception/inference workloads after a placement decision; it does not become the mission or console authority merely by hosting compute. |

`ROSY Console` names the human-facing product surface (D-290). The running site
screen is still the Fleet console; there is no separate Operations mission
server, natural-language interpreter, or multi-device OMX mission UI. Browser
and robot `/console` share a path segment but have different origins and
credentials (D-275). A site outage removes site control visibility and new
site work, while Pinky local CORE/stop must continue independently.

For an operator PC on another machine, the default loopback bind in
`.env.example` is insufficient. Before granting access, choose the approved
site FQDN and LAN interface, issue a certificate with that FQDN, set
`ROSY_SITE_BIND_ADDRESS` to the interface address in the private site env,
limit TCP 8443 to approved operator/camera networks, and provision separate
named user credentials. Keep Fleet 8090 and Vision 8095 unpublished. From the
operator PC, verify the trusted `https://<site-fqdn>:8443/healthz`, open
`/console`, confirm a viewer cannot submit work, and confirm an operator's
request appears in task history with its real status. An HTTP acceptance is
not proof of robot completion. Record the site host, client PC, image digest,
certificate identity, config revision, and readback in the site validation
record. These steps require the actual site host and devices for SITE/FIELD
acceptance; local Compose checks establish only LOCAL behavior.

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
`rosyov://<site-fqdn>:8443/?t=<phone-token>&s=ceiling_north&tls=1&pin=sha256/<b64url>`.
The `pin` makes the app trust only this site's certificate, so the site CA is
not installed on the phone (D-341 9). The pin is always the **site CA**
(D-341 9 never pins a leaf alone), so it survives leaf re-issue. The phone can
only match certificates the proxy sends, so the proxy must serve leaf + CA. Caddy
serves the whole `site_cert` file, so build it once with
`cat site.crt site-ca.crt > site-fullchain.crt` and point the `site_cert`
secret at `site-fullchain.crt`. Then print the link and QR on the site host:
`ROSY_OVERHEAD_TOKEN=<phone-token> rosy-vision pair-link --host <tls_host>
--port <published-8443> --source ceiling_north --pin-ca <secrets>/site-ca.crt
--pin-cert <secrets>/site-fullchain.crt`. Both options are required: the
command refuses (exit 2, with this recipe) unless the served file carries that
CA above the leaf. `rosy-vision receive --tls-cert` pins the CA of a leaf + CA
file and otherwise prints the link without a pin and says why. The app still
accepts a leaf pin from links printed before this rule, for compatibility only.
The link host is the `tls_host` name by default (`<name>.local` or the site FQDN); an IP
is only a fallback (D-391). An IP host is stored on the phone as a "수동 주소", breaks when
the site subnet changes, needs that IP in the certificate SAN, and makes `pair-link` print
a WARNING. `rosy-vision receive` puts `<hostname>.local` (or `--tls-host`) in the link and
prints the route-probe address only as an `IP fallback: <robot-ip>` diagnostic line.
`--tls-host` accepts only `<name>.local`; for a site FQDN or an IP pass `--advertise-host`.
When `--host` is a specific bind address, `receive` still links the name and says: "link host is <name>.local (D-391); use --advertise-host <ip> to pair by IP (fallback, needs an IP SAN)".
Treat the URI as a credential: do not paste it into tickets, logs, or shell
history. Use the QR/pairing screen over a trusted local channel.

## Enroll a robot from the console (D-361)

This is the default way to put a robot on the site roster. The operator powers
the robot on, presses **등록** on its row in **기기 연결 → 로봇 등록** (or uses
**주소로 추가** with a private `IPv4[:port]`, default port 8080, when multicast is
blocked), and types the 8-character code shown on the robot LCD. Fleet itself
calls the robot's `POST /api/v1/auth/pair`, reads `whoami` and `system/info` to
check the identity, seals the token in the Fleet database and adds the robot to
the roster. The browser never reaches the robot or sees the token. No SSH, no
`robots.yaml` edit and no restart. Enrollment writes need a named operator in
`site-users.yaml`; a single console token can read the panel only.

Scope: this works without SSH only for robots with an LCD whose card keeps
`login.boot_code` at its default (`operator`). Otherwise the code comes from an
administrator enrollment code on the robot dashboard or from SSH
`sudo rosy-login-code`. A new LCD code exists once per boot: the first
enrollment, each token expiry (7 days on the current image, which ignores the
site lifetime; 90 days after the S4 image) and each failure that consumed the
code need a power cycle or an administrator code. Where many people can see
the robot screens, set `login.boot_code: off` or a short `site_token_days`.

Create the `robot_credential_key` secret once, before the first start:

```bash
umask 077
python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())" \
  > "$ROSY_SITE_SECRETS_DIR/robot_credential_key"
chown root:10001 "$ROSY_SITE_SECRETS_DIR/robot_credential_key"
chmod 0640 "$ROSY_SITE_SECRETS_DIR/robot_credential_key"
```

It must be exactly one base64 line of 32 bytes and differ from every other
site secret (`robot-credential-key.template.txt` shows the format only). Back
the key up to a **different** place than the Fleet database backup: a database
copy alone yields no token, and the two together restore every enrollment.
Losing the key means re-enrolling every enrolled robot. A missing or wrong key
does not stop Fleet: enrollment answers 503, enrolled robots stay off the
roster for that run and `robots.yaml` robots keep working; fix the key and
restart, no codes needed. Rotate the key offline with the Fleet service
stopped, running the utility inside the Fleet image like backup and restore
(`compose` is the helper from "Backup and restore operations"). Write the new
key to a separate root-only file first; mount both keys read-only:

```sh
compose stop fleet
compose run --rm --no-deps --user 10001:10001 \
  -v "$ROSY_SITE_SECRETS_DIR/robot_credential_key:/keys/old.key:ro" \
  -v "$ROSY_SITE_SECRETS_DIR/robot_credential_key.new:/keys/new.key:ro" \
  --entrypoint python3 fleet /opt/rosy/site_db.py rekey \
  --path /var/lib/rosy/fleet.sqlite3 --old-key-file /keys/old.key \
  --new-key-file /keys/new.key --assume-stopped
```

Then replace `robot_credential_key` with the new file, back it up away from
the database backup, and start Fleet. `rekey` refuses a database path that does
not exist and a new key equal to the old one.

The robot address is pinned at enrollment; reserve each enrolled robot's
address in the router's DHCP table. When the same name appears at another
address, Fleet marks the robot **주소 바뀜 — 확인 필요**, sends only stop
requests to the pinned address, alarms if it was moving and holds overlapping
traffic. Either unenroll and enroll again with a new code, or, as a named
operator, **새 주소로 옮기기** after confirming the robot. **등록 해제** logs the
token out on the robot; if the robot is unreachable the row stays
**해제 대기** and Fleet tries the logout once when the robot reappears at its
pinned address.

The robot LAN carries codes and tokens in plain HTTP. Accept that only on an
operator-only SSID/VLAN recorded in the site validation record; a shared LAN,
routed networks, a central multi-site Fleet or more than 10 site robots need
the robot CORE TLS ADR first. If a site token is stolen, revoke it on the robot
dashboard (security panel, source "사이트"); until then it stays valid up to
its expiry. The manual `robots.yaml` procedure below remains for static and
simulated robots.

## Advertise and locate the Ubuntu Fleet PC

Choose a stable Ubuntu hostname before issuing the certificate. Install
`avahi-daemon` and `avahi-utils`, and check that TCP 8443 is reachable from
the intended robot/operator LAN. The site proxy's
`ROSY_SITE_BIND_ADDRESS` must name an approved LAN interface instead of
loopback when LAN clients need access. Set the same
`ROSY_SITE_HTTPS_PORT` in the private `/etc/rosy/site/.env` and the Compose
environment. Set `ROSY_SITE_TLS_HOST` to the same `<hostname>.local` name in
the site certificate SAN. Install `fleet-mdns.py` at `/opt/rosy/site/fleet-mdns.py`,
copy `rosy-fleet-advertise.service` and `rosy-overhead-advertise.service` to
`/etc/systemd/system/`, then run:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now avahi-daemon rosy-fleet-advertise.service rosy-overhead-advertise.service
avahi-browse -rtpk _rosy-fleet._tcp
avahi-browse -rtpk _rosy-overhead._tcp
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

The overhead record advertises only the public role, `rosy-overhead/1`, TLS
requirement, port, and certificate hostname. Android cameras discover multiple
`_rosy-overhead._tcp` receivers and let the operator choose one. Each camera
still needs its own configured source name and bearer token; discovery never
creates credentials or auto-pairs a camera. Install the separately issued site
CA in Android's trusted credentials so WSS certificate checks succeed. The
robot CORE `_rosy._tcp` record is a different API and is shown as a robot
discovery result, not as a camera-stream target.

See [D-341](../../docs/adr/D-341-overhead-console-approved-pairing.md)
(Proposed) for console-approved camera pairing: a named operator approves a
discovered camera's request by typing its 6-digit confirmation code, and the
installer confirms that the phone and console show the same site fingerprint
and credential ID. Only then is the per-camera token active and the site CA
pinned in the app. Discovery alone still grants nothing. Until D-341 is
implemented, and as the rollback path if pairing fails at a site, use a
`static` source with the manual `rosyov://...&tls=1` link, which still needs
the site CA installed in Android's user credentials.

## Prepare an Ubuntu host

Install Docker Engine and the Compose plugin from the approved Ubuntu package
source. Check `docker version` and `docker compose version`, then build the
two project images and pull the pinned Caddy image. Keep this deployment on a
host with a stable address and managed power; set host startup to run
the packaged `rosy-site-stack.service` after Docker and network-online are
ready. Do not install the site stack on the robot Pi or enable robot motion
through this stack. The unit starts the immutable loaded images with
`--no-build`; stopping it runs Compose `down` and preserves the named SQLite
volume. It does not authorize robot motion.

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
manager: one user API bearer per named person, the CORE registry credential,
phone-ingress, and vision-to-Fleet. Set every credential to a different value.
Store only each user's SHA-256 digest in `site-users.yaml`; deliver that user's
raw bearer separately. Write the service credentials to `registry_token`,
`phone_ingress_token`, and `fleet_sighting_token` files without trailing
newlines. Tokens are mounted as Compose secrets; the process bootstrap reads
them before dropping to UID/GID `10001`. Do not put secret values in YAML,
`.env`, command arguments, images, or logs.

The `registry_token` protects the separate CORE registry readback endpoint via
`ROSY_SITE_REGISTRY_TOKEN`. It is not a user API bearer and must differ from
every digest-backed `site-users.yaml` credential. The browser uses only the
individual token assigned to its user; Compose never reuses that token for the
CORE registry.

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
The builder output is unsigned. On the approved offline signing station, sign
the exact candidate manifest with the site-specific Ed25519 key. Do not sign
with the Pinky runtime release key, and never copy the private key into the
candidate or site host:

```sh
python3 deploy/site/sign_candidate.py \
  --candidate-dir "$candidate_dir" \
  --signing-key-id "$SITE_SIGNING_KEY_ID" \
  --private-key /secure/offline/site-release-ed25519.key \
  --public-key /secure/offline/site-release-ed25519.pub.pem
```

The signer first checks all manifest-listed deployment files, SBOMs, image
archive, and image records. It refuses to overwrite a signature and verifies
its output using the matching public key. `release.json.sig` is a detached
signature; the private key is never copied into the candidate.

Before transferring the candidate, bootstrap the Ubuntu host with the reviewed
`candidate_signing.py` and `verify_candidate.py` tools plus the site public key
through an independent trusted administrator path. Install these outside the
candidate, for example under `/usr/local/lib/rosy-site/` and
`/etc/rosy/site/trust/`, owned by root and not writable by the Fleet service.
Record the verifier source revision/hash, enrolled public-key fingerprint, and
key ID in host evidence. Do not run the verifier copied from the candidate to
authenticate that same candidate: an unsigned replacement could replace both.
The production site key ID and public key are not selected or present in this
repository yet; until they are independently provisioned, host activation is
HOLD.

Copy the signed candidate to the approved Ubuntu host using the site's
controlled transfer path. Verify its signature and files before Docker loads
the archive, then load and verify the exact images:

```sh
cd /opt/rosy/candidate
SITE_KEY_ID="$SITE_SIGNING_KEY_ID"
SITE_PUBLIC_KEY=/etc/rosy/site/trust/site-release-ed25519.pub.pem
python3 /usr/local/lib/rosy-site/verify_candidate.py \
  --candidate-dir /opt/rosy/candidate \
  --trusted-key-id "$SITE_KEY_ID" \
  --trusted-public-key "$SITE_PUBLIC_KEY" \
  --signature-only
docker image load --input images.tar
python3 /usr/local/lib/rosy-site/verify_candidate.py \
  --candidate-dir /opt/rosy/candidate \
  --trusted-key-id "$SITE_KEY_ID" \
  --trusted-public-key "$SITE_PUBLIC_KEY"
cp deploy/site/.env.example /etc/rosy/site/site.env
```

Set the image tag and private config paths in the operator-managed env file,
then run Compose with `--no-build` so the host uses the exact loaded candidate.
The first verifier invocation authenticates the exact manifest and checks the
packaged files, SBOMs, and image archive before load. The second also compares
the loaded Fleet, Vision, and proxy image IDs and platforms. Do not treat this
workstation-built candidate as field accepted until the target host's identity,
loaded image IDs, GPU, phone, CORE robot, and recovery checks are recorded.

Install the boot unit from that same verified candidate after its configuration
and secrets are ready:

```sh
sudo install -o root -g root -m 0644 \
  deploy/site/rosy-site-stack.service /etc/systemd/system/rosy-site-stack.service
sudo systemctl daemon-reload
sudo systemctl enable --now rosy-site-stack.service
sudo systemctl status rosy-site-stack.service --no-pager
docker compose --project-name rosy-site --env-file /etc/rosy/site/site.env \
  -f /opt/rosy/candidate/deploy/site/compose.yaml ps
```

On a planned stop or reboot, systemd stops the Compose project without deleting
its named volume. After reboot, verify the unit is active and all three
containers report healthy before accepting camera or operator traffic. For a
reboot acceptance, record that existing task/event/sighting rows remain
readable; a healthy container alone does not prove SQLite recovery. A failed
boot start is retried by systemd; inspect `journalctl -u rosy-site-stack` and
correct the Docker, env-file, or candidate-path cause before clearing the
failure.

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

Fleet stores sightings, authenticated CORE Agent event history, operator tasks,
task status history, and mutation audit in the same named SQLite volume with
WAL and full synchronous commit. Pairing a CORE Agent requires `--events-db`;
the Compose stack points it at `/var/lib/rosy/fleet.sqlite3`. Read the event
audit through the authenticated `GET /api/fleet/events` cursor API. The Fleet
image bundles a SQLite-aware online backup and guarded restore command at
`/opt/rosy/site_db.py`. Do not copy only the live main DB file while WAL is
active.

### Backup and restore operations

Keep backups on a protected host filesystem or approved encrypted backup
target. They contain operational history and task data. The utility creates
new backups without overwriting an existing file, runs `PRAGMA integrity_check`
before and after backup, publishes a standalone SQLite `DELETE`-journal file
without WAL sidecars, and reports a SHA-256 digest. The standalone file can be
verified from a read-only mount. The tool runs as the Fleet UID/GID
(`10001:10001`); prepare a private writable host directory and set the
installed candidate tag and paths in `/etc/rosy/site/site.env` first:

```sh
sudo install -d -o 10001 -g 10001 -m 0700 /var/backups/rosy-site
BACKUP_DIR=/var/backups/rosy-site
BACKUP_NAME="fleet-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
compose() { docker compose --project-name rosy-site --env-file /etc/rosy/site/site.env -f deploy/site/compose.yaml "$@"; }
compose run --rm --no-deps --user 10001:10001 \
  -v "$BACKUP_DIR:/backup" --entrypoint python3 fleet \
  /opt/rosy/site_db.py backup --destination "/backup/$BACKUP_NAME"
compose run --rm --no-deps --user 10001:10001 \
  -v "$BACKUP_DIR:/backup:ro" --entrypoint python3 fleet \
  /opt/rosy/site_db.py verify --path "/backup/$BACKUP_NAME"
```

Retain the command JSON output (including digest), backup filename, image
digest, and timestamp in the site's deployment record; transfer copies using
the approved encrypted path and verify them again after transfer. Define and
enforce a site retention period before production operation.

Before relying on recovery, test the backup against a separate Compose project
so it receives a different named `sighting_data` volume. The installed site
configuration and secret files must be available to Compose, but this one-off
command does not start the services or contact robots:

```sh
restore_test() { docker compose --project-name rosy-site-restore-test --env-file /etc/rosy/site/site.env -f deploy/site/compose.yaml "$@"; }
restore_test run --rm --no-deps --user 10001:10001 \
  -v "$BACKUP_DIR:/backup:ro" --entrypoint python3 fleet \
  /opt/rosy/site_db.py restore --source "/backup/$BACKUP_NAME" --assume-stopped
restore_test run --rm --no-deps --user 10001:10001 \
  --entrypoint python3 fleet /opt/rosy/site_db.py verify \
  --path /var/lib/rosy/fleet.sqlite3
```

Verify expected sightings, CORE events, tasks, status history, and audit rows
through the restored database or an isolated authenticated Fleet readback before
removing that test project. After recording the result, remove only the exact
test project and its test volume with
`docker compose --project-name rosy-site-restore-test --env-file /etc/rosy/site/site.env -f deploy/site/compose.yaml down --volumes`.
Never run that command with the production project name.

For a production restore, schedule a maintenance window and stop every writer
and reader first. Mount the chosen verified backup read-only, preserve the
printed pre-restore rollback path, and keep the same production Compose project
name so the command targets the existing data volume:

```sh
compose stop proxy vision fleet
compose run --rm --no-deps --user 10001:10001 \
  -v "$BACKUP_DIR:/backup:ro" --entrypoint python3 fleet \
  /opt/rosy/site_db.py restore --source "/backup/$BACKUP_NAME" \
  --destination /var/lib/rosy/fleet.sqlite3 --replace --assume-stopped
compose run --rm --no-deps --user 10001:10001 \
  --entrypoint python3 fleet /opt/rosy/site_db.py verify \
  --path /var/lib/rosy/fleet.sqlite3
compose up -d
```

`--assume-stopped` is an explicit operator assertion; the utility cannot prove
that no other process has the volume open. If restore fails, it attempts to
reinstate the pre-restore snapshot. Keep the site stopped and preserve both the
backup and reported rollback file until authenticated API readback confirms the
expected sightings, events, tasks, and audit history. Do not use `down --volumes`
on the production project.

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

## Automatic shadow delivery of new perception models (D-373)

`rosy-model-watch.timer` runs `tools/perception/model/watch.py` every 10
minutes. Automation stops at the shadow slot: selecting a learned model for
driving is not automated and stays behind the D-205 gate. Robots are reached
over SSH as `rosy` with `sudo -n` (D-373 decision 6).

### The store folder (default backend, no HF)

Datasets and models live in one **store folder** (D-373 decision 8). HF is
optional: the whole loop runs without an HF account. The config names it as
`store:` (default `/srv/rosy/store`, a local folder). To move it to a NAS or
Google Drive later, mount the share (SMB/NFS) or sync the folder with Google
Drive for desktop on the site PC, point `store:` at the mounted path and
re-run the install script; the layout and the code stay the same:

```text
<store>/datasets/<name>/<content_sha>/   publish.py writes; never overwritten
<store>/models/inbox/<folder>/           trainers drop hand-overs (handover.py)
<store>/models/accepted/<revision>/      intake passed
<store>/models/rejected/<folder>/        intake failed; REJECTED.txt says why
```

`content_sha` is the sha256 over the sorted `relpath\0sha256(file)` lines of
a folder (OS litter such as `desktop.ini` and the marker left out). An inbox
folder is taken only when its `READY` file holds that value, so a folder that
is still copying or half-synced from Drive or a NAS is ignored until it is
complete.

Each run lists the complete `models/inbox` folders oldest `READY` first,
runs intake on each unseen one (at most `max_new_per_run`), and moves it to
`models/accepted/<revision>/` on a pass or `models/rejected/<folder>/` on a
fail. On a pass the model is pushed to every configured robot's **shadow**
slot with `deliver.py push`. A missing store root (a mount that is not there)
is a listing failure, never an empty inbox. A folder name that was already
processed and reappears with other content is rejected as `reused`.

### Optional HF backend (`backend: hf`)

With `backend: hf` and `repo: <org>/<name>` the watcher lists the newest
`history_limit` commits of that HF model repository instead, and needs
`huggingface_hub` in the venv and, for a private repo, a read-only token.
The HF listing and the model download are then the only outbound calls.
First run: without a state file, every listed commit except the newest is
recorded as skipped (`bootstrap`), so an old history is not replayed. To
start from a known point instead, set `since: <commit sha>`: that commit and
all older ones are skipped, every later one is processed.

### What both backends share

The state file records every entry (inbox folder or commit), so each is
processed once:

- **Gate result.** An intake `pass` or `fail` is final.
- **Infrastructure errors** (disk, network, missing runtime, missing replay
  clips, timeouts) are not a verdict. The entry is retried on later runs up to
  `max_attempts` (default 5), then recorded as `gave_up`; an inbox folder stays
  in the inbox (fix the site, then delete its state entry to retry).
- **Robots.** A passed entry stays pending for each robot until its push
  succeeds. A robot that is off or unreachable does not block the others and
  is retried on later runs, without re-running intake, up to `max_attempts`.
  A robot added to the config later gets the newest passed model. The newest
  model wins: once a newer one is pending or delivered for a robot, an older
  pending one is marked `superseded` and never pushed.
- **Operators come first.** A manual `deliver` or `rollback` writes the
  robot's hold file `/var/lib/rosy/models/hold`; while it exists the watcher
  pushes nothing to that robot (no attempt used). It checks the file before a
  push and again inside the robot lock (`deliver.py push --unless-held`, exit
  76). `rosy_ml release-hold <robot>` removes the file; the next run reads the
  robot's real pointer and pushes the newest passed model if the robot is
  behind, even one it delivered before. A model already there is recorded
  without a push. Every pointer change runs under the robot's models lock
  (busy: exit 75, retried next run without using an attempt) and is recorded
  in `history.jsonl` (audit only; the watcher's entries say `site:<hostname>`).

### Install

The watcher needs a reviewed source checkout (it imports the manifest contract
and runner from `src/runtime/sensing`) and a Python venv with `onnxruntime`,
`onnx` (intake reads the graph's precision with it), `opencv-python-headless`,
`numpy` and `PyYAML` (add `huggingface_hub` only for `backend: hf`). A missing
package is a configuration error: the watcher exits 6 every run and records
nothing until the venv is fixed; `rosy_ml doctor --watch-config` names it. It is not part of the signed site candidate (follow-up: add
the units and a pinned watcher bundle to `build_candidate.py`). Prepare both,
then run the install script from that checkout:

```sh
sudo install -d -o root -g root -m 0755 /opt/rosy/model-watch
sudo git clone --no-checkout <reviewed-remote> /opt/rosy/model-watch/src
sudo git -C /opt/rosy/model-watch/src checkout --detach <reviewed-commit>
sudo python3 -m venv /opt/rosy/model-watch/venv
sudo /opt/rosy/model-watch/venv/bin/pip install onnxruntime onnx==1.23.1 opencv-python-headless numpy PyYAML
sudo /opt/rosy/model-watch/src/deploy/site/install-model-watch.sh --dry-run   # what it would do
sudo /opt/rosy/model-watch/src/deploy/site/install-model-watch.sh
```

`install-model-watch.sh` is idempotent and never overwrites a config, key,
`known_hosts` or token file. It creates the `rosy-model-watch` system user,
`/etc/rosy/model-watch/` with the site's own SSH key (`ssh-keygen`, owned by
the service user, 0600) and an empty pinned `known_hosts`,
`/etc/rosy/model-watch.yaml` from the example, the store folder and its
layout dirs when they are missing (a mount that exists keeps its owner), and
the drop-in `/etc/systemd/system/rosy-model-watch.service.d/store.conf` with
`ReadWritePaths=<store>` (the unit is `ProtectSystem=strict`; the store is its
only writable path besides its state directory); installs the unit and timer;
enables the timer only when the config has no `<...>` placeholders left; and
then runs `rosy_ml doctor --watch-config /etc/rosy/model-watch.yaml` as the
service user. It prints the remaining steps:

- **Site key.** The site host uses its own SSH key, not a person's;
  `ssh.identity` is required and has no default. Add the printed
  `site-ed25519.pub` line to `rosy`'s `authorized_keys` on each robot, so the
  site can be revoked without touching anyone else's access.
- **Host keys.** Record each robot's host key in
  `/etc/rosy/model-watch/known_hosts` from a trusted network
  (`StrictHostKeyChecking=yes`).
- **Config.** `sudoedit /etc/rosy/model-watch.yaml`: robots, `store`,
  `replay_root`. The config names robot addresses and so stays out of the
  checkout.
- **Store access.** People and tools that write the store (publish.py,
  trainers dropping into `models/inbox/`) need write access to it: members of
  the `rosy-model-watch` group on a local store, or the share's own
  permissions on a NAS or Drive folder.
- **Token (backend hf only).** For a private repo, paste a read-only HF token
  into `/etc/rosy/site/secrets/hf_token` (root:rosy-model-watch 0640) with
  `sudoedit`. The unit passes only its path (`HF_TOKEN_FILE`); the token never
  appears in a command line, the unit, the config, or the checkout. An empty
  or missing file means no token, which is what a public repo needs.
- **Replay clips.** Intake replays `data/teleop/learning/*.mp4` under
  `replay_root`. Without clips intake stops with a setup error (retried, not
  recorded as a model failure); doctor checks the count.

Re-run the script after these steps; then check a run by hand:

```sh
sudo systemctl start rosy-model-watch.service
journalctl -u rosy-model-watch.service -n 50
```

`TimeoutStartSec=6h` bounds one run. Worst case is roughly
`max_new_per_run` intakes (a few minutes each on the site CPU) plus, per robot,
one pointer read (60 s) and three push steps of `push_timeout_s` (600 s):
6 h covers about 10 robots at the defaults. Raise it for a larger site or
lower `push_timeout_s`.

Exit codes in the journal: `0` finished with nothing waiting on a retry (a
failed intake or a held robot is a recorded outcome), `1` an intake
infrastructure error, a store move or a robot push failed and will be retried,
`2` config or state file error, `5` the listing failed (store missing or
unreadable, or the HF listing failed) and nothing was recorded. The state
lives in `/var/lib/rosy-model-watch/state.json`; deleting an entry makes the
next run process it again.

## Current acceptance boundary

The stack is local-testable, but installing and running it on an Ubuntu control
PC requires a real site hostname, trusted certificate/CA, operator and camera
credentials, surveyed camera geometry, CORE endpoint credentials, host access,
and an approved network/firewall rule. Successful container health checks do
not prove phone pairing, site calibration, CORE connectivity, robot behavior,
or field acceptance. D-257/D-268 remain at their recorded status; autonomous
movement and pick are disabled pending those gates.

## Map auto-fit overlay (D-375)

Both images bake the `map_v2_fleet` track files at `/opt/rosy/maps/map_v2_fleet/`
(read-only). Vision runs with `--map-paint .../road_lines.stl` and serves
`GET /api/vision/sources/{id}/map-proposal` on the preview lease. Fleet runs with
`--site-lane-graph .../lane_graph.yaml --site-lane-paint .../road_lines.stl` and
serves `GET /api/fleet/site-lanes` (lane polylines and paint triangles, no video).
In `/console`, the operator presses **맵 자동 맞춤** in the ceiling-camera panel:
the lanes are drawn on the raw frame and the frame is shown warped into map
metres. **맞춤 수락** only stores a browser-local display draft per camera; it is
never used for sightings, `CameraMap`, or driving.

For another track, put its files under `ROSY_SITE_CONFIG_DIR` and point the flags
at `/run/rosy-config/...` (a `MAP_ID=` prefix limits a Fleet lane file to one
`map_id`). Removing the flags turns the feature off (404 on both routes).

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
