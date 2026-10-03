# ROSY Host Agent 계약 (전송·인증·명령)

- **Document ID:** ROSY-HOSTAGENT-001
- **Status:** Contract accepted; decision layer implemented (`deploy/robot/pinky_pro/release/host_agent.py`),
  transport and privileged execution implemented (`host_agent_server.py`), on-device
  verification pending WP-7
- **Related:** `docs/plans/2026-09-01-rosy-os-v1-image-release-design.md` §4.4/§10,
  ADR D-22, `deploy/robot/pinky_pro/compose.yaml`, `test/test_release_boundary_guards.py`

## 1. 왜 별도 프로세스인가

CORE는 로봇 API이자 명령 경계다. 네트워크 프로파일을 바꾸고, 릴리스를 활성화하고,
장비를 재부팅하는 일은 호스트 권한을 요구하는데, 그 권한을 CORE에 주면 **인터넷에
노출된 HTTP 표면과 호스트 root가 같은 프로세스 안에 들어온다.** ADR D-22와 설계
§2.13이 이를 금지한다.

그래서 호스트 권한이 필요한 동작은 최소권한 별도 프로세스인 Host Agent가 갖고,
CORE는 그것에 **요청만** 한다. Host Agent는 임의 셸을 제공하지 않는다.

이 문서는 구현 전에 확정해야 하는 세 가지를 정한다: 전송 방식, 인증 방법,
요청이 흐르는 경로.

## 2. 전송: unix domain socket

**결정: `/run/rosy/host-agent.sock` 위의 unix domain socket. 로컬 HTTP 포트는
쓰지 않는다.**

로컬 HTTP를 배제한 이유:

- CORE 컨테이너는 `network_mode: host`로 동작한다. Host Agent가 TCP 포트를 열면
  `127.0.0.1`에 바인딩하더라도 **호스트의 모든 프로세스**가 접근할 수 있고,
  바인딩을 한 번 잘못하면 사업장 WLAN 전체에 노출된다. 릴리스 활성화와 재부팅
  권한을 가진 엔드포인트에 그런 실수 여지를 남길 이유가 없다.
- 소켓은 파일시스템 객체다. 소유자·모드로 접근을 걸 수 있고, 커널이 연결한
  상대의 uid/gid/pid를 알려준다(§3). TCP에는 그에 상응하는 것이 없어 토큰을
  따로 만들고, 배포하고, 회전시켜야 한다.
- 포트가 없으면 방화벽 규칙도, TLS도, 인증서 수명도 없다.

소켓 파일은 `/run`에 둔다. tmpfs이므로 재부팅 시 사라지고 stale 소켓이 남지 않는다.

### 2.1 컨테이너로 전달

```yaml
rosy-core:
  volumes:
    - "/run/rosy/host-agent.sock:/run/rosy/host-agent.sock:ro"
```

**주의: 소켓에 붙은 `:ro`는 보호 장치가 아니다.** 읽기 전용 바인드 마운트는
소켓 *inode*의 교체를 막을 뿐 그 소켓으로 연결해 명령을 보내는 것을 막지 못한다.
`docker.sock:ro`가 Docker API 쓰기를 전혀 막지 못하는 것과 같은 이유이고,
`test_core_never_receives_a_container_runtime_socket`이 `:ro` 여부와 무관하게
컨테이너 런타임 소켓을 거부하는 이유이기도 하다.

Host Agent 소켓의 보호는 `:ro`가 아니라 **소켓 자체의 소유권·모드와 peer
credential 검사**에서 나온다(§3).

## 3. 인증: peer credential + 소켓 권한

**결정: `SO_PEERCRED`로 확인한 커널 제공 uid를 1차 인증으로 쓴다. 공유 토큰은
쓰지 않는다.**

```
/run/rosy/host-agent.sock   root:rosy   0660
```

- Host Agent는 root로 동작하며 소켓을 생성한다.
- 그룹 `rosy`(= compose의 `ROSY_GID`, 기본 1000)만 연결할 수 있다.
- 연결마다 `SO_PEERCRED`로 상대 uid/gid/pid를 읽고, **`ROSY_UID`가 아니면 즉시
  끊는다.** 이 값은 커널이 채우므로 클라이언트가 위조할 수 없다.

토큰을 쓰지 않는 이유: 토큰은 어딘가에 저장되어야 하고, 그 저장 위치는 이미지나
설정 파일이 되며, 설계 §2.7이 금지하는 "이미지에 담긴 공유 비밀"로 되돌아간다.
커널이 이미 정확한 답을 무료로 주는데 비밀을 새로 만들 이유가 없다.

**이 검사가 실제로 증명하는 것은 "uid가 `ROSY_UID`인 어떤 프로세스"이지 "CORE"가
아니다.** compose는 user namespace 재매핑을 쓰지 않으므로 컨테이너의 uid 1000은
호스트의 uid 1000과 같은 사용자다. Raspberry Pi OS Lite에서 uid 1000은 보통 사람이
로그인하는 기본 계정이다. 그대로 두면 그 계정의 SSH 세션이 `release.install`,
`network.apply_profile`, `system.reboot`을 그대로 호출할 수 있다.

따라서 **CORE에 로그인 계정과 구분되는 전용 시스템 uid를 부여하는 것이 이 인증의
전제 조건이다.** 이미지 빌드(WP-6)에서 `rosy` 시스템 사용자를 만들고
`ROSY_UID`/`ROSY_GID`를 거기에 맞춘다. 그전까지 이 계약의 인증 강도는 "로컬 로그인
사용자와 동등"이며, 그 이상으로 취급해서는 안 된다.

사용자 신원은 그 위의 별개 층이다. **어떤 사람이 요청했는지는 CORE가 판단해 요청에
실어 보낸다**(§5).

## 4. 요청 경로

```
브라우저 (대시보드)
   │  HTTPS/HTTP + 세션, 역할 검사
   ▼
CORE FastAPI  :8080          ← 컨테이너, uid 1000, cap_drop ALL, read_only
   │  role 검사 · 재확인 토큰 검증 · idempotency key 부여 · 감사 이벤트 발행
   │  typed JSON, 줄 단위 프레이밍
   ▼
/run/rosy/host-agent.sock    ← SO_PEERCRED = ROSY_UID 검사
   │
   ▼
Host Agent (root)            ← allowlist 실행, 감사 로그, idempotency 중복 제거
   │
   ▼
nmcli · systemctl · rosy-release · reboot
```

CORE는 셸을 호출하지 않는다. 설계 §10이 요구하는 대로 대시보드도 셸이 아니라
CORE의 typed API를 부른다.

## 5. 요청·응답 형식

한 줄에 하나의 JSON 문서. 요청과 응답은 `request_id`로 짝지어진다.

```json
{
  "schema_version": 1,
  "request_id": "01J8Z...",
  "idempotency_key": "01J8Z...",
  "command": "release.install",
  "actor": {"user_id": "operator-01", "role": "administrator"},
  "confirmed": true,
  "params": {"release_id": "2026.09.05-002"}
}
```

```json
{
  "schema_version": 1,
  "request_id": "01J8Z...",
  "ok": false,
  "code": "RELEASE_SIGNATURE_INVALID",
  "detail": "signature does not verify against the trusted release key",
  "recovery": "번들을 다시 받거나 서명 환경을 확인하십시오."
}
```

- `code`는 안정 식별자다. `deploy/robot/pinky_pro/release/manifest.py`와 `signing.py`의 Rejection
  코드를 그대로 쓴다. 설계 §11이 집계 숫자가 아니라 오류 코드와 복구 행동을
  요구하기 때문이다.
- `actor`는 CORE가 채운다. Host Agent는 이를 **감사 기록용으로만** 쓰고 권한
  판단의 근거로 삼지 않는다 — 권한은 §3의 peer credential과 §6의 allowlist다.
- `confirmed`는 파괴적 명령의 재확인 여부다. `false`면 Host Agent가 거부한다.
- `idempotency_key`가 같은 요청이 재도달하면 **다시 실행하지 않고 최초 결과를
  반환한다.** 네트워크가 끊긴 대시보드의 재시도가 두 번째 재부팅이 되어서는 안 된다.
- `network.status`와 `release.status`의 정상 응답만 `observed_at`(UTC ISO-8601)을
  추가한다. Host Agent가 각각의 동기 조회를 끝낸 직후 찍는 원본 시각이며 감사 시각이나
  CORE 수신 시각이 아니다. 부분 nmcli 조회 실패, 릴리스 상태 JSON 파싱·필수 필드
  실패는 정상 응답으로 바꾸지 않는다. 다른 명령과 거부 응답에는 이 필드를 붙이지 않는다.
- CORE는 이 원본 시각과 수신 시각의 차이를 검증해 `/host/network`와 `/host/release`에
  `evidence`를 더한다. 시각 누락·파싱 실패·미래 시각은 `unavailable`, 15초 초과는
  `delayed`, 소켓 미연결·타임아웃은 `disconnected`이다. 정상 15초 이내만 `fresh`다.
  이는 **상태 조회 시각**이지 네트워크 전환이나 릴리스 설치가 물리적으로 적용됐다는
  확인이 아니다.

## 6. Allowlist

Host Agent는 아래 명령만 안다. 임의 명령, 임의 경로, 임의 인자를 받지 않는다.

| command | 파라미터 | 역할 | 재확인 |
|---|---|---|---|
| `network.status` | — | viewer | 불필요 |
| `lane_perception.status` | — | viewer | 불필요 |
| `lane_perception.set` | `paint_source`: threshold / denoise / learned | administrator | 불필요 |
| `network.apply_profile` | `profile_id` (등록된 프로파일 id만) | administrator | 필요 |
| `network.set_mode` | `mode` (`SITE_STA` 또는 `RELAY_AP_STA`) | administrator | 필요 |
| `network.connect` | `ssid`, `psk` (PSK는 감사·응답에 남기지 않음) | administrator | 필요 |
| `release.status` | — | viewer | 불필요 |
| `release.install` | `release_id` (staging에 존재하는 것만) | administrator | 필요 |
| `release.rollback` | — | administrator | 필요 |
| `release.clear_hold` | — | administrator | 필요 |
| `service.status` | `unit` (고정 목록 내에서만) | viewer | 불필요 |
| `system.reboot` | — | administrator | 필요 |

**`system.shutdown`은 이 표에 없고, 앞으로도 추가하지 않는다.** 저배터리 셧다운은
사람이 없는 상태에서 발화하므로 인증할 administrator도 확인해 줄 operator도 없다.
그 경로를 여기에 뚫으면 이 문서 전체의 근거인 "무인·무확인 실행을 거부한다"가
무너진다. 대신 CORE가 파일에 관찰을 기록하고 호스트 유닛이 스스로 판단하는
일방향 센티넬을 쓴다 — 명령 채널이 아니므로 이 계약의 대상이 아니다. 근거와
인터록은 ADR D-27, 설계는
`docs/plans/2026-09-02-battery-integrity-low-battery-alert-design.md`에 있다.

규칙:

- `profile_id`, `release_id`, `unit`은 **열거된 값과 대조**한다. 문자열을 그대로
  명령줄에 넘기지 않는다.
- 알 수 없는 `command`는 실행하지 않고 `HOST_AGENT_COMMAND_UNKNOWN`으로 거부한다.
  비슷한 이름으로 추측하지 않는다.
- 파일 경로를 받는 명령은 없다. 경로가 필요하면 Host Agent가 `Layout`에서 스스로
  구성한다.
- 셸을 경유하지 않는다. `subprocess`에 인자 리스트로 직접 넘긴다.
- 장비가 `RECOVERY HOLD`이면 `release.install`은 `RECOVERY_HELD`로 거부한다.
  홀드 해제(`release.clear_hold`)는 별도의 의도적 행위다. 홀드를 통과해
  설치하면 성공을 보고한 뒤 다음 부팅이 그것을 뒤집는다 — 현장에서 복구 중인
  작업자에게 가장 나쁜 형태의 거짓말이다.

차선 인식 설정은 `/etc/rosy/line_observer_overrides.yaml`의 기존 지면 기하를
보존하고 `paint_source`만 선택한다. `learned`는 고정
`/var/lib/rosy/models/shadow` 포인터의 lane_seg manifest·파일 해시·신뢰 서명을
확인하고, CORE의 `/run/rosy/status-inputs.json`을 다시 읽어 3초 이내 fresh 정지,
IDLE, line-follow OFF, navigation·docking·swarm·mission·calibration 비활성을
확인한다. 속도나 상태가 없으면 거부한다. 파일을 원자 교체한 뒤
`rosy-camera.service`만 재시작하며 실패하면 원래 설정과 런타임을 복구한다.
`applied: true`는 설정 교체와 서비스 active 확인이며 실제 추론 성공이나
주행 허가가 아니다. Host Agent의 `applied_paint_source`는 live 증거를 읽지 않으므로
null이다. CORE는 별도로 실제 `line/keep_debug`의 validated `paint_source_used`를
읽어 로컬 monotonic 수신 후 2초 이내에만 이 필드를 채운다. 값은 threshold /
denoise / learned / denoise_fallback이며 `applied_source_age_s`가 수신 나이다.
`applied_model_revision`은 실제 learned mask producer가 제공한 revision만
표시한다. 설정 source·모델 revision 불일치, malformed packet, 카메라 clock reset,
stale 수신 또는 camera 재시작 전 증거는 null이다. 이는 주행 정책에 입력하지 않는다.

native `rosy-host-agent.service`는 이 표 중 `lane_perception.status/set`만
활성화한다. peer는 `/etc/passwd`의 전용 `rosy-core` UID이며 소켓 그룹도
`rosy-core`이다. 다른 Host 명령은 해당 runtime에서 COMMAND_UNKNOWN으로
거부한다. 설치 helper는 release의 native 폴더에 함께 실려 저장소 없이
실행되며 CORE가 1초마다 쓰는 실제 status 입력을 소비한다.
CORE는 Host 변경 요청 동안 실제 ModeMachine의 IDLE 예약을 유지한다.
같은 관리자도 주행 모드·teleop·navigation·line-follow를 시작할 수 없고,
Host 응답 또는 실패 뒤 finally에서 예약을 해제한다. IDLE 전환과 E-stop은
항상 가능하다. 이 예약은 보정 session을 만들거나 주행 상태를 꾸미지 않는다.
보정 busy_check와 session 생성, perception의 보정 부재 확인과 IDLE 예약은
같은 admission lock 아래에서 실행한다. 보정 검사와 session 생성 사이에
설정 요청이 끼어들어 통과할 수 없다.

## 7. Host Agent가 갖지 않는 것

- CORE 컨테이너에 Docker socket이나 host root를 전달하지 않는다. 이 제약은
  `test_core_never_receives_a_container_runtime_socket`,
  `test_core_never_receives_host_root`,
  `test_core_writes_to_nothing_on_the_host_but_its_own_data`,
  `test_core_joins_no_extra_host_groups`가 compose를 파싱해 검사한다. 이 검사들은
  `${VAR:-기본값}`을 먼저 전개한 뒤 경로를 비교하며, 소켓은 상위 디렉터리를 통해
  전달되는 경우까지 본다 — 문자열 부분 일치로 검사하던 초기 판본은 `:ro`를 붙이거나
  `/var/run`을 통째로 마운트하는 것을 놓쳤다.
- Host Agent는 `/cmd_vel`을 비롯한 어떤 이동 명령 경로도 갖지 않는다. 모터는
  ROS 2 어댑터의 영역이고 Host Agent는 거기에 닿지 않는다.
- Host Agent는 E-stop 해제나 hardware 모드 승격을 수행하지 않는다. 설계 §10이
  정한 대로 별도 현장 안전 절차다.
- `release.install`과 `release.rollback`은 언제나 `core`로 끝난다. Host Agent에
  motor/hardware로 기동하라고 요청하는 명령은 존재하지 않으며, updater의 rollback은
  이전 activation record의 mode를 그대로 되살리지 않고 `core`로 강제한다
  (`updater._previous_record`). 모터 모드로 승인된 로봇이 업데이트에 실패했을 때
  바퀴가 살아난 채 돌아오지 않도록 하기 위한 것이다.

## 8. 감사

모든 명령은 성공·실패와 무관하게 기록한다: 시각, `request_id`,
`idempotency_key`, `command`, `actor`, 결과 `code`. 기록에서 제외하는 것은
설계 §11이 정한 대로 토큰, Wi-Fi 비밀번호, 개인키, 전체 설정 파일이다.

`network.apply_profile`은 SSID를 남기되 PSK는 남기지 않는다. `network.connect`는
SSID를 남기고 PSK는 요청에서만 쓰며 감사 기록·응답 `data`에 넣지 않는다.

## 9. 구현 상태

### 9.1 확정되어 구현된 것

| 항목 | 결정 | 구현 |
|---|---|---|
| 프레이밍 | 줄 단위 JSON. 길이 프리픽스는 쓰지 않는다 — 요청이 한 줄이고 상한이 있으면 프레이밍은 문제가 되지 않는다 | `HostAgent.handle_line` |
| 요청 크기 상한 | 64 KiB. 초과하면 읽지 않고 `HOST_AGENT_REQUEST_TOO_LARGE` | `MAX_REQUEST_BYTES` |
| idempotency 보존 | 최근 256건, 삽입 순서. **성공만 기억한다** | `_Idempotency` |
| 연결당 요청 | 1건. 응답 후 닫는다 | `serve_forever` |

idempotency가 성공만 기억하는 것이 중요하다. 실행 중 실패(끊긴 `nmcli`, 바쁜
unit)를 기억하면 같은 key로 재시도할 때마다 그 실패가 재생되어, 대시보드로는
영영 고칠 수 없는 장비가 된다. 재시도는 다시 시도하겠다는 뜻이다.

### 9.2 아직 열려 있는 것

- 장시간 명령(`release.install`)의 진행률 보고 — 스트리밍 응답인지 폴링인지.
  현재는 완료 후 한 번 응답한다.
- Host Agent 자체의 재시작·감시 전략 (systemd `Restart=` 정책)
- `SubprocessCommands`가 부르는 `rosy-release` CLI 자체 (§14의 목표 인터페이스,
  WP-6에서 구현)

### 9.3 검증 상태

거부 판정 전체 — allowlist, 역할, 재확인, 열거 대조, 임의 파라미터 거부, 홀드 중
install 거부, idempotency, 요청 크기·스키마, 감사 redaction — 은
`test/test_host_agent.py`에서 소켓 없이 검증된다. 각 가드를 하나씩 무력화해
스위트가 잡는지 확인했다(14/14).

소켓 자체(`SO_PEERCRED`, 소유권·모드)와 실제 `nmcli`/`systemctl` 실행은 실기에서
확인한다 — `pi5-acceptance-checklist.md`. 여기서 검증된 것은 uid 판정 로직과
명령이 셸 문자열이 아니라 인자 리스트로 만들어진다는 것뿐이다.

전송과 인증(§2, §3)은 확정된 것으로 취급한다. 구현 중 이를 바꾸려면 이 문서를
함께 고친다.


## 2026-09-08 delivery integration status

`rosy-release` is now a separate root maintenance CLI for signed staging, installation, rollback and boot recovery. The systemd timer only checks/downloads/stages. This does not implement or change the socket API above: wiring the host-agent server or dashboard to this CLI requires a separate authorization/integration change. See `docs/deployment/github-updates.md`.
