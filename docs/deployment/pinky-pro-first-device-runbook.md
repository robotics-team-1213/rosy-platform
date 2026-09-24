# Pinky Pro first-device commissioning runbook

Date: 2026-09-21
Scope: first physical connection, install, stationary proof, motor/deadman check,
LiDAR mapping, and a bounded navigation smoke test.

This is a fail-closed G0-G5 procedure. A `GO` means only that its named gate has
valid evidence. ARTIFACT, DEVICE, calibration, and FIELD stay `HOLD` until their
own physical evidence exists. Do not copy Gazebo geometry, robot diameter,
speed, stopping distance, or `map_260905_update_v2` results into a device
certificate.

## 0. Build and sign the G0 release

Do this before powering the target robot. The image build host must be a native
ARM64 Linux machine; an x86/QEMU build is development evidence only. Start from
the exact clean commit that will be commissioned and retain the builder JSON:

```bash
set -euo pipefail
test "$(uname -m)" = aarch64
test -z "$(git status --porcelain)"
RELEASE_ID=2026.09.21-001
SIGNING_KEY_ID=rosy-release-2026-01
REVISION="$(git rev-parse HEAD)"
# Copy this digest from the approved registry-manifest evidence. A mutable tag
# such as ros:jazzy-ros-base is refused.
ROS_IMAGE='ros:jazzy-ros-base@sha256:<64-hex-registry-digest>'
PAYLOAD="/var/tmp/rosy-${RELEASE_ID}-unsigned"
python3 deploy/release/arm64_release_builder.py \
  --repo-root "$PWD" --output "$PAYLOAD" --release-id "$RELEASE_ID" \
  --signing-key-id "$SIGNING_KEY_ID" --ros-image "$ROS_IMAGE" \
  | tee "/var/tmp/${RELEASE_ID}-unsigned-payload-build.json"
```

The builder creates two Docker-save archives and an unsigned manifest. It
refuses non-ARM64 images and checks that both image labels match `$REVISION`.
It never reads a private key. Transfer the complete payload and builder JSON to
the offline signing environment, then sign and verify there. The private key
must remain outside both the payload and the target robot:

When no separate native build host is available, D-145 provides the same
unsigned handoff on GitHub's native ARM64 runner. It still does not sign:

```bash
gh workflow run build-arm64-payload.yml --ref main \
  -f release_id="$RELEASE_ID" \
  -f signing_key_id="$SIGNING_KEY_ID" \
  -f ros_image="$ROS_IMAGE"
# After that exact run succeeds, download its named unsigned artifact.
gh run download RUN_ID --name "rosy-unsigned-${RELEASE_ID}-${REVISION}"
ARCHIVE="rosy-unsigned-${RELEASE_ID}-${REVISION}.tar.zst"
CHECKSUM="${ARCHIVE}.sha256"
HANDOFF="/trusted/rosy-unsigned-${RELEASE_ID}-${REVISION}"
python3 deploy/release/import_unsigned_payload.py "$ARCHIVE" \
  --checksum "$CHECKSUM" --output "$HANDOFF" \
  --release-id "$RELEASE_ID" --git-revision "$REVISION" \
  --signing-key-id "$SIGNING_KEY_ID" \
  | tee "/trusted/${RELEASE_ID}-unsigned-import.json"
PAYLOAD="$HANDOFF/rosy-unsigned-payload"
```

Retain the run URL and job result with the builder JSON. The Actions artifact
expires after seven days, so move the verified archive to the offline signing
environment before then. The importer verifies the outer checksum before
decompression, rejects unsafe archive members, and binds builder, manifest,
provenance, payload hashes, and both `linux/arm64` image configs to the expected
release identity. Its `signed: false` result is a verified handoff, not G0.

```bash
set -euo pipefail
PUBLIC_KEY="/secure/${SIGNING_KEY_ID}.pem"
PRIVATE_KEY="/secure/${SIGNING_KEY_ID}.key"
BUNDLE="/trusted/rosy-release-${RELEASE_ID}.tar.zst"
python3 deploy/release/package_release.py "$PAYLOAD" "$BUNDLE" \
  --public-key "$PUBLIC_KEY" --private-key "$PRIVATE_KEY"
python3 deploy/release/publication.py verify-publication "$BUNDLE" \
  --release-id "$RELEASE_ID" --git-revision "$REVISION" \
  --public-key "$PUBLIC_KEY" --json \
  | tee "/trusted/${RELEASE_ID}-signed-bundle-verification.json"
```

Copy the bundle, matching public key, unsigned builder JSON, and
`signed-bundle-verification.json` to trusted removable media. Do not proceed to
G0 if either JSON says `ok: false`, if the public-key filename stem differs
from the manifest `signing_key_id`, or if the source revision differs.

## 1. Prepare before power-on

- Two people for G4/G5: one operator and one person at the physical power cut.
- Wheels-off-ground stand, clear floor zone, tape measure/caliper, charger, and
  a wired LAN cable. Keep the E-stop reachable at all times.
- Raspberry Pi 5, arm64 Raspberry Pi OS Lite, camera, LiDAR, and motors must be
  mechanically secured. Do not hot-plug motor power or the CSI ribbon.
- Bring the complete calibration input file. The supplied two-photo checker
  homography marked `approximate_requires_physical_validation` is a candidate,
  not an accepted robot-frame calibration. A truncated chat copy is unusable.
- Create an evidence directory. Raw outputs are never edited after hashing:

```bash
sudo install -d -o "$USER" -g "$(id -gn)" -m 0750 /var/lib/rosy/commissioning
SESSION=/var/lib/rosy/commissioning/pinky-01-$(date -u +%Y%m%dT%H%M%SZ).json
EVIDENCE="${SESSION%.json}.evidence"
mkdir -m 0750 "$EVIDENCE"
```

### 카드 쓰기 중 문제가 생겼을 때

카드 쓰기(`deploy/sd/write-card.ps1`)는 실패하면 스스로 멈추고, 카드 상태와 다음 명령을 알린다(D-187).
실패 문구 끝은 늘 이 형식이다.

```text
the card could not be read during readback (removed, disconnected or I/O error): media is shorter than the image at byte offset 4194304 (verified 4194304 bytes before it stopped)
stage=readback card_state=written-unverified
next: reinsert the card (or use another reader), then re-run the same command with -ResumeAfterWrite (...)
```

readback이 실패하면 verifier가 말한 이유(불일치 offset, 짧은 읽기, OSError)와 검증된 바이트 수가 이 문구, 진행 파일의
`failed` 줄 `detail`, 로그에 함께 남는다. 불일치는 데이터가 틀린 것(재기록, 반복되면 카드 교체)이고, 읽기 오류나 짧은
읽기는 리더기·연결 문제(다시 꽂거나 다른 리더기로 resume)다.

**쓰기는 분리 실행으로 띄운다 (D-188).** 쓰기는 30분에서 1시간 넘게 걸린다. 에이전트 세션이나 곧 닫을 셸의 자식으로
띄우면 그 세션과 함께 사라진다(release 005). `-Detach`는 관리자 창 하나를 따로 띄우고 바로 돌아온다. UAC는 한 번이다.
띄운 콘솔이나 에이전트를 닫아도 쓰기는 계속된다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\sd\write-card.ps1 `
  -PlanPath <cards>\plan-<release>-<device>.json `
  -ReleaseDir <signed release dir> `
  -WifiProfile <profile> `
  -Detach
```

출력되는 `Log:`, `Progress:`, `Exit marker:`, `Status:` 경로를 적어 둔다. ERASE 문구는 새 관리자 창에 입력한다.
처음 쓸 때 준 `-OperatorPublicKey`·`-ReprovisionReceipt`는 여기에도 같이 준다. 끝나면 창에 `EXIT_CODE=`가 남고,
로그 옆에 `.exit` 표지가 생긴다. 창은 결과를 보인 채 열려 있다.
UAC 창에서 "아니요"를 눌렀거나 시간이 지났으면 launcher가 `failed`/`untouched`와 `next:`를 진행 파일에 남기고 실패한다.
카드는 건드리지 않았으니 다시 띄운다.

**상태 보기.** 관리자 권한은 필요 없다. `Status:` 줄의 명령을 그대로 실행한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\sd\card-write-status.ps1 -LogPath <log>
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\sd\card-write-status.ps1 -LogPath <log> -Json   # 에이전트용
```

```text
Stage: readback   card_state: written-unverified
Bytes: 4,800 MB of 8,170 MB (58.8 %)
Rate: 20.1 MB/s over the last heartbeats
Pre-flight read: 21.3 MB/s (slow-media limit 10.0 MB/s)
ETA this stage: 3 min (about 14:32)
ETA whole job: 3 min (about 14:32)
Last progress line: 42 s ago
```

- `ETA this stage`는 이번 단계(`write` 또는 `readback`)의 남은 바이트를 최근 heartbeat의 실제 속도로 나눈 값이다.
  `ETA whole job`은 쓰기 중이면 남은 쓰기에 readback 예측(사전 측정 읽기 속도)을 더한다. 쓰기 전이면 사전 측정의 전체 예측이다.
  완료 시각을 말할 때는 이 값을 인용한다. 짐작으로 말하지 않는다.
- `STALLED:`가 보이면 멈춘 것이다. `write`·`readback`에서 바이트가 5분 넘게 늘지 않았거나, 다른 단계에서 5분 넘게 새 줄이 없었다.
  `write`는 도구가 Imager를 끝내고(`-WriterStallMinutes`, 기본 5), `readback`은 verifier를 끝낸 뒤(`-ReadbackStallMinutes`, 기본 5)
  스스로 실패한다. 상태에 `Result: FAILED`와 `next:`가 곧 뜬다. 창이 사라졌거나 얼었으면 창을 닫고 `next:`를 따른다.
- `Waiting for:`는 멈춤이 아니다. 관리자 창이 ERASE 문구나 느린 매체 질문의 답을 기다리는 중이다.
- 끝나면 `Result: COMPLETE` 또는 `Result: FAILED - <이유>`와 `next:` 한 줄이 나온다.

**느린 매체 경고.** ERASE 문구 전에 카드 앞 128 MiB를 읽기 전용으로 읽어 속도를 잰다. 창에 `Pre-flight:` 줄로 예상 쓰기·readback·
전체 시간이 나온다. 읽기 속도가 10 MB/s(`-MinReadMBps`) 미만이면 `SLOW MEDIA` 경고가 나온다(005 카드는 readback이 약 3.4 MB/s로
약 60분 걸렸다). 이렇게 한다.
- 다른 USB 포트(USB 3.0)에 꽂거나 다른 리더기를 쓴다.
- 가능하면 USB 3.0 리더기와 A1/A2 또는 U3 등급 카드를 쓴다.

그래도 이 카드로 쓰려면, 창에서 `SLOW`를 입력하거나 명령에 `-AcceptSlowMedia`를 붙인다. `-Confirmation`을 넘긴 비대화형 실행은
이 플래그 없이는 카드를 건드리지 않고 멈춘다.

**다른 카드를 꽂았을 때.** plan은 꽂힌 카드의 MBR disk signature나 GPT GUID를 기록한다. 같은 리더기에 다른 카드를 꽂으면
`a different card is in the reader`로 ERASE 전에 멈춘다(`card_state=untouched`). 싼 리더기는 같은 가짜 시리얼(`000000000207`)을
공유하므로, 시리얼만으로는 카드를 구분하지 못한다. 공장 초기 카드는 신원이 없어 시리얼과 크기만 확인하고 경고한다. 그럴 때는
라벨을 확인한다. 이미 이 릴리스로 써진 카드는, 같은 plan으로 쓰다 멈춘 기록(로그 폴더의 진행 파일)이 있고 `rosy-provision/`이
없을 때만 다시 쓴다. 다른 로봇용으로 다 쓴 카드는 지우지 않고 멈춘다.

**진행 파일 직접 읽기.** 상태 명령이 읽는 파일은 `<log>.progress.jsonl`이다. 단계가 바뀔 때마다 JSON 한 줄이 붙는다. 쓰기와
readback 중에는 약 60초마다 `heartbeat` 줄에 지금까지 처리한 `bytes`가 붙는다.

- 단계 순서: `launch` → `verify-signature` → `select-disk` → `preflight` → `confirm` → `write` → `readback` → `bundle` →
  `bundle-writing` → `receipt` → `done`. 실패하면 마지막 줄이 `failed`이고, `detail`에 원인이, `next`에 다음 행동이 있다.
- 창이 사라졌거나 PC가 꺼졌으면 마지막 줄의 `card_state`로 다음 명령을 고른다.

| 마지막 `card_state` | 다음 명령 |
|---|---|
| `untouched` | 같은 명령을 다시 실행 |
| `writing` | 전체 쓰기를 다시 실행(`-ResumeAfterWrite` 없이) |
| `written-unverified`, `verified-no-bundle` | 같은 명령에 `-ResumeAfterWrite`를 붙여 실행 |
| `bundle-partial` | 전체 쓰기(부분 bundle은 resume으로 끝낼 수 없다) |
| `complete`(receipt 없음), `unknown` | 실패 문구의 `next:`를 따른다. 모르면 전체 쓰기 |

**쓰기를 다시 하지 않고 이어 가기.** 카드가 끝까지 써진 뒤 Imager가 멈췄거나 readback 중 카드가 빠졌으면, 쓰기(약 16–20분)를
건너뛰고 readback부터 다시 한다. 서명 검증, 시리얼 선택, plan 대조, ERASE 확인은 그대로 거친다. 카드 첫 섹터의 MBR signature가
이미지와 다르면 readback 전에 멈춘다. boot 파티션에 `rosy-provision/`이 이미 있어도 멈춘다. 카드가 서명된 이미지와 다르면
readback이 bundle 전에 멈추므로, 잘못 골라도 잃는 것은 readback 한 번이다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\sd\write-card.ps1 `
  -PlanPath <cards>\plan-<release>-<device>.json `
  -ReleaseDir <signed release dir> `
  -WifiProfile <profile> `
  -ResumeAfterWrite -Detach
```

receipt에는 `resumed_after_write: true`가 남는다. plan의 receipt가 이미 있으면 거부한다(이미 끝난 카드다).

### 전원을 넣으면 보이는 것 (D-190)

LCD는 CORE 밖의 `rosy-boot-display.service`가 그린다. 전원을 넣고 몇 초 안에 첫 화면이 뜨고, 단계가 바뀌면 1초
안에 다시 그린다.

| 화면 단계 | 뜻 | 다음 행동 |
|---|---|---|
| `BOOTING`(회색) | 첫 부팅 개인화나 런타임이 아직 시작 중 | 기다린다. 첫 부팅은 1분 안팎 |
| `PROVISIONED` | 신원·Wi-Fi 적용 끝, CORE 시작 중 | 기다린다 |
| `READY` | CORE가 준비됐다. 아래 `IP:포트`로 대시보드·API에 접속 | 접속한다 |
| `FAILED`(빨강) + unit 이름 | 그 unit이 실패했다 | `journalctl -b -u <unit>`, 또는 카드의 `rosy-diag/` |

- 둘째 줄부터: `IP:포트`(IP가 없으면 `no IP address`), 배터리 %·전압(ADC를 못 읽으면 `battery --`).
- 현장 Wi-Fi 없이 120 s가 지나 AP가 열리면 `Wi-Fi rosy-pinky-xxxx`와 `PW <비밀번호>`, 주소 `10.42.0.1:8080`이 뜬다.
  비밀번호는 카드별이고(D-176), 화면에만 나오며 로그에는 남지 않는다. 업링크가 돌아오면 사라진다.
- 부저는 **기본으로 꺼져 있다.** Pro의 부저 핀이 아직 확인되지 않았기 때문이다(D-190 "부저 핀 확인"). 확인한 뒤
  `/etc/rosy/boot-display.env`에 `ROSY_BUZZER_ENABLED=true`(핀이 22가 아니면 `ROSY_BUZZER_PIN=<BCM>`도)를 쓰고
  `sudo systemctl restart rosy-boot-display` 한다. 그러면 `READY`에 한 번, `FAILED`에 세 번 짧게 울린다.
- 화면이 비어 있으면: `systemctl status rosy-boot-display`, `journalctl -b -u rosy-boot-display`. `/dev/spidev0.0`이
  없으면 패널이 없는 보드로 보고 조용히 끝난다. 노드가 있는데 그리지 못하면(라이브러리, GPIO 칩 label, 열기 실패) unit이
  `failed`가 되고 이유가 journal에 한 번 남는다. HDMI 콘솔 배너(D-174)와 `_rosy._tcp` mDNS는 LCD와 상관없이 같은 단계를 보인다.

## 2. Connection choice

### SSH path

Connect the Pi and workstation to the same wired LAN, find the address from the
router/DHCP lease, and pin the host key before transferring anything:

```powershell
ssh-keygen -F pinky-01.local
ssh rosy@pinky-01.local
```

If mDNS is unavailable, use the DHCP address. A changed host key is a stop
condition until the Pi identity is physically confirmed.

Verify the selected LAN before commissioning. `auto` prefers the default-route
interface; use `eth0` explicitly on the wired bench:

```bash
sudo /opt/rosy/deploy/robot/verify/verify-pi.sh --interface eth0
```

From Windows, verify that the API and dashboard are reachable by another host:

```powershell
$ConnectionEvidence = Join-Path $PWD "G0-connection-evidence.json"
./deploy/robot/verify/verify-from-windows.ps1 `
  -PiHost pinky-01.local -NetworkInterface eth0 `
  -BatchMode -ConnectTimeoutSec 5 -EvidencePath $ConnectionEvidence
```

This command does not change network settings or robot state. A JSON `GO` is
connectivity evidence only: it proves bounded key-based SSH plus `/api/v1` and
`/dashboard` reachability over the selected interface. It is not G0 artifact
acceptance and does not advance DEVICE or FIELD. Preserve the file with the
session evidence; the verifier refuses to replace an existing evidence file.

#### One-command stationary validation from Windows

When the signed manifest revision and robot number are known, run this from the
repository root. It joins peer connectivity, API/dashboard reachability, device
readback, exact robot identity, and exact release revision into one verdict. It
does not change runtime mode or send motor commands.

```powershell
$Revision = "<signed-manifest-full-40-character-git-revision>"
$Evidence = Join-Path $PWD ("pinky-01-preflight-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
./deploy/robot/verify/validate-pinky-from-windows.ps1 `
  -PiHost pinky-01.local -PiUser rosy -NetworkInterface eth0 `
  -ExpectedRobotNumber 1 -ExpectedRevision $Revision `
  -EvidenceDirectory $Evidence
```

The directory contains raw `G0-connection.json`, `G2-device-readback.json` when
collection succeeds, final `user-validation-summary.json`, and
`SHA256SUMS.txt`. Existing evidence is never replaced. If
`summary.outcome=HOLD`, repair the named `failed_checks`. If non-interactive
`sudo` is unavailable over SSH, the tool still records HOLD evidence and the
operator switches to the Pi local-console procedure.

`GO != motion authorization`. Even a GO result keeps
`motion_authorized: false`; its next gate is `G3_SENSOR_ONLY`. Open the reported
`dashboard_url` for observation. G4 wheels-off-ground work and G5 low-speed
floor motion still require their separate physical conditions and two-person
procedure.

### Local console path

Connect a display and keyboard, sign in locally, and use the same commands
below. The session records `console`; it does not weaken any gate. Network loss
after installation is not a reason to skip readback or safety checks.

G0 stages and verifies the signed bundle before `commission-pinky.py init`, so
the session revision comes from that verified manifest. Run the evidence CLI as
the ordinary owner of `/var/lib/rosy/commissioning`, never through `sudo`; only
the release/runtime commands below need root. For the Local console path, use
`--connection console`. Never attach a password, token, credential, private
key, or `.env` file.

### Changing the site Wi-Fi on the card (D-176)

Power the robot off and put the card in a PC. The boot partition holds
`rosy-config.yaml`, a commented template written with the card. Uncomment the
`wifi:` block, set the SSID and password, save, and boot the robot. At boot
`rosy-config.service` applies the file and rewrites every password on the card
as `"<applied>"`; the Wi-Fi key stays only in the root-only NetworkManager
profile. An invalid file applies nothing: the console banner and
`rosy-diag/` on the boot partition name the error. Identity keys
(`device_name`, `hostname`, ...) are refused here; change identity by
rewriting the card with `-ReprovisionReceipt`.

### Reaching the robot through its own AP (D-176)

With no uplink for 120 s the robot opens the WPA2 AP named after the device
(`rosy-pinky-xxxx`). The password was printed once when the card was written
and is kept in the writer PC's DPAPI store
(`%LOCALAPPDATA%\Rosy\ap\<device>.credential.xml`); a local console also shows
it. Join the AP and connect with the operator key:

```powershell
ssh -i $env:LOCALAPPDATA\Rosy\ssh\rosy-operator-ed25519 rosy@10.42.0.1
```

Pi 5 has one radio, so while the AP is up the site Wi-Fi is not scanned. After
600 s the AP steps aside for another 120 s site Wi-Fi attempt. `ap.mode: relay`
keeps the AP up; `ap.mode: off` never opens it.

### CORE API administrator credential (D-191)

Every card written with `prepare-rosy-sd.ps1` / `write-card.ps1` gets its own
CORE API administrator credential. The writer prints it once at the end
(`CORE API administrator for rosy-pinky-xxxx: id <id> value <value>`) and keeps
it in the writer PC's DPAPI store,
`%LOCALAPPDATA%\Rosy\api\<device>.credential.xml`, with `<CORE token id>|<device_uid>`
as the user name. The card carries only CORE's sha256 record; plans, receipts
(`personalization.core_api` holds the id and a 16-hex digest fingerprint) and
the progress file never hold the value. A write through `write-card.ps1` ends
its log with the read-back command, because the one-time line is not in the
transcript. Read it back on the same Windows account that wrote the card:

```powershell
$c = Import-Clixml "$env:LOCALAPPDATA\Rosy\api\rosy-pinky-xxxx.credential.xml"
$id, $uid = $c.UserName -split '\|'      # CORE token id, device_uid
$c.GetNetworkCredential().Password       # the credential itself
```

Use it as `Authorization: Bearer <value>` or paste it into the dashboard login.
First boot installs the record into `/var/lib/rosy/core/.rosy/rosy.yaml`
(`rosy-core`, 0600), the overlay CORE reads under `rosy-core.service`
(`HOME=/var/lib/rosy/core`), marked `source: card` (`GET /api/v1/auth/whoami`
answers `administrator`, `card`). The shared `rosy-dev-*` credentials never work
on a device (D-193 7): the packaged defaults carry no tokens, the dev tokens are
merged only with `ROSY_DEV_AUTH=1` on a development host, and CORE in device
mode (`ROSY_DEPLOYMENT=device`, set by `rosy-core.service` and `runtime.env`)
refuses their digests and any plaintext entry wherever they come from. With no
credential at all CORE still starts and answers every request with 401;
recover with `sudo rosy-login-code --role administrator` below. First boot holds
provisioning (`PROVISIONING_HOLD`) when
the bundle has no record, when that file already holds a credential other than
this card's own, or when any part of that path is a symlink or not a regular
file/directory.

The store is bound to the device: a store file for the same device name but
another `device_uid` stops the write before the card is touched (move it away if
that robot is retired). A store written before this binding is accepted once and
rewritten with the uid; the AP store (`Rosy\ap`) follows the same rule.

Rewriting the same device (`-ReprovisionReceipt`, or a retried write) reuses the
stored credential, so dashboards and scripts keep working. To get a new one on
the next write, delete the store file first. To rotate on a running robot,
create a new administrator credential, switch to it, then delete the old one:

```powershell
$h = @{ Authorization = "Bearer $($c.GetNetworkCredential().Password)" }
$new = Invoke-RestMethod -Method Post -Uri "http://rosy-pinky-xxxx.local:8080/api/v1/system/tokens" `
    -Headers $h -ContentType application/json -Body '{"role":"administrator","label":"rotated"}'
# $new.token is shown only in this response. Store it before continuing:
$secure = ConvertTo-SecureString $new.token -AsPlainText -Force
New-Object System.Management.Automation.PSCredential("$($new.id)|$uid", $secure) |
    Export-Clixml "$env:LOCALAPPDATA\Rosy\api\rosy-pinky-xxxx.credential.xml"
Invoke-RestMethod -Method Delete -Headers @{ Authorization = "Bearer $($new.token)" } `
    -Uri "http://rosy-pinky-xxxx.local:8080/api/v1/system/tokens/$id"
```

The dashboard's token settings do the same (`GET/POST/DELETE
/api/v1/system/tokens`, `PATCH` for the label). CORE refuses to delete the
credential in use or the last administrator without an expiry: a paired
(24 h) administrator does not count.

### Dashboard login code (D-193)

Tablets and other PCs do not need the 43-character credential. A root service,
`rosy-login-code.service` (no network, outside CORE), issues a one-time
8-character code such as `ABCD-EFGH` after the first `CORE_READY` of each boot:

- The LCD shows `Login ABCD-EFGH operator` under the stage (only at
  `CORE_READY`). The same code is on the local console banner
  (`/etc/issue.d/60-rosy-login.issue`).
- Type it in the dashboard login (the "robot screen code" tab arrives with
  S3; until then `POST /api/v1/auth/pair` with `{"code": "ABCD-EFGH"}` from the
  robot LAN). The browser gets its own token: `operator`/`viewer` for 7 days,
  `administrator` for 24 h (`auth.pairing.token_lifetime_hours`), listed as
  `pair-physical` in the token settings and revocable there or with
  `POST /api/v1/auth/logout`.
- The code works once and for 10 minutes on the robot's monotonic clock, only
  from RFC 1918 addresses, the AP (`10.42.0.0/24`) or loopback. It leaves the
  LCD within a second of use. Five wrong tries burn it: the LCD shows
  `Login code burned` for a minute. More than five tries per address per minute
  (30 in total) are answered 429.
- The card decides the boot code: `login: {boot_code: off | operator |
  administrator}` in `rosy-config.yaml` (default `operator`). Where passers-by
  can read the LCD, set `off`.
- An administrator can enroll another device from the dashboard:
  `POST /api/v1/auth/enrollment-codes` returns a 5-minute code (role at most
  the caller's, kept in CORE memory only; tokens from it are `pair-admin`).

No LCD, or a code on demand: over SSH or the local console,

```bash
sudo rosy-login-code                          # operator, 10 minutes
sudo rosy-login-code --role administrator --minutes 5
```

prints the code to that terminal only (never to the journal), replaces any
earlier code and also puts it on the console banner. This is also the recovery
path when a robot has no working credential.

The code is never in CORE, the avahi TXT record, the black box or a
diagnostics bundle: CORE reads only the scrypt verifier
`/run/rosy-boot/login-code.json` (root:rosy-core 0640) and tells root through
`/run/rosy/login-code-state.json` that the code was used or burned. Plain HTTP
is still the transport (D-193 10): keep the robot LAN an operator-only
SSID/VLAN.

## 3. Record contract

For every gate, save raw output under `$EVIDENCE`. `prepare` derives G0-G2 from
the actual release/readback JSON and validates the G3-G5 operator-attested body.
`record` re-derives/rechecks the claims, hashes every supplied file, locks the
session, and appends one gate atomically:

In the examples, `python3 "$COMMISSION" record` is the installed equivalent of
the `commission-pinky.py record` operation.

```bash
COMMISSION=/opt/rosy/deploy/robot/commission-pinky.py
python3 "$COMMISSION" prepare \
  --session "$SESSION" --record "$EVIDENCE/G2-record.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G2-record.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
python3 "$COMMISSION" status --session "$SESSION"
```

G3-G5 use an exact body file from
[the body templates](pinky-pro-commissioning-body-templates.md). Use each gate's
exact command below: G3 requires the G2 readback plus ten individual state JSON
files, G4 requires eight distinct trial digests, and G5 requires four distinct
role-bound digests. A body file by itself is always refused.

For G3-G5, the exact body is an explicit operator attestation backed by raw
telemetry. It is not a cryptographic sensor signature. G0 is instead derived
from the verified signed manifest and `STAGED` result; G1 from the successful
activation result and device readback; G2 from the readback itself.

The record common fields are filled by `prepare`: `schema_version`, `gate`,
`captured_at`, full lowercase `source_revision`, integer `robot_number`, and
`outcome: "GO"`. A validation error leaves the session unchanged. After G1,
use `/opt/rosy/deploy/robot/commission-pinky.py`; before it, use the copy inside
the same verified release payload.

## 4. Gates

### G0 - signed native artifact

Before installation, prove the release is signed, its manifest matches the full
Git revision, the target is Raspberry Pi 5 arm64 Raspberry Pi OS Lite, and both
`rosy_core` and `rosy_io` use immutable `sha256:` image digests.

```bash
RELEASE_ID=YYYY.MM.DD-NNN
COMMISSION=/trusted/verified-release/deploy/robot/commission-pinky.py
sudo rosy-release stage "/trusted/rosy-release-${RELEASE_ID}.tar.zst" --json \
  | tee "$EVIDENCE/G0-stage.json"
sudo install -o "$USER" -g "$(id -gn)" -m 0640 \
  "/var/cache/rosy/releases/${RELEASE_ID}/manifest.json" \
  "$EVIDENCE/G0-manifest.json"
REVISION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["git_revision"])' \
  "$EVIDENCE/G0-manifest.json")"
python3 "$COMMISSION" init \
  --session "$SESSION" --robot-number 1 --source-revision "$REVISION" \
  --connection ssh --operator "OPERATOR_NAME"
python3 "$COMMISSION" prepare \
  --session "$SESSION" --record "$EVIDENCE/G0-record.json" \
  --evidence-file "$EVIDENCE/G0-manifest.json" \
  --evidence-file "$EVIDENCE/G0-stage.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G0-record.json" \
  --evidence-file "$EVIDENCE/G0-manifest.json" \
  --evidence-file "$EVIDENCE/G0-stage.json"
```

Stop on any signature, target, revision, or digest mismatch. A Windows source
upload and a locally built candidate do not satisfy G0.

### G1 - install, core only

Install the verified release by its release ID. The installer must finish with
exit code 0 and leave the requested robot identity in `core` mode:

```bash
sudo rosy-release runtime down
sudo rosy-release install --release-id YYYY.MM.DD-NNN --json \
  | tee "$EVIDENCE/G1-install.json"
sudo /opt/rosy/deploy/robot/runtime-mode.sh status \
  | tee "$EVIDENCE/G1-runtime-status.txt"
sudo /opt/rosy/deploy/robot/verify/device-readback.sh \
  | tee "$EVIDENCE/G2-device-readback.json"
COMMISSION=/opt/rosy/deploy/robot/commission-pinky.py
python3 "$COMMISSION" prepare \
  --session "$SESSION" --record "$EVIDENCE/G1-record.json" \
  --evidence-file "$EVIDENCE/G1-install.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G1-record.json" \
  --evidence-file "$EVIDENCE/G1-install.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json" \
  --evidence-file "$EVIDENCE/G1-runtime-status.txt"
```

For robot 1 the derived values are `ROS_DOMAIN_ID=41` and namespace `rosy_01`.
Never proceed if the installer quarantines the runtime or starts motor/hardware.

### G2 - immutable device readback

```bash
python3 "$COMMISSION" prepare \
  --session "$SESSION" --record "$EVIDENCE/G2-record.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G2-record.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
```

Record the complete JSON as the G2 `readback`. It must match the G0 revision and
both image digests, report a verified signature, active/healthy CORE, derived
identity, exactly one final `cmd_vel` publisher, and `device_runtime: GO`.

### G3 - stationary CORE proof

Keep wheels lifted and keep E-stop asserted. CORE stays in `IDLE`; do not start
motor or hardware. Capture at least 10 ordered samples over at least 2 seconds.
Every sample must report zero linear/angular velocity and `estop: true` while
the graph still has exactly one final `cmd_vel` publisher.

Create a mode-0600 curl config containing only the operator/viewer authorization
header (never place the token on the command line), then capture the server
states. The body template identifies the fields copied from these raw files:

```bash
install -d -m 0700 "$HOME/.config/rosy"
install -m 0600 /dev/null "$HOME/.config/rosy/viewer.curl"
${EDITOR:-vi} "$HOME/.config/rosy/viewer.curl"  # header = "Authorization: Bearer ..."
for n in 01 02 03 04 05 06 07 08 09 10; do
  curl --config "$HOME/.config/rosy/viewer.curl" --fail-with-body --silent --show-error \
    http://127.0.0.1:8080/api/v1/robot/state \
    >"$EVIDENCE/G3-state-${n}.json" || exit 1
  sleep 0.25
done
```

Fill `$EVIDENCE/G3-stationary.json` from those ten states and the G2 publisher
count. G3 refuses the body alone; attach the G2 readback and all ten raw states:

```bash
python3 "$COMMISSION" prepare \
  --session "$SESSION" --body "$EVIDENCE/G3-stationary.json" \
  --record "$EVIDENCE/G3-record.json"
G3_ARGS=()
for path in "$EVIDENCE"/G3-state-*.json; do G3_ARGS+=(--evidence-file "$path"); done
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G3-record.json" \
  --evidence-file "$EVIDENCE/G3-stationary.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json" "${G3_ARGS[@]}"
```

If a sample moves, E-stop clears, the mode changes, or publisher count differs
from one: stop, preserve the raw output, and do not create a GO record.

### G4 - lifted-wheel motor and deadman

Hazardous gate: it is never auto-executed by `commission-pinky.py`.

```bash
install -m 0600 /dev/null "$HOME/.config/rosy/operator.curl"
install -m 0600 /dev/null "$HOME/.config/rosy/admin.curl"
${EDITOR:-vi} "$HOME/.config/rosy/operator.curl" # operator Authorization header
${EDITOR:-vi} "$HOME/.config/rosy/admin.curl"    # administrator Authorization header
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
sudo /opt/rosy/deploy/robot/verify/verify-motors.sh \
  | tee "$EVIDENCE/G4-motor-preflight.txt"
sudo ROSY_RUNTIME_MODE=motor /opt/rosy/deploy/robot/runtime-mode.sh up
```

Only after the torque-free preflight passes: confirm wheels lifted, physical cut
reachable, IDs 1 and 2 both respond, then switch deliberately to motor mode.
Run two deadman trials each for forward, reverse, clockwise, and
counter-clockwise. Each command release must reach final zero velocity within
0.65 s. Any timeout, unexpected direction, vibration, runaway, or missing ID is
an immediate E-stop and power-cut condition.

For each of the eight trials, use the authenticated dashboard's momentary
manual control at the lowest configured speed. Keep E-stop asserted while
selecting the direction; the safety operator explicitly releases it only for
the trial. Record `/rosy_01/odom` with ROS timestamps while the control is held.
The second terminal records the host stop time and stops only CORE to create a
real command-loss condition (replace `forward-1` for every trial):

```bash
timeout 30 docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml exec -T rosy-motor \
  ros2 topic echo --csv /rosy_01/odom \
  >"$EVIDENCE/G4-forward-1-odom.csv" &
printf '%s stop_core forward 1\n' "$(date +%s.%N)" \
  >>"$EVIDENCE/G4-deadman-events.txt"
docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml stop --timeout 0 rosy-core
# Wait for measured odometry to reach zero; immediately press E-stop if it does not.
sudo ROSY_RUNTIME_MODE=motor /opt/rosy/deploy/robot/runtime-mode.sh up
```

Reassert E-stop before restarting CORE and before changing direction. Compute
`stop_latency_s` from the recorded `stop_core` timestamp to the first
sustained-zero odometry timestamp. Do not type a passing value from visual
estimation alone.

After the trials:

```bash
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
sha256sum "$EVIDENCE"/G4-*-odom.csv >"$EVIDENCE/G4-odom-SHA256SUMS"
# Fill G4-evidence-manifest.json with all eight matching trial values and digests.
python3 "$COMMISSION" prepare \
  --session "$SESSION" --body "$EVIDENCE/G4-motor.json" \
  --record "$EVIDENCE/G4-record.json"
G4_ARGS=()
for path in "$EVIDENCE"/G4-*-odom.csv; do G4_ARGS+=(--evidence-file "$path"); done
[[ $((${#G4_ARGS[@]} / 2)) -eq 8 ]] || { echo 'need 8 G4 odom files' >&2; exit 1; }
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G4-record.json" \
  --evidence-file "$EVIDENCE/G4-motor.json" \
  --evidence-file "$EVIDENCE/G4-evidence-manifest.json" \
  --evidence-file "$EVIDENCE/G4-motor-preflight.txt" \
  --evidence-file "$EVIDENCE/G4-deadman-events.txt" \
  "${G4_ARGS[@]}"
```

### G5 - controlled hardware mapping/navigation

Lower the robot only in a cleared, supervised area. Keep E-stop asserted, start
hardware mode, then verify one `cmd_vel` publisher and fresh LiDAR before the
operator explicitly releases E-stop. Start with the lowest accepted physical
motion envelope; simulator speeds are not evidence.

Create separate mode-0600 operator and administrator curl configs as in G3.
The administrator credential is required only to release the software E-stop;
keep the physical power cut reachable. Then run:

```bash
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
sudo ROSY_RUNTIME_MODE=hardware ROSY_NAVIGATION_BACKEND=slam \
  /opt/rosy/deploy/robot/runtime-mode.sh up
timeout 10 docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml exec -T rosy-io \
  ros2 topic hz --window 50 /rosy_01/scan \
  | tee "$EVIDENCE/G5-lidar-rate.txt"
curl --config "$HOME/.config/rosy/admin.curl" --fail-with-body --silent --show-error \
  -X POST http://127.0.0.1:8080/api/v1/safety/release \
  | tee "$EVIDENCE/G5-estop-release.json"
curl --config "$HOME/.config/rosy/operator.curl" --fail-with-body --silent --show-error \
  -X POST http://127.0.0.1:8080/api/v1/slam/start \
  | tee "$EVIDENCE/G5-slam-start.json"
# In terminal A, record at most 15 minutes of raw physical telemetry. The
# commissioning directory is the only evidence write mount in rosy-io.
sudo timeout --signal=INT --kill-after=10s 900s \
  docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml exec -T rosy-io \
  ros2 bag record --storage mcap \
  --output "$EVIDENCE/G5-telemetry" \
  /rosy_01/scan /rosy_01/odom /rosy_01/cmd_vel /rosy_01/map /tf /tf_static
# In terminal B, drive only through the supervised dashboard while mapping.
# Stop terminal A with Ctrl-C after the route is covered; timeout remains the
# hard upper bound and allows rosbag2 to close metadata cleanly.
curl --config "$HOME/.config/rosy/operator.curl" --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' -d '{"name":"pinky_01_physical_001"}' \
  http://127.0.0.1:8080/api/v1/slam/save \
  | tee "$EVIDENCE/G5-map-save.json"
test -s /var/lib/rosy/maps/pinky_01_physical_001.yaml
test -s /var/lib/rosy/maps/pinky_01_physical_001.pgm
cp --no-clobber /var/lib/rosy/maps/pinky_01_physical_001.yaml \
  "$EVIDENCE/G5-map.yaml"
cp --no-clobber /var/lib/rosy/maps/pinky_01_physical_001.pgm \
  "$EVIDENCE/G5-map.pgm"
curl --config "$HOME/.config/rosy/operator.curl" --fail-with-body --silent --show-error \
  -X POST http://127.0.0.1:8080/api/v1/slam/stop \
  | tee "$EVIDENCE/G5-slam-stop.json"
curl --config "$HOME/.config/rosy/operator.curl" --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' -d '{"x":0.25,"y":0.0,"yaw":0.0}' \
  http://127.0.0.1:8080/api/v1/navigation/goal \
  | tee "$EVIDENCE/G5-goal.json"
```

Capture a fresh LiDAR rate, a fresh occupancy map ID, and one short Nav2 goal.
The goal must finish `SUCCEEDED`, with no observed collision. Finish at zero
velocity with E-stop asserted. `map_260905_update_v2` may be used as a route
reference only after coordinate/frame and clearance checks; the first physical
map gets a new evidence-bound ID.

Assert E-stop again before final capture. Fill the invalid-until-measured G5
body template, record, then take hardware down:

```bash
curl --config "$HOME/.config/rosy/viewer.curl" --fail-with-body --silent --show-error \
  -X POST http://127.0.0.1:8080/api/v1/safety/stop \
  | tee "$EVIDENCE/G5-estop-stop.json"
curl --config "$HOME/.config/rosy/viewer.curl" --fail-with-body --silent --show-error \
  http://127.0.0.1:8080/api/v1/robot/state >"$EVIDENCE/G5-final-state.json"
curl --config "$HOME/.config/rosy/viewer.curl" --fail-with-body --silent --show-error \
  http://127.0.0.1:8080/api/v1/navigation/state >"$EVIDENCE/G5-navigation-state.json"
MCAP_FILE="$(find "$EVIDENCE/G5-telemetry" -maxdepth 1 -type f -name '*.mcap' -print -quit)"
test -n "$MCAP_FILE" && test -s "$MCAP_FILE"
test -s "$EVIDENCE/G5-telemetry/metadata.yaml"
docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml exec -T rosy-io \
  ros2 bag info "$EVIDENCE/G5-telemetry" \
  | tee "$EVIDENCE/G5-telemetry-info.txt"
{
  cat "$EVIDENCE/G5-map-save.json"
  sha256sum "$EVIDENCE/G5-map.yaml" "$EVIDENCE/G5-map.pgm"
} >"$EVIDENCE/G5-map-artifacts.txt"
sha256sum "$MCAP_FILE" "$EVIDENCE/G5-telemetry/metadata.yaml" \
  "$EVIDENCE/G5-map.yaml" "$EVIDENCE/G5-map.pgm" \
  >"$EVIDENCE/G5-artifact-SHA256SUMS"
sha256sum "$EVIDENCE/G5-lidar-rate.txt" "$EVIDENCE/G5-telemetry-info.txt" \
  "$EVIDENCE/G5-map-artifacts.txt" \
  "$EVIDENCE/G5-navigation-state.json" "$EVIDENCE/G5-final-state.json" \
  >"$EVIDENCE/G5-role-SHA256SUMS"
# Fill G5-hardware.json with the measured duration/topics and the four artifact
# digests. Fill G5-evidence-manifest.json with five role digests and exact body
# role values. G5-telemetry-info.txt comes from `ros2 bag info G5-telemetry`;
# G5-map-artifacts.txt contains the map-save response and YAML/PGM sha256 lines.
python3 "$COMMISSION" prepare \
  --session "$SESSION" --body "$EVIDENCE/G5-hardware.json" \
  --record "$EVIDENCE/G5-record.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G5-record.json" \
  --evidence-file "$EVIDENCE/G5-hardware.json" \
  --evidence-file "$EVIDENCE/G5-evidence-manifest.json" \
  --evidence-file "$EVIDENCE/G5-lidar-rate.txt" \
  --evidence-file "$EVIDENCE/G5-final-state.json" \
  --evidence-file "$EVIDENCE/G5-navigation-state.json" \
  --evidence-file "$EVIDENCE/G5-map-save.json" \
  --evidence-file "$EVIDENCE/G5-goal.json" \
  --evidence-file "$MCAP_FILE" \
  --evidence-file "$EVIDENCE/G5-telemetry/metadata.yaml" \
  --evidence-file "$EVIDENCE/G5-map.yaml" \
  --evidence-file "$EVIDENCE/G5-map.pgm" \
  --evidence-file "$EVIDENCE/G5-telemetry-info.txt" \
  --evidence-file "$EVIDENCE/G5-map-artifacts.txt"
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
```

## 5. Calibration checklist

All four items remain `HOLD` until measured on this assembled Pinky Pro:

1. Measure the actual robot diameter/footprint at its widest rotating envelope,
   including protrusions and cable sweep. Validate by slow 360-degree rotation.
2. Measure command-to-stop distance repeatedly by direction and battery state.
   Tune adaptive speed from measured free clearance minus robot radius, stopping
   distance, localization uncertainty, and a safety margin; do not use a fixed
   maximum 8 cm clearance rule.
3. Validate camera intrinsics first. Then collect checkerboard and ArUco floor
   targets at multiple lateral positions and near/mid/far distances. The image
   homography coordinates must be converted from board-relative lateral-right
   into the declared robot frame before promotion.
4. Keep candidate and independent holdout captures separate. Record camera
   mount height/pitch, image size, focus, target size, lighting, RMSE by range,
   and raw image digests. Reject a homography that extrapolates beyond its
   validated floor region or fails physical tape-measure checks.

When clearance becomes insufficient, the planner may stop, reverse into its
already observed free corridor, rotate, and re-plan. It must include the full
measured footprint and swept path; it must not reverse into unknown occupancy.

## 6. Recovery and end-of-day evidence

On any unexplained state, collision, sensor staleness, command timeout, or loss
of supervision:

```bash
# Press/hold the physical E-stop first.
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
sudo systemctl disable --now rosy-runtime.service
sudo rosy-release status --json
```

Use `sudo rosy-release recover --json` for an interrupted transaction. Use
`sudo rosy-release rollback --json` only for an explicit previous signed
release. Do not clear a recovery hold until its cause is understood.

At the end, keep the session, every referenced raw evidence file, camera/LiDAR
captures, and map artifacts together. Verify all recorded SHA-256 values from a
second copy. A session ending before G5 is resumable and remains `HOLD`; never
edit it to look complete.
