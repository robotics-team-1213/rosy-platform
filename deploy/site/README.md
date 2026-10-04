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
site FQDN and LAN interface, issue a certificate with that FQDN, open the
proxy to the LAN as described in [LAN access](#lan-access) (wildcard bind plus
the interface firewall, never a literal LAN IP), and provision separate
named user credentials. Keep Fleet 8090 and Vision 8095 unpublished. From the
operator PC, verify the trusted `https://<site-fqdn>:8443/healthz`, open
`/console`, confirm a viewer cannot submit work, and confirm an operator's
request appears in task history with its real status. An HTTP acceptance is
not proof of robot completion. Record the site host, client PC, image digest,
certificate identity, config revision, and readback in the site validation
record. These steps require the actual site host and devices for SITE/FIELD
acceptance; local Compose checks establish only LOCAL behavior.

## LAN access

On 2026-10-01 a site moved from 192.168.1.0/24 to 10.16.36.0/24. The proxy was
published on the old interface IP, so the next start failed with "cannot
assign requested address" and the console, cameras, robots and the discovery
bridge went down together. The site stack therefore never names a LAN
address:

| Setting (private `site.env`) | Local / SSH tunnel | LAN |
|---|---|---|
| `ROSY_SITE_BIND_ADDRESS` | `127.0.0.1` (default) | `0.0.0.0` |
| `ROSY_SITE_LAN_IFACE` | empty | the LAN interface name, e.g. `wlan0` or `eth0`; a bridged LAN needs the bridge name (`br0`); comma-separated for several |

- **Bind the IPv4 wildcard.** `0.0.0.0` exists on every IPv4 host, so a new
  DHCP lease or a renumbered site LAN needs no edit and no restart, and
  loopback stays reachable for the discovery bridge. `::` and an empty bind
  (which publishes on IPv6 too) are refused: the filter below and robot
  discovery are IPv4 only. A literal LAN IP is refused unless
  `ROSY_SITE_ALLOW_LITERAL_BIND=1`; it dies with the address and the
  discovery bridge cannot reach it on loopback.
- **Scope it by interface, ahead of Docker.** Docker-published ports are
  DNAT-forwarded and skip the INPUT chain and ufw, so a ufw rule does not
  limit them. `site-firewall.py apply` (run by `rosy-site-firewall.service`)
  filters in the `mangle` table's `PREROUTING` chain, before Docker's DNAT,
  where the published port is still the destination port. One jump
  `-p tcp --dport <port> -j ROSY-SITE-INGRESS` leads to its own chain, which
  returns traffic arriving on `lo` and on each `ROSY_SITE_LAN_IFACE`, then
  drops everything else addressed to this host
  (`-m addrtype --dst-type LOCAL -j DROP`). After that only traffic on Docker
  bridges (`-i br+`, `-i docker0`, container to container) returns, and an
  unconditional `-j DROP` ends the chain, so a packet routed straight to a
  container IP from any other interface is dropped too. When the published
  port differs from the proxy's container port 8443, a second jump
  `-p tcp --dport 8443 -m addrtype ! --dst-type LOCAL` sends such routed
  packets to the chain; it skips local destinations, so a host service on
  8443 is untouched. It matches interface names only, never an IP or subnet.
  The chain is written in one `iptables-restore -w --noflush` transaction
  (declaring the chain flushes and refills it atomically), and the jumps are
  inserted once and kept; re-running changes nothing. A named interface that
  does not exist yet is admitted by name with a warning.
- **Docker Engine 28 or later.** Older engines accept packets routed
  directly to a container address from any interface; the chain's final drop
  covers that, and Docker Engine 28 closes it on its own side as well. Use
  Docker Engine 28 or later. `check` warns when `docker version` reports an
  older engine (it cannot tell before dockerd is up, so `apply` does not
  enforce it).
- **Boot order and failure.** The unit runs `After=network-pre.target` and
  `Before=docker.service rosy-site-stack.service`, so the filter is in place
  before dockerd can restore a proxy container. Docker does not touch the
  `mangle` chain. If `apply` fails, `OnFailure=` starts
  `rosy-site-firewall-failclosed.service`, which stops the proxy container
  found by its Compose labels (project `rosy-site`, service `proxy`) without
  parsing any config, so a broken `site.env` cannot keep it running.
  `rosy-site-firewall-check.timer` runs `check` every
  5 minutes; a missing or bypassed filter logs the reason at error level in
  `journalctl -u rosy-site-firewall-check` and closes the port the same way.
  After a clean shutdown no container is left to restore, because the stack
  unit's stop runs Compose `down`.
- **One env parser.** The helper takes the bind address, port, interfaces
  and `tls_host` from `docker compose config` (the `x-rosy-site` block in
  `compose.yaml`), so `site.env` means the same to it as to Compose. Lines
  that are not plain `KEY=VALUE` (for example `export KEY=...`) exit 2,
  because systemd would read them differently. `apply` also writes
  `/run/rosy-site/site-public.env` with only `ROSY_SITE_TLS_HOST` and
  `ROSY_SITE_HTTPS_PORT` for the bridge and the advertise units.
- **Preflight.** `rosy-site-stack.service` runs
  `site-firewall.py check --verify-certs` before Compose. It refuses to
  start, with the reason in `journalctl -u rosy-site-stack`, when the bind is
  a literal IP this host no longer owns, a non-loopback bind has no
  `ROSY_SITE_LAN_IFACE`, the filter is missing, or the site certificate fails
  strict verification for `tls_host` ([Site certificate
  profile](#site-certificate-profile)).
- **Certificate.** Clients verify the certificate against `tls_host` (and
  the FQDN), not an IP, so the site certificate needs no IP SAN. Add an IP SAN
  only for the manual IP pairing link below.

```sh
for unit in rosy-site-firewall.service rosy-site-firewall-failclosed.service \
    rosy-site-firewall-check.service rosy-site-firewall-check.timer; do
  sudo install -o root -g root -m 0644 /opt/rosy/candidate/deploy/site/$unit /etc/systemd/system/
done
sudo python3 /opt/rosy/candidate/deploy/site/site-firewall.py apply --dry-run  # prints; changes nothing
sudo systemctl daemon-reload
sudo systemctl enable --now rosy-site-firewall.service rosy-site-firewall-check.timer
sudo iptables -t mangle -S PREROUTING; sudo iptables -t mangle -S ROSY-SITE-INGRESS
```

Check from a LAN client that `https://<tls_host>:8443/healthz` answers, and
from a client on another interface (if the host has one) that it does not.
When the LAN interface name changes (for example from Wi-Fi to Ethernet), set
`ROSY_SITE_LAN_IFACE` and `systemctl restart rosy-site-firewall.service`.

### Upgrading from a literal-IP bind

1. In `/etc/rosy/site/site.env` set `ROSY_SITE_BIND_ADDRESS=0.0.0.0` and
   `ROSY_SITE_LAN_IFACE=<interface>`, and make sure `ROSY_SITE_TLS_HOST` and
   `ROSY_SITE_HTTPS_PORT` are set there. Keep every line plain `KEY=VALUE`.
2. Install and enable `rosy-site-firewall.service`,
   `rosy-site-firewall-failclosed.service`, `rosy-site-firewall-check.service`
   and `rosy-site-firewall-check.timer` (commands above).
3. Run `sudo python3 /opt/rosy/candidate/deploy/site/site-firewall.py check --verify-certs`
   and fix what it reports, before the stack is restarted.
4. Copy the new `mdns-bridge.py` to `/opt/rosy/site/mdns-bridge.py` and the new
   `rosy-mdns-bridge.service`, `rosy-fleet-advertise.service` and
   `rosy-overhead-advertise.service` to `/etc/systemd/system/`. Remove
   `/etc/rosy/site/mdns-bridge.env` (`ROSY_SITE_DISCOVERY_URL` is retired).
5. `sudo systemctl daemon-reload`, then
   `sudo systemctl restart rosy-site-firewall.service rosy-site-stack.service`
   and `sudo systemctl restart rosy-fleet-advertise.service rosy-overhead-advertise.service`.
6. Confirm the console discovery panel shows devices, not **검색기 끊김**.

### Recovering after the port was closed

The fail-closed unit stops only the proxy container. `rosy-site-stack.service`
stays `active (exited)`, so nothing restarts the proxy by itself. Read the
reason in `journalctl -u rosy-site-firewall -u rosy-site-firewall-check`, fix
it, run `sudo python3 /opt/rosy/candidate/deploy/site/site-firewall.py check`
until it passes (after `systemctl restart rosy-site-firewall.service` if the
filter itself was missing), then `sudo systemctl restart rosy-site-stack`.
Editing `ROSY_SITE_LAN_IFACE` (or the port) without restarting
`rosy-site-firewall.service` makes the next 5-minute check fail and closes
the port the same way; always restart the firewall unit after such an edit.

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
`discovery_token`; `site-ca.crt` is already public to the host service.

The bridge needs no URL, FQDN or LAN address. Its unit reads
`ROSY_SITE_TLS_HOST` and `ROSY_SITE_HTTPS_PORT` (default 8443, as in Compose)
from `/run/rosy-site/site-public.env`, which `site-firewall.py apply` writes
from `docker compose config`. It connects to the proxy on this host's
loopback (`127.0.0.1`, then `::1`) at that port and sets the TLS server name,
the certificate name check and the HTTP `Host` to `ROSY_SITE_TLS_HOST`,
verified strictly (`VERIFY_X509_STRICT`) against `site-ca.crt`. The unit
allows only loopback IP traffic (`IPAddressAllow=localhost`), and the token
file must hold one printable ASCII token.
Loopback rather than `https://<tls_host>` resolved on the host: resolving the
name goes through DNS or nss-mdns, which follows the LAN (a stale record, a
changed subnet or a down Wi-Fi interface makes it fail), while loopback exists
whatever the LAN does, and both the default `127.0.0.1` and the LAN
`0.0.0.0` bind include it. The certificate still has to carry `tls_host`, so
a wrong proxy fails TLS rather than receiving the scan. A literal LAN IP bind
does not listen on loopback, so the bridge cannot work with it. Remove the
retired `/etc/rosy/site/mdns-bridge.env` (`ROSY_SITE_DISCOVERY_URL`) when
upgrading.

Check `avahi-browse -rtpk _rosy._tcp` on the host, then start the timer with
`systemctl enable --now rosy-mdns-bridge.timer`. Check
`systemctl status rosy-mdns-bridge.service` and the Fleet discovery panel.
When Avahi or TLS fails, the bridge must not replace the last good scan with
an empty result; Fleet marks the scanner offline after its lease expires, and
the console discovery panel then shows **검색기 끊김** in red with the age of
the last scan and logs the loss once, because new-robot discovery and
**새 주소로 옮기기** stop until the bridge delivers again.
AP advertisements are excluded. On a VLAN or Wi-Fi with multicast/client
isolation, use the existing manual endpoint and outbound FleetAgent path.

#### User discovery fallback without administrator access

When the site account already has `Linger=yes`, a running user systemd manager,
and access to the existing Avahi daemon, discovery can start at boot through
user units. This opt-in fallback does not install Avahi, change the firewall,
enable linger, or replace the system units above. Stop existing temporary user
advertisers before installing; active system discovery services and readable
system Avahi ROSY XML advertisements cause a refusal. The known broken
root-owned `0600` XML files are left untouched and do not block this explicit
fallback; Avahi cannot read them. Failed root services and an enabled timer
without a working scanner also do not prevent the fallback.

Copy `install-user-discovery.py`, `mdns-bridge.py`, and `fleet-mdns.py` to one
directory readable by the site account. Select the same discovery secret that
Fleet actually uses and its public site CA, then run as that account:

```bash
python3 install-user-discovery.py --enable-user-fallback \
  --tls-host <certificate-hostname.local> --port 8443 \
  --ca-file <site-ca.crt> --token-file <selected-discovery-secret>
systemctl --user status rosy-user-mdns-bridge.service
systemctl --user list-timers rosy-user-mdns-bridge.timer
```

The installer stores one token as `0600` and the public CA as `0644` under the
user-owned `0700` directory `~/.local/share/rosy/site-discovery`. Advertisers
`rosy-user-fleet-advertise.service` and `rosy-user-overhead-advertise.service`
use the existing common TXT contracts and certificate hostname. The bridge
timer runs every 15 seconds with `AccuracySec=1s` to stay within Fleet's 45-second
scanner lease, and reuses the same strict TLS verification and
loopback connection code. Secrets never appear in unit files or arguments.
User units have the account's ordinary permissions; they do not inherit the
root bridge's OS-level IP firewall restrictions. Loopback is enforced by the
unchanged bridge implementation. Verify a fresh Fleet discovery scan and both
DNS-SD records after reboot. Before returning to system discovery, disable the
three user units with `systemctl --user disable --now` and their names above.

For a 4–10 robot site, boot all cards on the same LAN and confirm one distinct
row per device, no duplicate-name conflict, all configured devices eventually
show **confirmed**, and newly initialized cards remain **registration pending**.
Reboot one robot, change its DHCP address, disconnect the site host, then
repeat the scan. A registered `.local` endpoint follows the changed address;
an IP-pinned `robots.yaml` entry needs an operator update and is never
silently rewritten from untrusted mDNS. The LAN test does not replace pairing, CORE health, or
physical motion acceptance.

Fleet 이미지에는 `libnss-mdns`가 포함된다. 컨테이너는 호스트의 실행 중인
Avahi `/run/avahi-daemon` 디렉터리를 읽기 전용으로 연결하고 NSS로 `.local`
주소를 조회한다. 디렉터리 연결은 Avahi 재시작으로 교체된 소켓도 따른다.
호스트 Avahi와 소켓 접근 권한이 필요하며, 경로가 없으면 Compose가 시작을
거부한다. 일반 Docker 서비스 이름은 계속 DNS로 조회한다. 이미지와 Compose를
함께 갱신한 뒤 Fleet 실행 UID로 `socket.getaddrinfo` 또는 `getent hosts`를
사용해 로봇 `.local` 이름과 `fleet`/`vision`/`proxy`를 확인한다. `nslookup`은
NSS를 거치지 않는다. TLS CA와 원래 hostname 검증은 그대로 유지한다.

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

### Site certificate profile

The bridge, `site-firewall.py check --verify-certs` and Python 3.13+ clients
verify with OpenSSL's X.509 strict mode, which rejects a CA or leaf without
these extensions:

| Certificate | Extensions |
|---|---|
| Site CA | `basicConstraints = critical, CA:TRUE, pathlen:0`; `keyUsage = critical, keyCertSign, cRLSign`; `subjectKeyIdentifier = hash`; `authorityKeyIdentifier = keyid:always` |
| Site leaf | `basicConstraints = critical, CA:FALSE`; `keyUsage = critical, digitalSignature`; `extendedKeyUsage = serverAuth`; `subjectAltName = DNS:<tls_host>` plus the DNS names above; `subjectKeyIdentifier = hash`; `authorityKeyIdentifier = keyid` |

Gate every issued pair before installing it:

```sh
openssl verify -x509_strict -purpose sslserver -verify_hostname <tls_host> \
  -CAfile site-ca.crt site.crt
```

The stack preflight runs the same check (a strict TLS handshake for
`tls_host`) and refuses to start on failure. Reissuing the **CA** is a
rotation, not a fix-up: every Rosy Cam pins the SHA-256 of the CA (DER), so
each camera must be paired again, and browsers and robots need the new CA.
Reissuing only the leaf under the same CA keeps every pin.
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
the intended robot/operator LAN. When LAN clients need access, set
`ROSY_SITE_BIND_ADDRESS=0.0.0.0` and `ROSY_SITE_LAN_IFACE` to the approved
LAN interface ([LAN access](#lan-access)). Set `ROSY_SITE_HTTPS_PORT` once,
in the private `/etc/rosy/site/site.env`; Compose reads it there and the
advertise units get it through `/run/rosy-site/site-public.env`. Set `ROSY_SITE_TLS_HOST` to the same `<hostname>.local` name in
the site certificate SAN. Install `fleet-mdns.py` at `/opt/rosy/site/fleet-mdns.py`,
copy `rosy-fleet-advertise.service` and `rosy-overhead-advertise.service` to
`/etc/systemd/system/`.

The publisher atomically installs public advertisement XML with mode `0644`
so the unprivileged Avahi daemon can read it, even with a `0077` umask.
After upgrading an older publisher, restart the advertise services to
replace any existing `0600` advertisements with readable files.

Then run:

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
(Accepted as design) for console-approved camera pairing: a named operator approves a
discovered camera's request by typing its 6-digit confirmation code, and the
installer confirms that the phone and console show the same site fingerprint
and credential ID. Only then is the per-camera token active and the site CA
pinned in the app. Discovery alone still grants nothing. As the rollback path when pairing is off or fails at a site, use a
`static` source with the manual `rosyov://...&tls=1` link, which still needs
the site CA installed in Android's user credentials.

### Preflight (D-391 3)

Run the consistency check on the Ubuntu host before `docker compose up`; it
exits non-zero and prints a reason and fix hint per failed check:

```sh
python3 /opt/rosy/site/site_preflight.py --site-cert <secrets>/site.crt
python3 /opt/rosy/site/site_preflight.py --site-cert <secrets>/site.crt --json
```

It reads `ROSY_SITE_TLS_HOST` (flag `--tls-host`, else the shell, else
`/etc/rosy/site/site.env`) and checks: `site_cert` is a leaf (not a CA) followed by
a CA; the leaf has a DNS SAN equal to `tls_host` (exact, case-insensitive, a
wildcard does not count); `tls_host` is a `<name>.local` name; the
`--tls-host` that the advertise units publish equals it; and the Caddyfile
site address names no other host (a port-only `:8443` address passes). Only the
first Caddyfile site block's addresses are read. IP SANs are not checked: they
go stale on renumber, and an IP SAN is needed only for a `manual_host`
fallback link, which this preflight does not cover.

### Camera pairing (D-341)

Off by default: with nothing below set, the stack, the DNS-SD record and the phone behave as before
(`credential: static` and the manual `rosyov://` link). Pairing is one switch, `ROSY_SITE_PAIRING=1`,
plus its overlay key, both in the one `/etc/rosy/site/site.env`; `site_preflight.py` checks that the
switch, the overlay, the advertisement and the sync token agree.

1. **Sync token.** Vision reads the credentials Fleet issued over `https://fleet:8090`, authenticated
   by its own token (D-341 12). Make it a new random value, distinct from every other secret in
   `secrets/` (`discovery-token.template.txt` shows the shape; this one is
   `pairing-sync-token.template.txt`):
   `umask 077; openssl rand -hex 32 > "$ROSY_SITE_SECRETS_DIR/pairing_sync_token"`.
   Only Fleet and Vision mount it. The preflight refuses a missing, empty or duplicated token.
2. **Cameras.** In `site-cameras.yaml` give each pairable source `credential: paired` and drop its
   `phone_token_env`. A `credential: static` source keeps its fixed token and manual link; both kinds
   can live in one file (see `site-cameras.yaml.example`).
3. **Fleet and Vision.** In `/etc/rosy/site/site.env` set
   `ROSY_SITE_PAIRING=1` and
   `ROSY_SITE_PAIRING_COMPOSE=-f /opt/rosy/candidate/deploy/site/compose.pairing.yaml`.
   `rosy-site-stack.service` appends that word list after `-f compose.yaml` (an empty value adds
   nothing). The overlay gives Fleet `--pairing-ca /run/secrets/site_ca` (the CA, never the leaf),
   `--pairing-tls-host ${ROSY_SITE_TLS_HOST}` and the sync token, and gives Vision
   `--pairing-sync-url https://fleet:8090`, `--pairing-sync-ca /run/secrets/site_ca` and the same
   token. Vision refuses a plain `http` URL or a missing CA.
4. **Advertisement.** Nothing more to set: `ROSY_SITE_PAIRING` is set once in
   `/etc/rosy/site/site.env`; `site-firewall.py apply` copies it into
   `/run/rosy-site/site-public.env` for the advertise unit (restart `rosy-site-firewall` after a
   change). `rosy-overhead-advertise.service` runs `fleet-mdns.py publish --role overhead --pair=${ROSY_SITE_PAIRING}`,
   which adds TXT `pair=rosy-pair/1` to `_rosy-overhead._tcp` (D-341 14). Never advertise it without
   step 3: the pairing routes answer 404 when Fleet runs without `--pairing-ca`, and the phone would
   offer a request that cannot succeed. Apps that predate the key ignore it.

Run `python3 deploy/site/site_preflight.py` (it reads `/etc/rosy/site/site.env`), then
`sudo systemctl restart rosy-site-firewall rosy-site-stack rosy-overhead-advertise`. The
`pairing_consistent` check fails when `ROSY_SITE_PAIRING` is not `1`, `0` or empty,
when the overlay is named without the switch (or the switch without the overlay), when the unit
advertises `pair` while pairing is off (or omits it while on), and when `pairing_sync_token` is
missing or equals another secret.

**What the phone sees.** The app offers **사이트에 연결 요청** only for a site whose record carries
`pair=rosy-pair/1`; otherwise it shows the manual/deep-link path. Nothing is granted by discovery. The
phone and the console compare a 6-digit code and the site fingerprint before the credential turns
active.

**Operator flow.** In the Fleet console open **기기 연결**, then **카메라 연결 승인** (D-391 4):
pick the request, choose a free paired source, and type the 6-digit code the phone shows (the console
never shows the code). The console then shows the site fingerprint and credential ID; the installer
checks the phone shows the same two values and taps 일치 within 120 s, and only then is the credential
active. To revoke a camera, use 폐기… on its row in the same panel; Vision drops it at its next credential sync. To turn pairing
off, clear `ROSY_SITE_PAIRING` and `ROSY_SITE_PAIRING_COMPOSE` in `site.env` and restart the same
three units; sources
fall back to `credential: static` with the manual link.

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
otherwise bind `0.0.0.0` and limit the port to the LAN interface with
`rosy-site-firewall.service` ([LAN access](#lan-access)). Do not expose Fleet's
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
the loaded Fleet, Vision, and proxy image IDs and platforms. A host on the
classic Docker image store reports the config digest recorded in
`release.json`; a host on the containerd image store reports the OCI image
manifest digest. The verifier accepts the second form only when that manifest
blob, read from the hash-checked `images.tar`, hashes to the reported digest
and names the signed config digest. The PASS line records `id_form` per
service (`config` or `oci-manifest`). Do not treat this
workstation-built candidate as field accepted until the target host's identity,
loaded image IDs, GPU, phone, CORE robot, and recovery checks are recorded.

### CI-built candidates (D-437)

The normal path builds the candidate on a GitHub-hosted runner instead of a
local PC. The runner output is unsigned, and no signing key is ever stored in
GitHub. Placeholders below (`<owner>/<repository>`, `<commit>`, key paths) are
filled from the operator's private records.

1. A push to `main` that touches an image source, the candidate's discovery
   document, or the workflow builds automatically (D-441). To build another
   commit, dispatch it. A short first job checks whether the release for that
   commit already exists: a dispatch then fails at once, a push succeeds
   without building. The build then runs `build_candidate.py --sbom-tool syft` on
   `ubuntu-24.04` and creates the prerelease `site-<first 12 hex of commit>`
   with `release.json`, `SHA256SUMS`, and the split tar
   (`rosy-site-candidate-<commit>.tar.partNN`, each under 2 GiB):

   ```sh
   gh workflow run build-site-candidate.yml --repo <owner>/<repository> -f ref=<commit>
   ```

2. On the offline signing station, download only `release.json`. Release
   assets can be replaced by anyone with write access, so bind the file to the
   CI run before signing. Both checks are required:
   - Open the workflow run page and copy the `release.json SHA-256` from the
     job summary table. Do not take it from arbitrary log lines: build tool
     output runs with workflow commands paused, and the table is written only
     after they resume. Alternatively use the subject digest that
     `gh attestation verify ... --format json` reports for `release.json`. The
     run summary and attestations cannot be edited by release-asset writers.
   - Verify the GitHub build provenance of the downloaded file. It must come
     from this workflow, built from `main`:

   ```sh
   gh release download site-<sha12> --repo <owner>/<repository> \
     --pattern release.json --dir <station-dir>
   gh attestation verify <station-dir>/release.json --repo <owner>/<repository> \
     --signer-workflow <owner>/<repository>/.github/workflows/build-site-candidate.yml \
     --source-ref refs/heads/main
   python3 deploy/site/sign_candidate.py --manifest-only \
     --manifest <station-dir>/release.json \
     --expected-commit <commit> \
     --expected-manifest-sha256 <sha256-from-run-summary> \
     --signing-key-id "$SITE_SIGNING_KEY_ID" \
     --private-key /secure/offline/site-release-ed25519.key \
     --public-key /secure/offline/site-release-ed25519.pub.pem
   gh release upload site-<sha12> --repo <owner>/<repository> \
     <station-dir>/release.json.sig
   ```

   `--manifest-only` does not look at the candidate files. It refuses a
   manifest whose SHA-256 differs from `--expected-manifest-sha256`, and a
   `source_commit` that is not 40 hex characters or differs from
   `--expected-commit`. The signature says "this manifest from that CI run and
   commit is approved"; the host verifier below still checks every file hash.
   A candidate dispatched from another branch fails `--source-ref
   refs/heads/main`; sign only main builds.

3. On the site host, as the operator (no sudo), fetch and stage it. The script
   checks `SHA256SUMS`, joins the parts, extracts into a fresh staging folder,
   adds `release.json.sig`, and refuses a release that has no signature yet.
   Before extracting it rejects any archive member that is not a regular file
   or directory (symlink, hardlink, device, fifo) or lies outside
   `<commit>/`, then extracts with Python's tarfile `data` filter (needs
   python3 3.12 or newer):

   ```sh
   /usr/local/lib/rosy-site/fetch_candidate.sh \
     --repo <owner>/<repository> --commit <commit>
   ```

   Install `fetch_candidate.sh` once next to the reviewed verifier, by the same
   administrator path. It is not part of the candidate, so adding it did not
   change the file list that installed verifiers accept.

   It prints the administrator commands that follow: copy the staged folder to
   `/opt/rosy/candidate`, run the independently installed verifier with
   `--signature-only`, `docker image load`, run the full verifier, set
   `ROSY_SITE_IMAGE_TAG`, and restart `rosy-site-stack.service`. These are the
   same D-301 checks as above; `SHA256SUMS` alone authenticates nothing.

The release job keeps only the newest three `site-*` releases: after creating
the new prerelease it deletes older ones and their tags (exact
`^site-[0-9a-f]{12}$` names only). Robots look for `payload-*` releases in the
first page of 20 recent releases, prereleases included (D-412), so site
candidates must not push the newest payload release off that page. Stage a
candidate on the host before three newer ones are built, or rebuild it.

Install the boot unit from that same verified candidate after its configuration
and secrets are ready. For LAN access install `rosy-site-firewall.service`
first ([LAN access](#lan-access)); the stack unit's `ExecStartPre` preflight
refuses to start a LAN bind without it:

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

### Automatic updates (D-441)

Since D-441 the chain runs by itself: a push to `main` builds the candidate,
the operator's signing PC signs it, and the site host installs it with a health
check and rollback. Code merged to `main` becomes the site deployment within
roughly half an hour. The trust anchors do not move: the private key stays on
the signing PC, and the host verifies with the verifier and public key it got
by hand (D-301). Placeholders below are filled from private records.

**Signing PC (Windows or Linux).** `auto_sign_candidates.py` runs every 10
minutes. It needs Python 3.10+, OpenSSL, and `gh` logged in with a token that
can upload release assets to this repository only (a fine-grained token with
Contents read/write on that repository). Keep the config outside the
repository, for example `C:\RosySigning\auto-sign.json`:

```json
{
  "repo": "<owner>/<repository>",
  "key_id": "<site-signing-key-id>",
  "private_key": "C:\\RosySigning\\site-release-ed25519.key",
  "public_key": "C:\\RosySigning\\site-release-ed25519.pub.pem",
  "state_dir": "C:\\RosySigning\\state",
  "keep": 10,
  "max_per_run": 3
}
```

```powershell
python deploy\site\auto_sign_candidates.py --config C:\RosySigning\auto-sign.json --dry-run
powershell -ExecutionPolicy Bypass -File deploy\site\register_auto_sign_task.ps1 `
  -ConfigPath C:\RosySigning\auto-sign.json
```

For each unsigned `site-<12 hex>` release (newest first, at most
`max_per_run`) it downloads only `release.json` and signs only when all of
these hold. Otherwise it records a refusal and does not check the same bytes
again:

- `gh attestation verify` passes for this repository's
  `build-site-candidate.yml` with `--source-ref refs/heads/main`, and the
  attested `release.json` subject digest equals the SHA-256 of the downloaded
  bytes. That digest becomes `--expected-manifest-sha256`.
- The manifest `source_commit` is on `main` (GitHub compare status `ahead` or
  `identical`) and the tag is `site-<source_commit[:12]>`.
- `sign_candidate.sign_manifest_only` accepts it (commit, image tag, platform,
  digest), and no `release.json.sig` exists yet. It never uses `--clobber`.

Every decision is one JSON line in `<state_dir>/audit.jsonl`. Exit codes: 0
nothing to do, 10 signed, 20 refused or failed, 2 configuration or lock. The
task runs only while that user is logged on. Pause with
`Disable-ScheduledTask -TaskName RosySiteAutoSign`; remove with
`Unregister-ScheduledTask -TaskName RosySiteAutoSign -Confirm:$false`. On
Linux run the same command from a systemd user timer or cron.

**Site host (once, as the administrator).** Install the first candidate by
hand as above; the updater only replaces a running one. Install the updater
beside the reviewed verifier from a reviewed checkout, never from a candidate:

```sh
sudo install -o root -g root -m 0755 deploy/site/rosy_site_autoupdate.py \
  /usr/local/lib/rosy-site/rosy_site_autoupdate.py
sudo install -o root -g root -m 0644 deploy/site/verify_candidate.py \
  deploy/site/candidate_signing.py deploy/site/site_update_io.py /usr/local/lib/rosy-site/
sudo install -o root -g root -m 0644 deploy/site/rosy-site-autoupdate.service \
  deploy/site/rosy-site-autoupdate.timer /etc/systemd/system/
sudoedit /etc/rosy/site/autoupdate.conf   # JSON below, mode 0644, owner root
sudo systemctl daemon-reload
sudo /usr/bin/python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py run --dry-run
sudo systemctl enable --now rosy-site-autoupdate.timer
```

```json
{
  "repo": "<owner>/<repository>",
  "key_id": "<site-signing-key-id>",
  "public_key": "/etc/rosy/site/trust/site-release-ed25519.pub.pem",
  "health_url": "https://<site-fqdn>:8443/healthz",
  "health_ca": "/etc/rosy/site/secrets/<site-ca-file>",
  "health_timeout_s": 300,
  "keep": 3
}
```

Each run (every 15 minutes, randomized by up to 5) picks the newest signed
`site-*` release whose commit is a strict descendant of the running commit.
Release creation time only orders eligible candidates; rebuilding an old
commit cannot authorize a downgrade. The running signed manifest must match
`site.env`. Running container tags and immutable image identities must also
match the signed archive before release selection. A network error, including
an incomplete HTTP body, postpones the attempt without blacklisting it.
Each eligible candidate:

1. refuses without changing anything when `ROSY_SITE_PAIRING_COMPOSE` names a
   file other than the candidate's `compose.pairing.yaml`, when `site.env`
   sets `COMPOSE_FILE`, when the stack unit (drop-ins included, read through
   `systemctl cat`) adds a Compose file, or when `docker compose config` with
   the new tag does not resolve every site service to
   `rosy-site-<service>:<commit>`. Remove the override, then let it run;
2. downloads into `/opt/rosy/candidates/.staging-<tag>`, checks
   `SHA256SUMS`, joins the parts, applies the same tar member rules as
   `fetch_candidate.sh`, and moves the result to
   `/opt/rosy/candidates/<commit>`;
3. runs the installed verifier with the enrolled key (signature and hashes),
   `docker image load`, then the full verifier (loaded image IDs). The signed
   `source_commit` must match the selected full commit before loading;
4. backs up `site.env` to `site.env.autoupdate-prev`, durably records the
   previous folder and commit in the state file, then writes the new
   `ROSY_SITE_IMAGE_TAG`, swaps the `/opt/rosy/candidate` symlink (an
   existing real directory there is moved once to
   `/opt/rosy/candidates/<its commit>`), and restarts
   `rosy-site-stack.service`;
5. waits up to `health_timeout_s` for `healthz` 200 and all three containers
   running, healthy, and on the new image. Otherwise it restores the previous
   symlink and `site.env`, restarts, and records the tag as failed. A failed
   tag is never retried automatically. Any exception during switching also
   triggers rollback. Restart failures and timeouts remain retryable. On the
   next run an interrupted switch is undone before contacting GitHub. Failed
   rollback keeps its recovery record and blocks updates and pruning;
6. keeps the newest `keep` candidate folders (always the running and previous
   ones) and removes older `rosy-site-*` images that no container uses. Commits
   from retained manifests protect rollback images even in renamed folders.
   Failed inventory commands defer pruning.

Every step is one JSON line in `journalctl -u rosy-site-autoupdate`. The
state is in `/var/lib/rosy/site-autoupdate.json`
(`sudo python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py status`).
After fixing the cause of a failed tag, allow it again with
`sudo python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py forget-failed site-<sha12>`.
This command takes the updater lock. An unreadable or malformed state file
blocks changes and is preserved for operator recovery. Interrupted rollback
requires the backup environment and signed previous candidate to match the journal.
When `verify_candidate.py`, `candidate_signing.py`, or `site_update_io.py` change on `main`, the
administrator reinstalls them by the same reviewed path; the updater never
copies them from a candidate.

### Local maintenance and manual installation (D-441 follow-up)

Local Git edits and commits are source work: they do not replace the running
signed images. Publish, pass CI, build and sign a candidate to deploy that code.
The signing station now requires the newest `ci.yml` run for the exact main
commit and its `ci-result` gate to succeed. Pending, failed or unavailable CI
proof postpones signing; the same manifest is checked again next time.

Before changing the site deployment locally, use:

```bash
sudo python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py hold 'local maintenance'
# Finish and verify the local work, then explicitly resume.
sudo python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py resume
```

Both commands take the updater lock. Hold prevents new downloads, switches and
pruning. It does not stop recovery of an already interrupted switch; recovery
runs first. `status` shows the hold and `last_run.result=held`. Resume permits
checks again; it does not bypass signature or runtime verification.

A manually installed signed version is accepted only when its manifest,
environment tag and actual running image identities agree. After verification,
the updater reconciles `installed` with that real commit and marks its origin
`manual`. It clears uncertain previous history rather than inventing it. The
next automatic switch records this actual installation as `previous` and keeps
its rollback folder/images. A dry run does not adopt the manual installation.

The current Compose hashes must agree with the running containers' configuration
labels, and their root filesystems must remain read-only and unprivileged. An
ordinary local deployment/configuration mismatch blocks a switch; restore the
approved settings or keep the host on hold. This detects ordinary operational
drift; it does not defend against a root administrator forging Docker labels.
It also does not inspect every mutable database/configuration file's contents.

For a functional gate, add `functional_checks` to host `autoupdate.conf`:

기존 운영 계정 토큰 대신 전용 viewer를 만들 때는 검토된
`site_functional_setup.py`를 운영자의 sudo 터미널에서 실행한다.
기본 실행은 preflight만 수행하고 `--apply`는 계정·토큰·설정을 적용한다.
설치기는 현재 서명된 이미지와 실행 설정, 대기 작업, 기존 권한을 확인하고
Fleet만 재시작한다. 기존 사용자와 enrollment, 키, 타이머 상태를 보존한다.
사용자 파일의 Fleet 그룹 읽기 권한도 유지하며 새 raw token은 root0600이다.

중단된 설치는 같은 `--apply`로 먼저 복구한다. 모든 복구 자료의 checksum과
현재 파일을 확인한 뒤 기존 파일을 복원한다. 알 수 없는 로컬 수정은 덮어쓰지
않는다. API가 응답하지 않거나 작업 중이면 Fleet를 재시작하지 않고 복구 기록과
정지된 타이머를 유지한다. 원인을 해소한 뒤 같은 명령을 재실행한다.
완료 후 `/var/lib/rosy/site-functional-setup-receipt.json`과 실제 GET 응답을 확인한다.

이 gate는 Fleet의 등록 ID와 Vision source가 유지되는지 검사한다. 로봇의 online,
카메라 프레임 갱신, marker와 로봇의 물리적 대응, 주행 인수는 별도 검증한다.
정적 roster를 정리하기 전에 카메라 `robot_ids`와 `robot_markers` 참조를 함께
확인하고 실제 marker 부착을 확인한다. offline만으로 기존 등록이나 키를 지우지 않는다.

```json
"functional_checks": [
  {"path": "/api/fleet/state", "token_file": "/etc/rosy/site/secrets/<viewer-token-file>",
   "required_ids": ["<robot-id>"]},
  {"path": "/api/fleet/vision/sources", "token_file": "/etc/rosy/site/secrets/<viewer-token-file>",
   "required_ids": ["<camera-source-id>"]}
]
```

Use an enrolled viewer credential in a separate absolute regular file protected
by host permissions. It is read at request time and never placed in command
arguments or logs. Only these GET APIs on the health URL's HTTPS origin are
allowed; authenticated redirects are refused. The gate checks response structure
and required IDs before staging and after switching. A failing preflight leaves
the current installation in place; failure after switching triggers rollback.
Hosts without this setting retain the liveness-only gate. Listing a camera is
not proof of advancing frames, and listing a robot is not physical acceptance.
Record actual camera frame reception separately without sending motion.

The administrator must reinstall the reviewed updater, I/O and verifier modules
outside candidate folders to activate these changes; a new signed image alone
does not replace those privileged tools. Upgrade the signing station's reviewed
script separately as well, preserving its existing enrolled key.

**Pause.** Host: `sudo systemctl disable --now rosy-site-autoupdate.timer`.
Signing PC: `Disable-ScheduledTask -TaskName RosySiteAutoSign`. Either one
stops new deployments; builds on push keep running and are harmless.

**Roll back by hand.** Pause the host timer first, then point the symlink and
tag back at a kept folder and restart:

```sh
sudo systemctl disable --now rosy-site-autoupdate.timer
ls -lt /opt/rosy/candidates/
sudo ln -sfn /opt/rosy/candidates/<previous-commit> /opt/rosy/candidate.new
sudo mv -T /opt/rosy/candidate.new /opt/rosy/candidate
sudoedit /etc/rosy/site/site.env   # ROSY_SITE_IMAGE_TAG=<previous-commit>
sudo systemctl restart rosy-site-stack.service
```

The previous images stay loaded unless that folder was pruned. Re-enable the
timer only after `forget-failed` or once a newer fix is on `main`: while the
timer is on, a newer signed candidate replaces a manual rollback.

**Release count.** The build workflow keeps only the newest three `site-*`
releases, so pushes do not crowd the robots' release scan (D-412 reads the
first page of 20 releases, prereleases included). A host that was offline
through more than three builds installs the newest one.

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

`rosy-model-watch.timer` runs the perception model watcher (`model/watch.py`)
every 10 minutes through the stable entry point
`/opt/rosy/model-watch/bin/rosy-model-watch`. The wrapper looks for the watcher
in the source copy at `learning/training/perception/` first and at its pre-D-427
location second, so moving the perception tools does not break the unit. A
site host installed before this wrapper existed runs the old checkout path:
update the checkout and re-run `install-model-watch.sh` once. Automation stops at the shadow slot: selecting a learned model for
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
and runner from `middleware/perception`) and a Python venv with `onnxruntime`,
`onnx` (intake reads the graph's precision with it), `opencv-python-headless`,
`numpy` and `PyYAML`; NCNN intake additionally needs `ncnn==1.0.20260526`
(D-431; CPython 3.12 ARM64/x86_64 wheel hashes are pinned in
`deploy/robot/pinky_pro/image/learned-perception-requirements.txt`).
Add `huggingface_hub` only for `backend: hf`. A missing
package is a configuration error: the watcher exits 6 every run and records
nothing until the venv is fixed; `rosy_ml doctor --backend ncnn --watch-config` names the NCNN dependencies. It is not part of the signed site candidate (follow-up: add
the units and a pinned watcher bundle to `build_candidate.py`). Prepare both,
then run the install script from that checkout:

```sh
sudo install -d -o root -g root -m 0755 /opt/rosy/model-watch
sudo git clone --no-checkout <reviewed-remote> /opt/rosy/model-watch/src
sudo git -C /opt/rosy/model-watch/src checkout --detach <reviewed-commit>
sudo python3 -m venv /opt/rosy/model-watch/venv
sudo /opt/rosy/model-watch/venv/bin/pip install onnxruntime onnx==1.23.1 opencv-python-headless numpy PyYAML
sudo /opt/rosy/model-watch/venv/bin/pip install ncnn==1.0.20260526  # NCNN intake only
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
only writable path besides its state directory); installs the wrapper
`/opt/rosy/model-watch/bin/rosy-model-watch`, the unit and the timer; enables
the timer only when the config has no `<...>` placeholders left; and then
runs `rosy-model-watch doctor --watch-config /etc/rosy/model-watch.yaml`
(`rosy_ml doctor`) as the service user. It prints the remaining steps:

- **Site key.** The site host uses its own SSH key, not a person's;
  `ssh.identity` is required and has no default. Add the printed
  `site-ed25519.pub` line to `rosy`'s `authorized_keys` on each robot, so the
  site can be revoked without touching anyone else's access.
- **Host keys.** Record each robot's host key in
  `/etc/rosy/model-watch/known_hosts` from a trusted network
  (`StrictHostKeyChecking=yes`), **under the robot id** (the config's `name`),
  not the address: `ssh-keyscan -t ed25519 <hostname>.local | sed 's/^[^ ]* /<robot-id> /'
  >> /etc/rosy/model-watch/known_hosts`. The watcher passes
  `-o HostKeyAlias=<robot-id>`, so the pin follows the robot when the network is
  renumbered. A mismatch is still refused (exit 79); nothing is auto-accepted.
  An older address-keyed entry is reported by `rosy_ml doctor --watch-config`,
  which prints the one command that copies it under the id:
  `rosy_ml repin --watch-config /etc/rosy/model-watch.yaml <robot-id>`
  (it never rewrites `known_hosts` on its own).
- **Config.** `sudoedit /etc/rosy/model-watch.yaml`: robots, `store`,
  `replay_root`. A robot's `host` is its mDNS name `<hostname>.local`
  (avahi, `rosy-pinky-<4 chars>`), not an IP: the site network renumbers and
  an IP then fails silently for hours. An IP still works but doctor flags it.
  The config names robot hosts and so stays out of the checkout.
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
unreadable, or the HF listing failed) and nothing was recorded, `6` intake
cannot run on this host (venv package missing). A robot that cannot be reached
makes the run exit with its own code and the unit show `failed` (the timer keeps
firing every 10 minutes): `77` its host name did not resolve (DNS / mDNS, or the
name in the config is wrong), `78` connection refused, timed out or no route
(robot off or on another network), `79` its host key is unknown or changed
(never auto-accepted: check the robot, then re-pin it). The journal has one line
per robot, e.g. `pinky-a: dns failure (exit 77, 3 in a row): ...`. A network
failure spends no delivery attempt, so a long outage never turns into
`gave_up`. The last failure per robot (kind, exit, time, consecutive count) is
kept in `state.json` under `robot_failures`, cleared when the robot answers
again, and shown by `rosy_ml status --watch-config /etc/rosy/model-watch.yaml`
and `rosy_ml store-status --watch-config ...`. `rosy_ml doctor --watch-config`
resolves every configured host and reports the ones that do not. The state
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

## Rosy Cam 화면 상태 확인·깨우기

관제 PC의 자체 ADB 키로 공식 Android 무선 디버깅 페어링을 먼저 완료한다.
Windows 등 다른 PC의 개인 키를 복사하지 않는다. `cam-screen.json.example`을
저장소 밖의 개인 JSON 설정으로 복사하고 설치된 ADB 절대 경로, 실제 전화의
`ro.serialno`, `ro.product.model`을 입력한다. 실제 식별자·주소는 공개 파일에
기록하지 않는다.

```bash
python3 deploy/site/rosy_cam_screen.py status --config /private/path/cam-screen.json
python3 deploy/site/rosy_cam_screen.py wake --config /private/path/cam-screen.json
python3 deploy/site/rosy_cam_screen.py light-status --config /private/path/cam-screen.json
python3 deploy/site/rosy_cam_screen.py light-request --config /private/path/cam-screen.json
python3 deploy/site/rosy_cam_screen.py light-cancel --config /private/path/cam-screen.json
```

CLI는 이미 인증된 연결을 먼저 검사하고, 없으면 ADB mDNS 및 Avahi의
`_adb-tls-connect._tcp`에서 예상 serial의 후보를 찾아 변경된 포트로 재연결한다.
발견 이름만 믿지 않고 실제 serial과 model을 모두 확인한 단일 연결에만
`KEYCODE_WAKEUP`을 보낸다. 미인증·오프라인 연결, 식별 불가·불일치·다중 연결은
거절한다. 페어링이나 ADB 권한 변경은 이 CLI가 수행하지 않는다.
목록에 다른 기기의 오프라인·미인증 연결이 있어도 보수적으로 거절하므로 먼저
ADB 연결 목록을 확인한다. 발견된 오래된 포트가 응답하지 않으면 다음 후보를
시도하지만, 다른 실제 식별자가 응답하면 즉시 거절한다.

`status`도 필요한 경우 기존 페어링으로 재연결한다. `wake_sent`는 깨우기 명령
전달 결과이며 잠금 해제나 영상 수신 증거가 아니다. OS 화면 상태와 실제 JPEG의
증가하는 sequence·freshness를 별도로 확인한다. ADB가 끊기거나 무선 디버깅이
꺼진 경우에는 공식 재연결·페어링 경로를 사용한다. 충전 중 화면 유지와 화면
제한시간은 전화의 OS 설정이며, 앱의 화면 유지 해제만으로 설정을 덮어쓰지 않는다.

조명은 기본 꺼짐이며 요청 없이 반복 점등하지 않는다. `light-request`는 실행 중인
Rosy Cam의 공식 `촬영 조명 요청` 버튼만 조작한다. 그 요청 안에서만 저조도를
판단하고, 요청부터 최대 30초 후 요청과 조명을 모두 종료한다. 이미 요청 중이면
시간을 연장하지 않으며, `light-cancel`은 즉시 취소한다. 재시작·렌즈 교체·발열
제한 시 취소하고, 어둡거나 온도가 회복돼도 새 요청 없이 재개하지 않는다.

`light-status`는 화면을 깨우지 않고 서비스의 boolean 상태만 읽는다. 제어 결과의
`light_requested`는 요청 수락 상태이며 실제 점등은 `torch_on`으로 따로 확인한다.
조작은 검증된 장치·앱의 최신 UI를 확인하며, 잠긴 보안 화면·미지원 렌즈·발열
제한·중복/변경 UI는 거절한다. 보안 잠금을 우회하거나 송출을 자동 시작하지 않는다.
화면 방향 등 UI 배치가 인식 범위를 벗어나면 수동 조작이 필요하다.
