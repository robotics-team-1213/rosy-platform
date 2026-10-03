# Rosy Traffic Signal Controller — Agent Contract

- **Document ID:** ROSY-SIGNAL-001
- **Status:** Reference implementation (G-S1 compile/bench·G-S3 Fleet client 전).
  참조 펌웨어는 `firmware/`에 있고 host source-contract만 통과했다
- **Related:** `docs/plans/2026-09-21-traffic-light-controller-research.md` (조사 보고서),
  `firmware/dock/README.md` (ROSY-DOCK-001 — 폴링 방향·자격증명 규칙의 선례),
  `docs/plans/2026-09-14-site-middleware-role-fabric-design.md` (D-59)

## 이 컨트롤러가 필요한 이유

접점 스위치로 켜지는 저가 LED 신호등을 관제(Fleet 콘솔)가 대신 켜고 끄게 하는 것이
목적이다. 그런데 신호등에는 다른 장비에 없는 성질이 하나 있다: **표시가 거짓말을
하면 현장 전체가 거짓말을 믿는다.** 관제가 죽은 뒤에도 마지막 명령(녹색)을 계속
보여 주는 신호등은, 아무것도 안 보여 주는 신호등보다 나쁘다.

그래서 이 펌웨어의 1차 임무는 제어가 아니라 **신뢰할 수 없음의 표시**다. 부팅,
감독자(토큰 유효 요청) 침묵, 펌웨어 재시작 — 신뢰가 깨지는 순간 전 기능 적색
점멸로 내려가고, 새 인증 명령이 올 때까지 거기서 움직이지 않는다.

## 방향: 감독자가 폴링하고 명령한다

**이 장치는 스스로 연결을 열지 않는다**(독과 동일). 관제 LAN 의 Fleet 서버가 폴링으로
상태를 모으고 POST 로 명령을 내린다. 신호등들 가운데 누가 녹색일지는 장치가 정하지
않는다 — 교행 순서를 판정하는 주체는 Fleet 이다(D-12). `cycle` 모드는 Fleet 이
명시적으로 넘겨주는 로컬 반복 패턴일 뿐이다.

## `GET /status`

```json
{
  "signal_id": "signal_1",
  "firmware": "1.0.0",
  "mode": "failsafe",
  "seq": 17,
  "lamps": { "red": true, "yellow": false, "green": false },
  "secs_since_contact": 11,
  "faults": ["supervisor_lost"]
}
```

| Field | Required | Meaning |
|---|---|---|
| `mode` | **yes** | `failsafe` / `manual` / `cycle` / `hold` / `all_red` / `flash_red` |
| `lamps` | **yes** | 지금 실제로 켜진 램프(명령값이 아니라 구동값) |
| `signal_id` | no | NVS `id`. 운영자가 두 기를 구별하기 위한 것 |
| `firmware` | no | 버전 |
| `seq` | no | 마지막으로 수용한 명령의 `seq` (부팅 후 0) |
| `secs_since_contact` | no | 마지막 토큰 유효 요청 이후 경과 초 |
| `faults` | no | 비어 있으면 정상 |

### 누락된 필수 필드는 오류다

`mode` 나 `lamps` 가 빠진 응답은 기본값을 채우지 않고 오류로 취급한다(독의
`load_present` 교훈과 동일). "모른다"와 "꺼져 있다"를 합치면 클라이언트의 재시도
전략이 무너진다.

### `lamps` 는 구동값이다

명령이 아니라 접점이 실제로 닫혀 있는 상태를 보고한다. 이것이 `seq`·명령 대조를
가능하게 한다 — 관제는 "내가 보낸 것"과 "실제 켜진 것"이 갈리는지 볼 수 있다.

## `POST /command`

**인증이 먼저다.** 모든 명령에는 `X-Rosy-Token` 헤더가 필요하고, NVS 의 토큰과
일치하지 않으면 `403` 이다. 토큰이 규정되지 않은 장치(빈 NVS)는 read-only 상태
조회만 하고 **어떤 명령도 수용하지 않는다** — 페일세이프에서 벗어날 길 자체가
없다. 이는 의도한 fail-closed 다.

폴링도 토큰과 함께 보내는 것이 규칙이다. 토큰 없는 GET 은 디버그용으로 읽히지만
하트비트로는 세지 않는다 — 익명 요청이 존재한다는 이유로 페일세이프를 눌러 주는
일이 없어야 한다.

```json
{
  "seq": 18,
  "mode": "manual",
  "lamps": { "red": false, "yellow": false, "green": true }
}
```

```json
{
  "seq": 19,
  "mode": "cycle",
  "cycle": { "green_ms": 5000, "yellow_ms": 2000, "red_ms": 5000 }
}
```

| mode | 뜻 | 함께 오는 필드 |
|---|---|---|
| `manual` | 램프 직접 지정 | `lamps` (필수) |
| `cycle` | 로컬 반복 녹→황→적 | `cycle` (생략 시 기본값) |
| `hold` | 지금 켜진 대로 고정 | — |
| `all_red` | 전 기능 적색 **점등** | — |
| `flash_red` | 전 기능 적색 **점멸** (수동 페일세이프) | — |

### `seq` 는 단조 증가한다

`seq` 가 마지막 수용값 이하면 `409 stale_seq` 로 거절한다. 관제의 재시도·지연
재전송이 옛 명령을 되살리지 못게 하는 최소 장치다. `seq` 는 재부팅에서 0 으로
돌아가는데, 부팅 상태가 페일세이프이고 Fleet 은 `failsafe` 를 보면 마지막 의도를
다시 내려보내는 것이 클라이언트의 책임이므로(아래 §클라이언트) 재생 위험이
커맨드 경로에 스며들지 않는다.

### 충돌 가드: 적+녹은 없다

`manual` 에서 `red` 와 `green` 이 함께 오면 `400 conflict` 로 거절한다. 도로용
제어기 표준(EN 12675 계열)의 결함 분류에서 최악의 클래스를 몇 줄의 가드로 옮긴
것이다. `yellow` 는 단독 또는 `red` 와 함께 허용한다(적황 동시 표시는 실제
신호 체계에 있다).

### cycle 타이밍

`green_ms`, `yellow_ms`, `red_ms` 는 각각 0 보다 커야 하고 합이 1 시간 이하여야
한다. 초과하면 `400 bad_cycle`. 기본값은 5s/2s/5s. 서로 다른 신호기 사이의
단계 맞춤(상반 측 녹색 금지 등)은 이 장치의 일이 아니다 — **여러 신호기의
순서는 Fleet 이 정한다**(D-12). 한 기 안의 cycle 은 시연·벤치용 반복 패턴이다.

## 하트비트와 페일세이프

- 하트비트는 **토큰이 유효한 요청**(GET 폴링 또는 POST)이다.
- 토큰 유효 요청이 `HEARTBEAT_TIMEOUT_MS`(10 s — 2 s 폴링 5회 분) 동안 없으면
  장치는 `mode=failsafe`, `faults=["supervisor_lost"]` 로 내려간다. 전 기능
  적색 점멸.
- **부팅 직후부터 페일세이프다.** 첫 유효 명령 전까지 어떤 것도 점등되지 않는다
  는 보장 대신, 전 기능 적색 점멸이 보장된다 — "장치가 살아 있는지"가 밖에서
  보인다.
- **펌웨어 재시작도 페일세이프다.** 마지막 명령은 NVS 에 저장하지 않는다(의도한
  선택). 오래된 명령이 혼자 되살아나는 경로를 원천 차단한다. 재부팅 후 관제가
  의도를 다시 내려보내는 것은 클라이언트의 몫이다.

### `all_red` 과 `failsafe` 는 다른 말이다

- `all_red` (점등): **명령된, 건강한** 전체 정지. Fleet 의 e-stop scatter 가
  내리는 것이다.
- `failsafe` (점멸): **컨트롤러가 신뢰를 잃었다**는 표시. 도로 규칙에서
  점멸이 "신호기 고장 — 전 방향 일시정지"를 뜻하는 것과 같은 자리다.

둘을 합치면 관제 화면이 "정지시켰다"와 "장비가 말을 안 듣는다"를 구별할 수
없게 된다.

## 클라이언트(Fleet 서버, 향후)의 책임

1. 폴링에도 토큰을 보낸다. 안 보내면 장치는 10 s 후 페일세이프로 간다 — 그것이
   정상 동작이다.
2. `mode=failsafe` 를 보면 마지막 의도를 `seq` 를 올려 재명령한다.
3. 자신이 보낸 마지막 명령과 `/status` 의 `mode`·`lamps` 를 대조해 불일치가
   계속되면 faults 로 UI 에 드러낸다.
4. 신호등 보고만으로 로봇 쪽 안전 동작을 억제하는 경로를 만들지 않는다(독의
   `charging: true` 단독 불신 원칙과 동일).

## 전기

- **채널은 active-HIGH** 로 구동한다: 핀 HIGH 동안 릴레이 접점이 닫힌다.
- 릴레이 모듈 입력은 **바이어스 저항**으로 고정해야 한다 — ESP32 부팅 중 핀이
  Hi-Z 로 떠 있는 동안 입력이 떠서 접점이 닫히는 일이 없어야 한다. 저가
  low-level-trigger 모듈은 3.3V 구동 불안정 사례가 많아, 조달 시 3.3V 호환을
  확인한다(조사 보고서 §4 참고).
- 신호등은 **DC 12/24V 제품을 권장**한다. AC 85–265V 제품은 메인스 절연(인클로저,
  퓨즈, 크리피지) 설계가 따로 필요하다.
- 한 컨트롤러 = 하나의 논리 신호기다. 앞뒤로 같이 보이는 병설 기둥은 같은 색
  배선을 한 채널에 묶는다. 상반 방향 신호기는 **별도 컨트롤러**로 두고 Fleet 이
  함께 조율한다. 채널 2개(`PIN_SPARE_A/B`)는 화살표·보행자 확장용 예비다.

## 규정(프로비저닝)

자격증명은 소스에 박히지 않는다(시험이 빌드를 막는다). NVS 가 비어 있을 때만
시리얼로 받는다:

```
[rosy-signal] NVS empty — provision now, end with 'done':
  wifi <ssid> <key>
  token <value>
  id <signal_id>
  done
```

저장 후 재시작한다. 이후 변경은 NVS 소거(re-flash)로만 — 네트워크에서 토큰을
바꾸는 통로를 열어 두지 않는다. 관제 토큰은 `robots.yaml` 의 토큰 패턴(D-30)과
같이 운영자가 발급·보관한다.

## 검증

```bash
python -m pytest test/test_signal_contract.py -q
```

현재 host source-contract 14건은 README 예시, route·mode, fail-safe, 인증,
단조 `seq`, 자격증명 부재, helper 정의와 Wi-Fi 입력 분리를 고정한다. 이 결과는
Arduino compile이나 ESP32 bench가 아니다. G-S3 Fleet client가 생기면 독의
`test_dock_contract.py`처럼 클라이언트 파서도 함께 대조해야 한다.
