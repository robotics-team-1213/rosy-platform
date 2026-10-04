## D-443 `rosy.site-device/1` — 사이트 장치(신호등·도크, 나중에 컨베이어·문·PLC)는 한 계약을 쓰고, 장치마다 로컬 failsafe를 진다

**Status:** Accepted (2026-10-04, 사용자 수용; D-429 후속 2). 번호 메모: 초안은 D-440이었으나 D-440·D-441·D-439는 다른 브랜치가 쓰고 있고 D-442는 Motion Intent ADR이 쓴다. [D-429](D-429-five-concerns-control-port-and-site-devices.md) §4가 예고한 사이트 장치 계약의 초안이다. 이번 변경은 문서뿐이다. 코드·펌웨어·wire·매니페스트·폴더 이전·실기 gate 변화는 없다. 지금 신호등과 도크의 HTTP API는 **wire를 바꾸지 않고** 이 계약의 profile로 읽힌다. 독립 리뷰와 사용자 답변(아래 열린 질문) 뒤 Accepted로 올린다. **리뷰 1차(2026-10-04, REVISE) 반영:** 재단언 한계(B1), seq 재동기화와 안전 방향 재시도(S1), 측정 효과 열거와 admission 술어(S2·S3), 오프라인 행(S4), ER2 fence(S5), PLC 어댑터 API 모양(S6), 펌웨어 결함 기록(S7). **사용자 결정(2026-10-04):** Q5 Fleet 상시 감독·수동 점등은 운영자가 있을 때만·stale 의도 재전송 금지, Q8 `charging.py` safety 태그(별도 D-430 매니페스트 변경), Q9 `integrations/fieldbus/modbus`, 나머지 질문은 권고안 수용. 현재 코드 결함은 이전 직후 첫 안전 작업으로 고친다(후속).

### Context

D-429 §4는 로봇과 사이트 장치가 같이 지는 공통 바탕(식별·등록, measured와 claimed를 가른 상태, heartbeat, semantic 명령만, failsafe 의무)을 정했다. 그리고 사이트 장치 쪽은 `rosy.site-device/1`이라는 이름만 두고 내용을 후속 2로 미뤘다. [D-430](D-430-safety-as-a-separate-concern.md)은 안전 체인의 층 2를 "사이트 장치 로컬 failsafe"로 두고, 신호등은 적색 점멸, 도크는 0 V를 fail-closed 상태로 정했다. 물리 E-stop과 safety PLC는 ROSY와 독립이다(D-430 §3 불변식 5).

지금 저장소에는 사이트 장치가 둘 있고, 같은 개념을 서로 다른 모양으로 갖고 있다. 2026-10-04 `origin/main` `0b277ae38` 기준이다.

| 항목 | 신호등 (ROSY-SIGNAL-001) | 도크 (ROSY-DOCK-001) |
|---|---|---|
| 펌웨어 | `firmware/signal/firmware/rosy_signal/rosy_signal.ino` | `firmware/dock/firmware/rosy_dock/rosy_dock.ino` |
| 계약 문서 | `firmware/signal/README.md` | `firmware/dock/README.md` |
| 경로 | `GET /status`, `POST /command` (`rosy_signal.ino:395-396`) | `GET /status`만 (`rosy_dock.ino:195`) |
| 식별 | `signal_id`, `firmware` (선택 필드) | `dock_id`, `firmware` (선택 필드) |
| 필수 상태 | `mode`, `lamps` | `load_present`, `charging` |
| 자격증명 | `X-Rosy-Token`. NVS가 비면 어떤 명령도 받지 않는다(`rosy_signal.ino:169-176`). 토큰 없는 GET은 heartbeat가 아니다 | 없다. 읽기 전용 평문 HTTP. 명령면이 생기면 다시 판단한다(도크 README "Network") |
| heartbeat | 토큰 유효 요청. `HEARTBEAT_TIMEOUT_MS = 10000`(`rosy_signal.ino:33`) | 없다. 감독 링크가 없다(D-429 §2) |
| 명령 순서 | `seq` 단조 증가, 이하면 `409 stale_seq` + `last_seq`(`rosy_signal.ino:241-247`) | 해당 없음 |
| 로컬 failsafe | 부팅·감독 상실 → `mode=failsafe`, 전 기능 적색 점멸 500 ms(`:34`, `:66`, `:114-118`, `:412-414`). 마지막 명령을 NVS에 저장하지 않는다 | 부팅 0 V(`:172`), 리밋스위치 미눌림 → 0 V(300 ms debounce, `:37`, `:124`), 과전류 3.0 A·과전압 8.7 V 폴트 → 0 V, 부하 제거까지 래치(`:33-35`, `:63-65`, `:116-119`) |
| 감독자/소비자 | Fleet `src/site/fleet/fleet/server/signals.py` (`POLL_INTERVAL_S = 2.0`, `HTTP_TIMEOUT_S = 1.5`, `REASSERT_LIMIT = 1`, `:31-33`) | 로봇 `core_features/docking/agent.py` (`DockAgent.poll`, timeout 1.0 s, `core_common.device_poll.poll_json`, `:73-107`) |
| 독립 측정 | 관측 서비스 `GET /observed`(D-163, `firmware/signal/observer/observer.py`) | 로봇 자기 팩 전압(`charging.py` `ChargingConfirmation`, 창 10 s) |

공통점은 이미 많다. 둘 다 장치가 연결을 열지 않고(감독자·소비자가 폴링), 필수 필드가 빠지면 기본값을 채우지 않고 오류로 다루며(`signals.py:70-79`, `agent.py`의 `_REQUIRED`), 자격증명은 시리얼 프로비저닝으로 NVS에만 둔다. 다른 점도 분명하다. 신호등의 `lamps`는 "구동값"(릴레이 접점 상태)이고, D-337 §1은 그것을 로봇이 믿으면 안 되는 **주장**으로 본다. 도크의 `charging`은 장치가 자기 전류 측정으로 내린 판정이고, 로봇은 그것을 단독으로 믿지 않는다(도크 README "The robot does not trust this endpoint alone", `charging.py:76-90`).

빈칸은 셋이다.

1. **공통 타입이 없다.** Fleet은 `SignalStatus`(`signals.py:50-68`), 로봇은 `DockStatus`(`agent.py`)를 따로 갖는다. 컨베이어·문·PLC가 오면 세 번째·네 번째 모양이 생긴다.
2. **"보냈다"와 "됐다"의 구분이 코드에만 있다.** 신호등 명령의 200 응답은 수용(ack)일 뿐이다. 실제 점등은 `/status`의 `lamps`(장치 주장)와 관측 `/observed`(측정)로 따로 확인한다(`signals.py:97-146` `cross_check`). 이 구분이 계약 문장으로 정해져 있지 않다.
3. **새 kind의 failsafe·timeout·소유자를 정하는 규칙이 없다.** D-429 §4는 예시(문은 마지막 안전 상태, 컨베이어는 정지)만 두었다.

외부 패턴(참고만, **미확인** — 2026-10-04에 원문을 다시 대조하지 않았다):

- Open-RMF의 door/lift adapter는 중앙 조정자가 요청(requested mode)을 내고 장치 adapter가 현재 상태(current mode)를 따로 보고하는 구조로 알려져 있다. 요청과 관측 상태를 가르는 점이 이 ADR의 ack/effect 구분과 같다. D-429 Context가 인용한 https://osrf.github.io/ros2multirobotbook/integration.html 이 출발점이다.
- 산업 현장의 Modbus/PLC 연동은 상위 시스템이 레지스터를 직접 다루지 않고, 통합자가 정한 태그·레지스터 맵 위에 "start/stop/reset" 같은 semantic 명령을 얹는 wrapper를 흔히 둔다. 안전 I/O는 safety PLC가 따로 소유한다. 일반 관행 서술이며 특정 표준 원문을 확인하지 않았다.

### Decision

#### 1. `rosy.site-device/1` 스키마

`rosy.site-device/1`은 **호스트 쪽 타입 계약**이다. 장치 wire는 kind별 **profile**이 정하고, profile codec이 wire를 이 타입으로 옮긴다. 지금 wire에는 스키마 이름이 실리지 않는다. 스키마 이름과 profile 이름은 감독자·소비자 설정(예: `signals.yaml`의 항목, 로봇 dock DB)과 D-354의 mDNS 서비스 이름(`_rosy-signal._tcp`, `_rosy-dock._tcp`)으로 정해진다.

##### 1.1 식별·등록 (`identity`)

| 필드 | 뜻 | 규칙 |
|---|---|---|
| `kind` | `signal`, `dock`, `conveyor`, `door` | 닫힌 열거. 새 kind는 ADR로 더한다 |
| `profile` | `signal/1`, `dock/1`, … | kind별 wire profile 버전 |
| `device_id` | 사이트 안에서 유일한 장치 id | 등록(설정 파일)이 정본이다. 장치가 보고하는 `signal_id`·`dock_id`는 대조용 **주장**이며, 등록값과 다르면 `identity_mismatch` 폴트로 본다 |
| `firmware` | 장치가 보고한 펌웨어 버전 | 선택. 없으면 `null`. 버전으로 동작을 바꾸지 않는다 |
| `endpoint` | base URL 또는 mDNS 인스턴스 | 등록값 |
| `credential_ref` | 자격증명의 **참조**(설정 키) | 값 자체는 타입·상태·로그·스냅샷에 싣지 않는다 |

자격증명 규칙(지금 신호등 계약을 일반화한다):

- **명령을 받는 kind는 장치별 자격증명이 필수다.** 지금 형식은 `X-Rosy-Token` 헤더다. 자격증명이 비어 있는 장치는 상태 조회만 하고 어떤 명령도 받지 않는다. 그래서 failsafe에서 나올 길이 없다(의도한 fail-closed, `rosy_signal.ino:169-176`).
- 자격증명은 소스에 넣지 않는다. 시리얼 프로비저닝으로 NVS에만 둔다. 네트워크로 바꾸는 경로는 열지 않는다. 바꾸려면 NVS를 지우고 다시 프로비저닝한다(신호등·도크 README). 소스 안 자격증명은 계약 시험이 막는다(`test_signal_contract.py::test_no_credentials_in_the_sources`, `test_dock_contract.py::test_no_credentials_in_the_firmware`).
- **heartbeat는 인증된 요청만이다.** 익명 요청은 디버그 읽기일 뿐 감독으로 세지 않는다.
- 읽기 전용 kind(지금 도크)는 자격증명이 없어도 된다. 명령면이 생기는 순간 이 규칙 전체를 진다(§2.4).

##### 1.2 상태 (`SiteDeviceStatus`)

| 필드 | 뜻 |
|---|---|
| `schema` | `"rosy.site-device/1"` |
| `identity` | §1.1 |
| `link` | 이번 읽기의 도달성. `ok`, `unreachable`, `timeout`, `bad_response`(`core_common.device_poll`의 4상태와 같다, D-353 §2). `read_at`(소비자 단조 시각) |
| `mode` | profile이 정한 장치 모드 열거. 모드가 없는 kind(도크)는 `null` |
| `claimed` | **장치가 자기 출력·판정에 대해 주장하는 값.** 구동 중인 접점, 장치가 내린 판정 |
| `measured` | **센서가 잰 값.** 장치 자신의 센서와 장치와 독립된 관측 소스를 `source` 태그로 구분한다(`device_sensor`, `independent_observer`) |
| `supervision` | `supervised`(bool), `secs_since_contact`(장치 보고, 선택), `timeout_s`(profile 상수) |
| `last_seq` | 장치가 마지막으로 수용한 명령 seq. 명령이 없는 kind는 `null` |
| `faults` | 문자열 목록. 비면 정상 |

규칙:

- **필수 필드가 빠지면 `link=bad_response`다.** 기본값을 채우지 않는다. "모른다"와 "꺼져 있다"를 합치지 않는다(신호등 README "누락된 필수 필드는 오류다", 도크 README "Missing required fields are an error").
- **`claimed`와 `measured`는 섞지 않는다(D-337).** 소비자가 진입·충전 같은 허가 판단에 쓸 수 있는 것은 `measured`뿐이고, 그것도 단독 허가가 아니다(D-337 §3, D-429 §2 "로봇의 소비"). `claimed`는 감독자의 대조(ack vs effect, §1.4)와 화면에 쓴다.
- **`link`가 `ok`가 아니어도 마지막 값은 남기되, 언제나 `link`와 나이(`read_at` 기준 경과)를 함께 싣는다. 그 값은 허가 판단(§1.4 admission 술어)에 절대 쓰지 않는다.** 화면은 오프라인 행을 "마지막으로 본 값, N초 전"으로 그린다. 지금 코드는 오프라인 행에 마지막 `mode`·`lamps`를 나이 없이 보여 준다(`signals.py:463-476`의 `_row`가 `status.as_row()`를 `online=false`와 함께 섞는다). 나이를 붙이는 일은 이행 (b2)의 필수 변경이다.

##### 1.3 semantic 명령 (`SiteDeviceCommand`)

| 필드 | 뜻 |
|---|---|
| `schema` | `"rosy.site-device/1"` |
| `device_id`, `kind` | 대상 |
| `verb` | profile이 정한 semantic 동사(아래 표). raw I/O(핀·코일·레지스터·릴레이 번호)는 동사도 인자도 될 수 없다(D-429 §4) |
| `args` | 동사별 인자. 단위가 있는 값만(예: `green_ms`) |
| `seq` | 장치별 단조 증가. 감독자가 채운다(`signals.py:311-329`) |
| `fence` | 명령을 낸 근거. 운영자 직접 명령은 actor와 그 시점의 정지 세대다. 감독자가 D-429 §3의 승인 후보를 **입력으로 삼아** 스스로 명령을 만들 때는 그 후보의 fence를 함께 기록한다(아래). 실행 직전에 다시 확인하고, 하나라도 다르면 내리지 않는다(stale, 재시도 없음) |

승인 후보에서 출발한 명령의 실행 직전 재확인은 D-429 §3 전부다. 후보는 장치 명령이 아니라 감독자 신호 순서·교통 로직의 입력일 뿐이다.

- **현재 점유 재확인:** 교차로 점유와 진입 grant를 다시 본다(D-429 §3 "승인의 효과"). 후보를 승인한 뒤 점유가 바뀌었으면 stale이다.
- **세대 재확인:** site/signal-group 세대 또는 장치 `last_seq`(D-429 §3 "fence 범위").
- **turn·stop 무효화:** 다른 제안과 같은 turn·stop 무효화를 받는다(D-357 §6, D-358 §4). 정지 세대가 올라갔거나 turn이 무효화됐으면 stale이다.
- **인터록 우선:** 운영자 승인은 Fleet 인터록(점유, grant, all_red·e-stop scatter, stop latch)을 넘지 않는다.
- stale이면 재시도하지 않고 운영자에게 사유를 보인다. "조건이 풀리면 실행되는" 대기 승인은 없다.

kind별 profile 동사:

| kind | 동사 | 인자 | 장치 로컬 failsafe | 감독 상실 timeout |
|---|---|---|---|---|
| `signal` | `cycle` | `green_ms`·`yellow_ms`·`red_ms`(각 > 0, 합 ≤ 1 h, 생략 시 5000·2000·5000) | 전 기능 적색 점멸(`mode=failsafe`, 500 ms 주기) | 10 s (`HEARTBEAT_TIMEOUT_MS`, 2 s 폴링 5회) |
| | `hold` | 없음 | 위와 같다 | 위와 같다 |
| | `all_red` | 없음. 명령된 건강한 전체 정지(점등) | 위와 같다 | 위와 같다 |
| | `failsafe` | 없음. 운영자가 명령하는 적색 점멸 | 위와 같다 | 위와 같다 |
| | `set_aspect` | `red`·`yellow`·`green` bool. 적+녹 동시 금지 | 위와 같다 | 위와 같다 |
| `dock` | 없음(읽기 전용) | 없음 | 0 V. 부팅 시, 리밋 미눌림 시, 폴트 시 | 없음. 감독 링크가 없고 인터록이 국소다. 명령이 생기면 §2.4 |
| `conveyor` (미래) | `start`, `stop`, `index` | `index`는 정수 칸 수. 속도는 profile의 이름 붙은 등급(`speed_class`)만, 수치 속도 아님 | 정지(구동 해제) | 제안값 2 s (Q6) |
| `door` (미래) | `open`, `close` | 없음 | 마지막 안전 상태 유지. 스스로 움직이지 않는다. 끼임 감지 같은 장치 로컬 규칙이 이긴다 | 제안값 10 s (Q6) |

- `set_aspect`는 네 동사(cycle·hold·all_red·failsafe) 밖의 동사다. 지금 Fleet 콘솔이 쓰는 `manual` 모드를 그대로 옮기려면 필요하다. 램프 이름(red·yellow·green)은 신호의 의미 단위이지 핀이 아니므로 semantic 명령으로 본다(Q1).
- `failsafe` **명령**과 장치가 스스로 들어간 `failsafe` **모드**는 다른 것이다. 명령은 wire `flash_red`로 내려가고 `/status`도 `mode=flash_red`로 돌아온다. 장치가 부팅·감독 상실로 들어간 상태만 `mode=failsafe`다. 펌웨어는 `failsafe`를 명령 모드로 받지 않는다(`rosy_signal.ino:249-263`, 그 밖은 `400 bad_mode`). 화면은 "운영자가 점멸시켰다"와 "장치가 감독을 잃었다"를 계속 구별한다(신호등 README "`all_red` 과 `failsafe` 는 다른 말이다")(Q2).
- 여러 신호기 사이의 순서는 동사가 아니다. 순서는 Fleet이 정하고(D-337 §2, D-12), 동사는 한 장치의 상태만 바꾼다.

##### 1.4 수용(ack)과 관측된 효과(effect)

명령 결과는 두 단계로 나눠 기록한다. 하나로 합치지 않는다.

| 단계 | 뜻 | 신호등 지금 wire |
|---|---|---|
| `ack` | 장치가 명령을 받아들였는가. `accepted`, `rejected(code)`, `unreachable` | `200` + 상태 본문 = accepted. `403 unauthorized`, `400 bad_json`·`bad_mode`·`bad_lamps`·`conflict`·`bad_cycle`, `409 stale_seq`(+`last_seq`) = rejected |
| `effect.claimed` | 장치가 주장하는 출력이 의도와 맞는가. `agree`, `controller_mismatch` | 다음 `/status`의 `mode`·`lamps` 대 마지막 의도(`signals.py:428-439`) |
| `effect.measured` | 독립 측정이 장치 주장과 맞는가. `agree`, `display_mismatch`, `stale`, `unmapped`, `absent`, `unreachable`, `unknown`, `pending`, `bad_response` | 관측 `/observed`의 `stable` 대 `lamps`(`cross_check`, `signals.py:97-146`; `_verify_row`, `:441-461`). 관측이 `frozen`이면 `stale` |

- **수용은 효과가 아니다.** 감독자는 `ack=accepted`만으로 "신호가 녹색이다"라고 말하지 않는다. 반대로 `rejected`도 "효과 없음"을 보장하지 않는다. 지금 펌웨어는 `bad_cycle`을 거절하기 전에 실행 중인 cycle 값을 이미 바꾼다(후속 5). 그래서 거절 뒤에도 다음 `/status`로 효과를 다시 본다.
- **`effect.measured`에서 `agree` 말고는 전부 non-agree다.** `absent`(관측기 없음 또는 관측 본문 없음), `unreachable`(관측기 오류), `unknown`(장치 상태 없음), `pending`(대응된 램프 중 하나라도 debounce 확정 전), `stale`, `unmapped`, `display_mismatch`, `bad_response`가 모두 그렇다. 지금 코드에는 이 규칙과 어긋나는 자리가 있다. `cross_check`는 `observed`가 없으면 `agree`를 돌려주고(`signals.py:118-119`), `pending` 램프는 건너뛰므로 나머지가 맞으면 `agree`가 된다(`:137-138`). `_verify_row`의 `unreachable`·`unknown`(`:447`, `:456`)은 초안의 열거에 없었다. codec은 이 경우를 각각 `absent`·`pending`·`unreachable`·`unknown`으로 옮긴다. 화면 표시는 지금처럼 두되, 허가 술어가 이 값을 `agree`로 읽지 못하게 하는 것이 목적이다. 시험: `test_effect_measured_is_not_agree_when_observer_absent_unreachable_unknown_or_pending`.
- **admission 술어.** 지금 Fleet admission·교통은 신호·문 상태를 읽지 않는다(신호 상태 소비자는 `console.py`·`cli.py`뿐이다). 읽게 되면, 진입 허가 근거는 아래 다섯이 **모두** 참일 때뿐이다. 하나라도 거짓이면 진입 불허다(fail-closed).
  1. 측정값이 "가도 된다"는 상태다. 신호는 운영자 사이클 지도가 진행으로 정한 램프가 측정으로 켜져 있고 정지 램프가 꺼져 있다(색의 의미는 지도가 정한다, D-163). 문은 측정이 "열림"이다.
  2. `effect.measured == agree`.
  3. 장치 상태가 `link == ok`이고, 장치 `mode`가 `failsafe`·`flash_red`·`all_red`가 아니다.
  4. 신선하다. 관측은 `frozen=false`이고 `age_s ≤ freeze_after_s`(관측기 기본 5.0 s)다. 장치 상태는 `read_at`에서 `2 × POLL_INTERVAL_S`(4 s) 안에 읽었다. 오프라인 행의 마지막 값(§1.2)은 신선하지 않다.
  5. 감독자가 이 장치에 대해 `stale_seq` 불일치를 들고 있지 않다.

  **적색이 적색과 맞는 것도 `agree`다. `agree`는 "가도 된다"가 아니다.** 그래서 1번이 따로 있다. 로봇은 이 술어와 별개로 D-337 §1·§3대로 측정만 읽고 카메라 증거와 함께 쓴다. 시험: `test_admission_requires_go_aspect_agree_link_ok_and_fresh`, `test_red_agreeing_with_red_never_admits`.
- **seq 재동기화.** 감독자는 폴링한 `last_seq`로 자기 seq를 맞춘다. 규칙은 `seq := max(감독자 seq, 장치 last_seq)`이고 매 폴링에서 적용한다. `409 stale_seq`를 받으면 응답의 `last_seq`로 같은 방식으로 맞춘다. **안전 방향 동사(`all_red`, `failsafe`)는 재동기화 뒤 한 번만 다시 보낸다.** 그 밖의 동사는 자동으로 다시 보내지 않고 `stale_seq` 불일치로 남겨 운영자에게 보인다(다른 감독자의 흔적일 수 있다).
  - **지금 코드는 이 규칙을 어긴다(이행 (b2)에서 고친다).** Fleet이 재시작하면 seq가 0부터 다시 시작한다(`signals.py:294`). 장치 `lastSeq`는 장치가 재부팅할 때만 0이 된다. 폴링 기록(`_record`, `:422-426`)은 장치 `seq`를 읽지 않는다. 그래서 Fleet 재시작 뒤 첫 `all_red` scatter는 `409`를 받고(`:353-359`) 재시도도 없다. e-stop의 신호등 쪽 절반이 그 장치에서 실패한다. 실패가 화면에 보이기는 하지만 e-stop이 한 번에 신호를 세우지 못한다. 시험: `test_poll_resyncs_seq_from_device_last_seq`, `test_all_red_after_fleet_restart_retries_once_after_resync`, `test_non_safety_verb_is_not_retried_after_stale_seq`.
- **failsafe 재단언에는 한계가 있다.** 감독자는 장치가 `mode=failsafe`인 것을 보고 운영자의 마지막 의도를 새 seq로 **한 번** 다시 내릴 수 있다. 단, 아래 두 조건이 모두 참일 때만이다.
  1. **감독이 끊기지 않았다.** 감독자가 그 장치와 마지막으로 성공한 인증 접촉(폴링 또는 명령)이 failsafe를 처음 본 시점보다 `timeout_s`(신호등 10 s) 안이다. 즉 장치가 재부팅·전원 흔들림으로 failsafe에 들어갔고, 그동안 감독자는 계속 감독하고 있었다.
  2. **수동 녹색은 운영자가 있어야 한다.** 그 의도가 `set_aspect`(수동 점등)이면 재단언 시점에 운영자가 콘솔에 있어야 한다(아래 "수동 점등 유지"). 없으면 재단언하지 않는다.

  여기서 **stale 의도**는 내린 뒤 그 장치의 감독이 한 번이라도 `timeout_s` 이상 끊긴 의도, 또는 운영자가 없는 수동 점등 의도다. stale 의도는 절대 다시 보내지 않는다(사용자 결정 Q5, 2026-10-04).

  하나라도 거짓이면 장치는 failsafe에 남는다. 운영자가 새 명령을 내려야만 나온다. 화면은 "재명령 필요"와 마지막 의도, 그 나이를 보여 준다. 링크가 돌아왔다는 사실만으로 failsafe가 풀리지 않는다(§2.4, D-430 §4의 래치 정지 취지). D-429 §3의 승인 후보를 입력으로 만든 명령은 조건과 무관하게 재단언하지 않는다.
  - **지금 코드는 이 규칙을 어긴다(이행 (b2)의 필수 변경).** `_intent`는 나이 없이 무기한 남고(`signals.py:293`), 재단언은 failsafe 에피소드마다 한 번 일어난다(`:402-418`). 폴링은 콘솔 UI가 당길 때만 돈다(모듈 docstring). 그래서 콘솔을 밤새 닫아 두면 신호등은 10 s 뒤 failsafe로 가고, 다음 날 첫 폴링이 운영자 행동 없이 옛 의도를 다시 내린다. 그 의도가 `manual` 녹색이면 아무도 확인하지 않은 녹색이 켜진다. 시험: `test_reassert_requires_continuous_supervision`, `test_reassert_refuses_manual_intent_without_operator_presence`, `test_failsafe_after_supervision_gap_waits_for_operator_command`.
- **상시 감독(사용자 결정 Q5, 2026-10-04).** Fleet은 등록된 모든 신호등을 콘솔이 열려 있든 아니든 계속 감독한다. 폴링 주기는 `POLL_INTERVAL_S`(2 s)이고, 인증된 폴링이 장치 heartbeat다. 감독은 더 이상 콘솔 UI의 `/api/fleet/state` 당김에 기대지 않는다.
- **수동 점등 유지(사용자 결정 Q5).** `set_aspect`(수동 점등, 예: 수동 녹색)는 운영자가 콘솔에 있는 동안만 유지된다. 운영자 있음은 인증된 `operator` 역할(D-332 §4) 콘솔 세션이 presence를 `timeout_s`(10 s) 안에 보내고 있는 상태다. presence가 끊기면 감독자는 그 신호등에 `failsafe` 동사(wire `flash_red`)를 내린다. **자동 cycle로 돌아가지 않는다.** 아무도 확인하지 않은 녹색이 자동 순서로 다시 켜지는 길을 막기 위해서다. 이 상태에서 나오는 길은 운영자의 새 명령뿐이다. `cycle`·`hold`·`all_red`·`failsafe` 의도는 운영자 presence에 묶이지 않는다.
  - **지금 코드에는 상시 감독도 수동 점등 유지도 없다.** 폴링은 콘솔 UI가 당길 때만 돌고(`signals.py` 모듈 docstring, `refresh`), 수동 점등은 운영자가 떠나도 감독이 이어지는 한 그대로 남는다. 상시 감독 루프와 presence 기반 `failsafe` 전환은 이행 (b2)의 필수 변경이며 Fleet 동작을 바꾼다. 시험: `test_signals_are_supervised_without_console`, `test_manual_aspect_drops_to_failsafe_when_operator_presence_lapses`, `test_cycle_intent_is_not_bound_to_operator_presence`.

##### 1.5 버전

- 스키마 major는 이름에 있다(`/1`). 필수 필드 추가·의미 변경·필드 삭제는 `/2`다. 선택 필드 추가는 `/1` 안에서 한다.
- profile 버전(`signal/1`, `dock/1`)은 wire 버전이다. 지금 펌웨어의 두 wire가 각각 `signal/1`, `dock/1`이다. 펌웨어 semver(`"1.0.0"`)는 장치 구현 버전이며 profile 버전과 다르다.
- 장치가 profile 이름을 스스로 알리는 필드(예: `/status`의 `contract`)나 mDNS TXT는 지금 넣지 않는다. 넣는다면 선택 필드로, D-432 발견 규약과 함께 정한다(Q10).
- 소비자는 모르는 선택 필드를 무시한다. 모르는 `mode` 값은 표시는 하되 허가 근거로 쓰지 않는다(진입 불허 쪽). 지금 Fleet은 비어 있지 않은 `mode` 문자열을 그대로 받으므로(`signals.py:76-79`) 이 규칙은 표시 동작을 바꾸지 않는다.

##### 1.6 지금 wire → 계약 대응 (wire 변경 없음)

**`signal/1`** (ROSY-SIGNAL-001)

| 계약 | wire | 비고 |
|---|---|---|
| `identity.device_id` | `signals.yaml`의 `signal_id`(등록) | `/status.signal_id`는 대조용 |
| `identity.firmware` | `/status.firmware` | 선택 |
| `credential_ref` | `signals.yaml`의 `token` → `X-Rosy-Token` | GET·POST 모두 |
| `mode` | `/status.mode` (`failsafe`·`manual`·`cycle`·`hold`·`all_red`·`flash_red`) | 필수 |
| `claimed.lamps` | `/status.lamps` | 필수. 릴레이 구동값 = 주장(D-337 §1) |
| `measured.lamps` (`independent_observer`) | 관측 `/observed`의 `stable` + `signals.yaml`의 `observer_map` | 관측기가 없으면 `absent` |
| `supervision.secs_since_contact` | `/status.secs_since_contact` | 선택 |
| `supervision.timeout_s` | 10 (profile 상수, `HEARTBEAT_TIMEOUT_MS`) | |
| `last_seq` | `/status.seq` | 없으면 0 (`signals.py:85`) |
| `faults` | `/status.faults` (예: `supervisor_lost`) | |
| `verb=cycle` | `POST /command {"seq", "mode":"cycle", "cycle":{...}}` | |
| `verb=hold` | `{"seq", "mode":"hold"}` | |
| `verb=all_red` | `{"seq", "mode":"all_red"}` | Fleet e-stop scatter(`signals.py:336-360`) |
| `verb=failsafe` | `{"seq", "mode":"flash_red"}` | §1.3 |
| `verb=set_aspect` | `{"seq", "mode":"manual", "lamps":{...}}` | 적+녹은 장치가 `400 conflict` |

**`dock/1`** (ROSY-DOCK-001)

| 계약 | wire | 비고 |
|---|---|---|
| `identity.device_id` | 로봇 dock DB의 도크 항목(등록) | `/status.dock_id`는 대조용 |
| `identity.firmware` | `/status.firmware` | 선택 |
| `credential_ref` | 없음 | 읽기 전용 |
| `mode` | `null` | 도크에는 모드 필드가 없다. 지어내지 않는다 |
| `measured.load_present` (`device_sensor`) | `/status.load_present` | 필수. 리밋스위치, 기계적 사실 |
| `measured.current_a`, `measured.output_voltage_v` (`device_sensor`) | 같은 이름 | 선택 |
| `claimed.output_enabled` | `/status.output_enabled` | 선택. 장치가 접점을 켰다는 주장 |
| `claimed.charging` | `/status.charging` | 필수. 장치 판정(`output_enabled && current_a > 0.05`, `rosy_dock.ino:151`)이므로 주장으로 분류한다. 로봇은 자기 전압과 함께만 쓴다(`charging.py`) |
| `supervision` | `supervised=false`, `timeout_s=null` | |
| `last_seq` | `null` | |
| `faults` | `/status.faults` (예: `overvoltage`) | |
| 동사 | 없음 | |

`charging`을 `claimed`로 두는 것이 이 대응의 핵심이다. 도크 README가 이미 "로봇은 이 엔드포인트만 믿지 않는다"고 적었고, 그 이유는 이 값이 D-27 과방전 정지를 억제하는 입력이기 때문이다. 계약 타입이 이 구분을 들고 다니면, 새 소비자가 `charging`만 보고 안전 경로를 끄는 실수를 타입 수준에서 드러내기 쉬워진다.

#### 2. 소유와 권한

1. **명령하는 쪽은 하나다.** 명령을 받는 장치에 명령을 내리는 구성 요소는 operations의 사이트 장치 감독자 하나뿐이다. 지금은 Fleet 프로세스(`signals.py`)다. 장치마다 동시에 감독자는 하나이며, 두 번째 명령 진입점을 만들지 않는다(D-429 §2). 콘솔 UI·ER2·로봇·관측기·다른 서비스는 감독자를 거친다. 문·컨베이어의 정책 소유자가 D-435(Proposed)에서 Fleet이 아닌 작업 오케스트레이션으로 정해지더라도, 장치별 단일 감독자와 단일 진입점이라는 규칙은 같다(Q4).
2. **로봇은 읽기만 한다.** 로봇은 도크 `/status`를 직접 읽고(`agent.py:73-107`), 신호는 관측 서비스의 측정만 읽는다(D-337 §1). 로봇에서 사이트 장치로 가는 명령 경로는 만들지 않는다(D-337 §2). 로봇은 사이트 장치 상태를 fail-closed evidence로만 쓴다. 장치 상태만으로 로봇 안전 동작을 억제하거나 진입을 단독 허가하지 않는다(D-429 §2, D-430).
3. **ER2는 후보만 낸다.** D-429 §3 그대로다. 사이트 장치 직접 구동 도구는 catalog에 없다(D-392 §4, D-429 §3의 거부 이름, D-430 층 7 시험). 승인된 후보는 장치 명령이 아니라 감독자 신호 순서·교통 로직의 입력일 뿐이다. 감독자가 그 입력으로 명령을 만들면 실행 직전에 §1.3의 재확인(점유, 세대, turn·stop 무효화, 인터록)을 모두 하고, stale이면 재시도하지 않는다.
4. **장치마다 로컬 failsafe를 진다.** 명령을 받는 kind는 감독자 침묵을 스스로 감지해 §1.3 표의 failsafe 상태로 간다. 부팅 직후와 펌웨어 재시작 직후도 failsafe다. 마지막 명령은 비휘발 메모리에 남기지 않는다. failsafe에서 나오는 길은 인증된 감독자의 새 명령뿐이다. 링크가 돌아왔다는 사실만으로 풀리지 않는다(D-430 §4). 감독자 쪽 재단언은 §1.4의 두 조건 안에서만 허용된다. 읽기 전용 kind는 감독 상실 규칙 대신 국소 인터록을 진다(도크 0 V). 도크가 명령면을 얻으면 같은 변경에서 자격증명, heartbeat, 감독 상실 시 0 V, 그리고 profile 개정(`dock/2`)이 함께 들어와야 한다.
5. **어떤 ROSY 구성 요소도 안전 회로에 쓰지 않는다.** 물리 E-stop, safety relay, safety PLC의 코일·레지스터·입출력에 쓰지 않고 우회하지 않는다. 그 상태는 `measured`로 읽을 수 있다(D-430 §3 불변식 5, D-429 §4).

#### 3. PLC/Modbus 경로

- **자리:** `integrations/fieldbus/modbus` 어댑터(사용자 결정 Q9, 2026-10-04. `control`은 D-429 concern 이름과 겹쳐서 쓰지 않는다)가 `rosy.site-device/1`의 `conveyor`·`door` profile을 구현한다. 어댑터는 writer가 아니라 포트 구현이다(D-429 §4 integrations 재정의). D-427 §2 표의 operations integrations 목록에 `fieldbus`를 더하는 일은 첫 어댑터 변경에서 한다(매니페스트 `import_rules.operations.integrations`는 지금 `[models, storage]`). D-429 §4의 예시 이름 `integrations/site_devices/modbus`를 대체한다.
- **profile 레지스터 맵:** 통합자가 사이트별로 쓰는 설정 파일이 semantic 동사 → 쓰기 주소·값, 상태 필드 → 읽기 주소와 `claimed`/`measured` 분류를 정한다. 쓰기 가능한 주소는 이 맵에 나온 것뿐이다(허용 목록). 맵에 없는 주소에 쓰는 API는 어댑터에 없다.
- **안전 주소 거부 목록:** 통합자가 safety 영역(E-stop 상태, safety relay, safety PLC I/O, 안전 파라미터)을 거부 목록으로 선언한다. 어댑터는 (1) 맵을 읽을 때 쓰기 주소가 거부 목록과 겹치면 기동을 거부하고, (2) 실제 쓰기 함수에서도 다시 확인한다. 겹침은 주소 하나가 아니라 **범위**로 검사한다. 범위의 키는 `(unit_id, table, start, count)`이고, table은 coil·holding register 같은 Modbus 쓰기 대상이다. 여러 칸을 한 번에 쓰는 FC15(Write Multiple Coils)·FC16(Write Multiple Registers)도 `start`부터 `start+count-1`까지 전체가 거부 범위와 겹치지 않아야 한다. 이 두 동작은 시험 `test_plc_adapter_never_writes_safety_addresses`가 강제한다. **이 시험은 D-430이 소유한다**(D-430 Validation). 첫 PLC 어댑터와 같은 변경에서 들어온다. 이 ADR은 시험을 다시 정의하지 않는다.
- **거부 목록만으로는 부족하다.** 허용 목록과 거부 목록은 같은 통합자가 같은 설정에 쓴다. 그래서 둘은 한 사람의 실수를 함께 놓칠 수 있는 단일 실패점이다. 따라서 **safety PLC는 어댑터가 주소로 닿을 수 있는 어떤 Modbus unit에도 있으면 안 된다.** 안전 기능은 별도 safety PLC·안전 relay에 있고, 그 장치는 어댑터의 연결 범위(호스트·포트·unit_id) 밖에 있다. 어댑터가 safety 상태를 읽어야 하면, 표준 PLC가 그 상태를 비안전 입력으로 복사해 둔 주소를 읽는다. 이 배치는 설치 확인 항목이며 상세 경계는 D-429 후속 4가 정한다.
- **감독 heartbeat:** 어댑터는 PLC의 비안전 watchdog 레지스터를 주기적으로 갱신한다. watchdog 값은 **쓸 때마다 바뀌는 카운터 또는 토글**이다. 같은 값을 반복해 쓰는 것은 heartbeat가 아니다. 그래야 멈춘 어댑터가 마지막 값을 들고 있어도 PLC가 침묵을 알아챈다. watchdog은 그 PLC의 단일 감독자만 쓴다. PLC 로직이 watchdog 정지를 보면 §1.3의 failsafe(컨베이어 정지, 문 정지·유지)로 간다. 이 failsafe는 PLC 안의 로컬 규칙이며 ROSY가 살아 있어야 동작하는 것이 아니다.
- **인터록은 두 겹이다.**
  - Fleet admission은 문에 대해 §1.4 admission 술어가 참일 때만(측정 "열림", `agree`, `link=ok`, 신선함) 그 문을 지나는 경로·진입을 승인한다. 닫힘·움직임·모름·stale은 모두 불허다.
  - PLC는 자기 로컬 인터록을 따로 가진다(예: 끼임·광커튼). ROSY 명령은 그 인터록을 넘지 못한다.
  - 상세 인터록 설계와 ROSY 감독 신호·safety PLC 회로의 경계는 **D-429 후속 4(PLC 인터록 ADR)**가 정한다. 이 ADR은 참조만 한다.
- **연결 소유:** PLC 하나가 D-442의 PLC 구동 축(로봇 장치, DeviceControlPort binding)과 컨베이어(사이트 장치)를 함께 구동할 수 있다. 이때 **PLC 연결 하나에 어댑터 프로세스 하나**를 두고, 축 binding과 사이트 장치 profile은 그 어댑터를 거치는 두 클라이언트가 된다(권고). 두 클라이언트의 쓰기 범위는 서로 겹치지 않고, 어댑터가 범위 겹침과 거부 목록을 한 곳에서 검사한다. 축 쪽 단일 writer 규칙(D-442, D-2·D-38)과 사이트 장치 쪽 단일 감독자 규칙(§2.1)은 각자 그대로다. 연결을 둘로 나누면 같은 PLC에 writer가 둘, watchdog도 둘이 생기므로 피한다.

#### 4. 이행 — 동작 변경 없이 먼저

| 단계 | 내용 | 동작 변화 | 시험 |
|---|---|---|---|
| (a) | 계약 타입(`SiteDeviceStatus`·`SiteDeviceCommand`·ack/effect)과 `signal/1`·`dock/1` profile codec을 `contracts/site_device`(import `rosy.contracts.site_device`, `contracts/skill`과 같은 모양)에 둔다. 적합성 시험을 지금 펌웨어 fixture에 대해 쓴다 | 없음. 아직 아무도 import하지 않는다 | README 예시 본문(신호등 `/status`·`/command` 예시, 도크 `/status` 예시)이 codec을 왕복하는지, 필수 필드 누락이 `bad_response`인지, profile 동사 → wire 모드 대응이 펌웨어 모드 열거(`rosy_signal.ino:249-263`)와 같은지, `failsafe`가 wire 명령 모드가 아닌지, 계약 타입에 raw I/O 필드가 없는지 |
| (b1) | Fleet `signals.py`가 안쪽에서 계약 타입을 쓴다. `SignalStatus`는 codec 결과의 얇은 별칭이 되거나 사라진다. HTTP 경로와 `/api/fleet/state` 행 모양은 그대로다 | 없음 | 기존 `src/site/fleet/test/test_server_signals.py` 전부 통과 |
| (b2) | **현재 코드 결함 고치기와 상시 감독(필수, 안전 방향 동작 변경).** ① 재단언 한계(§1.4: 감독 연속성, 수동 점등은 운영자 presence, stale 의도 재전송 금지). 장치별 마지막 성공 접촉 시각과 의도 시각을 기록한다. ② 폴링마다 `last_seq` 재동기화, 안전 방향 동사(`all_red`·`failsafe`) 1회 재시도(§1.4). ③ `effect.measured`에서 `absent`·`unreachable`·`unknown`·`pending`을 `agree`와 가르고, admission 술어를 둔다(§1.4). ④ 오프라인 행에 `link`와 나이를 붙인다(§1.2). ⑤ Fleet 상시 감독 루프(콘솔과 무관, 2 s)와 운영자 presence가 끊기면 수동 점등을 `failsafe`로 바꾸는 규칙(§1.4, 사용자 결정 Q5) | 있음. 신호등이 콘솔 없이도 감독된다. 밤사이 옛 의도의 자동 재점등이 사라지고, 운영자가 떠난 수동 녹색은 점멸로 바뀌며, Fleet 재시작 뒤 e-stop의 신호등 쪽이 성공한다. `/api/fleet/state` 행에는 필드가 더해질 뿐 빠지지 않는다 | §1.2·§1.4의 시험 이름 전부 + 기존 `test_server_signals.py`. Fleet 동작 변경이고 all_red scatter는 e-stop의 절반이므로 독립 리뷰와 `Safety-Review:` trailer를 붙인다 |
| (c) | 로봇 도크 소비자(`DockAgent`, `ChargingConfirmation`)가 같은 상태 타입을 쓴다. `charging`은 `claimed`에서 읽는다 | 없음 | `src/runtime/services/test/test_docking*.py`, `test/test_dock_contract.py` 통과. 2소스 확인 규칙 불변 |
| (d) | 새 kind(컨베이어·문)는 (a)–(c)((b2) 포함)가 main에 들어간 뒤에만 연다. 새 kind의 profile 표·failsafe·timeout은 이 ADR 개정 또는 새 ADR로 정하고, PLC 경로는 D-429 후속 4와 함께 간다 | 새 장치 | kind별 적합성 시험 + D-430의 `test_plc_adapter_never_writes_safety_addresses` |

- **D-427 이전과의 순서.** 펌웨어 폴더 이전(`firmware/{signal,dock}` → `operations/site_devices/{signal,dock}`, 매니페스트 wave `3b`)과 이 이행은 별개다. 어느 쪽이 먼저여도 되지만, 한 커밋에서 섞지 않는다.
- **(a)의 자리가 contracts인 이유.** 도크 상태 타입은 middleware(로봇 도킹)가, 신호 상태 타입은 operations(Fleet)가 쓴다. 둘이 함께 import할 수 있는 곳은 contracts뿐이다(D-427 §2). 계약 **문서**의 정본과 펌웨어는 D-429 §2대로 `operations/site_devices/<kind>`에 남는다. 신호 HTTP driver(`HttpSignalClient`)는 Fleet이 import하는 `operations/site_devices/signal` 라이브러리로 간다(D-429 §2). contracts에는 타입과 순수 codec만 둔다. 네트워크 코드는 두지 않는다(Q3).
- **안전 변경 통제.** 펌웨어(`firmware/signal/firmware`, `firmware/dock/firmware`)와 Fleet `console.py`의 `estop_all`(all_red scatter 호출자)은 D-430 §1의 safety 태그 대상이다. 이행 단계가 그 파일을 건드리면 독립 리뷰와 `Safety-Review:` trailer가 필요하다(D-430 §5). 계획상 (a)–(c)는 펌웨어를 바꾸지 않는다. (b2)는 `signals.py`만 바꾸더라도 Fleet 감독 동작과 e-stop의 신호등 쪽 동작을 바꾸므로 trailer를 붙인다. (b2)가 `all_red()`의 반환 모양이나 호출 방식을 바꾸면 `console.py`도 바뀌므로 trailer가 필수다. (c)의 `charging.py`는 사용자 결정 Q8에 따라 safety로 태그된다. 태그는 별도 D-430 매니페스트 변경으로 넣고, 그 변경이 먼저 들어가면 (c)도 `Safety-Review:` trailer를 가진다. 먼저 들어가지 않았더라도 (c)는 같은 수준의 리뷰를 받는다.

### 기존 결정과의 관계

| 기록 | 처리 |
|---|---|
| D-429 (Accepted) | 후속 2를 채운다. §4 공통 바탕(식별·상태 measured/claimed·heartbeat·semantic 명령·failsafe)을 사이트 장치 쪽에서 구체화한다. §2의 소유(펌웨어·계약은 `operations/site_devices/<kind>`, 신호 런타임은 Fleet 안, 도크는 로봇 직접 읽기)와 §3의 ER2 후보 규칙·fence 범위를 그대로 쓴다. §4 예시의 signal 명령 "mode·phase"를 §1.3 동사 표로 구체화한다. 예시 경로 `integrations/site_devices/modbus`는 사용자 결정 Q9에 따라 `integrations/fieldbus/modbus`로 대체한다. D-429 본문은 이 Proposed 단계에서 고치지 않는다 |
| D-430 (Accepted) | 층 2(사이트 장치 로컬 failsafe)의 kind별 상태·timeout을 §1.3 표로 적는다. 불변식 5(안전 회로 쓰기 금지)를 §2.5·§3에서 따른다. `test_plc_adapter_never_writes_safety_addresses`는 D-430이 소유하며 여기서는 참조만 한다. §5 변경 통제(`Safety-Review:` trailer)를 §4 이행에 건다 |
| D-163 (Accepted) | 유지한다. 관측기는 `GET /observed`만 가진 읽기 전용 평면이며, 이 계약에서는 신호등 `measured`의 `independent_observer` 소스다. 관측기는 명령 경로가 아니다. 실행 호스트는 여전히 정하지 않는다 |
| D-337 §1–§3 (Accepted) | 유지한다. measured vs claimed 구분이 이 스키마의 필드 구분이 된다. 로봇의 제2 신호 소스는 측정뿐, 순서는 Fleet, 불일치·소등은 HOLD/WAIT_SIGNAL |
| D-12 (Accepted) | 유지한다. 여러 신호기 사이의 순서는 동사가 아니다. 순서 결정은 Fleet에 있다 |
| D-200 (Accepted) | 유지한다. 도킹 판단과 DOCKING 모드는 로봇에 있다. 계약은 도크 상태 타입만 공유한다 |
| D-349, D-350, D-351 (Accepted) | 유지한다. 도크 리밋 인터록·0 V 부팅·폴트 래치, 하드웨어 단계, 실패 종류별 재시도는 바뀌지 않는다. `dock/1` profile은 그 상태 필드를 옮겨 적을 뿐이다 |
| D-392 §4 (Accepted, D-429로 보강) | 유지한다. 사이트 장치 직접 구동 도구는 금지이며, §1.3의 동사는 모델 도구가 아니라 감독자 내부 명령이다. 후보 도구 이름은 D-429 후속 3이 거부 목록과 겹치지 않게 정한다 |
| D-427 (Accepted) | 경로를 따른다. 계약 타입은 `contracts/site_device`, 장치 owner는 `operations/site_devices/<kind>`, 어댑터는 `integrations/fieldbus/modbus`(사용자 결정 Q9). operations의 integrations kind 목록 추가는 첫 어댑터 변경에서 한다 |
| D-435 (Proposed) | 충돌 가능 지점을 Q4로 둔다. D-435 §3은 문·컨베이어 같은 로봇 외 자원의 정책을 자동으로 Fleet 책임으로 올리지 않는다. 이 ADR은 "장치별 단일 감독자"를 정하고, 감독자가 Fleet인 것은 신호등(D-337 §2)에 대해서만 확정한다 |
| D-442 (Accepted) | PLC 구동 축은 D-442의 DeviceControlPort binding(로봇 장치)이고, 컨베이어·문은 이 계약의 사이트 장치다(D-442 Decision의 구분). 한 PLC가 둘을 함께 구동하면 연결 하나에 어댑터 하나, 클라이언트 둘로 둔다(§3 "연결 소유") |
| D-353 (Accepted) | 유지한다. `link` 필드가 `core_common.device_poll`의 4상태 실패 열거를 그대로 쓴다 |
| D-354, D-432 (Accepted) | 유지한다. mDNS 서비스 이름이 kind 판정의 한 근거다. 장치가 profile을 알리는 필드는 D-432와 함께 나중에 정한다 |

### Alternatives

- **지금 wire를 통일한다(공통 envelope로 펌웨어 개정).** 장치끼리 모양이 같아진다. 하지만 safety 태그 펌웨어 두 개를 다시 굽고 실물을 다시 확인해야 하며, 얻는 것은 호스트 타입 하나로도 얻을 수 있다. 기각. 새 kind는 처음부터 profile `/1`을 계약 모양에 가깝게 만들 수 있다.
- **kind마다 따로 둔다(현 상태 유지).** 변경이 없다. 하지만 컨베이어·문·PLC가 올 때마다 상태·ack·failsafe 규칙을 다시 정하게 되고, measured/claimed 구분이 소비자 코드마다 다시 쓰인다. 기각.
- **Open-RMF door/lift 메시지를 그대로 쓴다.** 검증된 모양을 빌린다. 하지만 ROS 메시지를 전제하며, 첫 비-ROS 대상(PLC/Modbus, D-429 §4)과 ROS 없는 Fleet 프로세스에 맞지 않는다. 요청 상태와 현재 상태를 가르는 의미만 빌린다(§1.4). 원문 대조는 하지 않았다(미확인).
- **일반 `set_output(channel, value)` 명령.** 새 kind를 코드 없이 붙일 수 있다. 하지만 raw I/O가 계약에 들어오고(D-429 §4 위반), 안전 주소 거부를 어댑터 밖으로 밀어낸다. 기각.
- **계약 타입을 `operations/site_devices`에만 둔다.** D-429 §2의 "owner가 계약을 소유"와 글자 그대로 맞는다. 하지만 middleware(로봇 도킹)가 operations를 import할 수 없어(D-427 §2) 도크 소비자가 같은 타입을 못 쓴다. 문서 정본은 owner에, 타입·codec은 contracts에 둔다(Q3).
- **별도 사이트 장치 서비스 프로세스.** 장치 감독을 Fleet에서 떼어 낸다. D-429 §2가 이미 기각했다(두 번째 명령 진입점, 신호 순서 소유자 분리). 기각.

### Consequences

- 사이트 장치를 늘리는 단위가 정해진다. kind 하나 = profile 하나(wire 대응 표, 동사, failsafe, timeout) + 적합성 시험 + 장치 owner 폴더.
- "보냈다"와 "됐다"가 타입에서 갈린다. admission·교통 grant가 측정된 효과만 근거로 쓴다는 규칙이 문장이 된다.
- 도크 `charging`이 `claimed`로 분류되어 단독 신뢰 금지가 타입에 남는다.
- 지금 Fleet 신호 폴링은 요청 시 갱신이다(`signals.py` 모듈 docstring). 콘솔을 아무도 보지 않으면 신호등은 10 s 뒤 failsafe로 간다. 사용자 결정 Q5에 따라 이행 (b2)에서 Fleet이 상시 감독으로 바뀐다. 그 뒤로는 신호등이 콘솔과 무관하게 감독되고, 수동 점등만 운영자 presence에 묶인다. §1.4의 재단언 한계 때문에 감독이 끊긴 뒤 옛 의도가 저절로 되살아나는 일은 없다.
- 이행 (b2)는 동작 변경이다. "동작 변경 없이 먼저" 원칙의 예외이며, 바뀌는 방향은 모두 안전 쪽이다(재점등 차단, e-stop 성공, non-agree 확대).
- contracts에 새 root(`contracts/site_device`)가 생긴다. 매니페스트와 `test/architecture`에 root를 더하는 일은 (a) 단계에서 한다.
- 코드·펌웨어·wire·매니페스트·gate는 이번 변경에서 바뀌지 않는다.

### Validation and Follow-up

이번 문서의 수용 조건은 ADR·Log 행의 일치, 번호 충돌 부재, harness lint 0 error, `test/architecture` 통과다. 코드·펌웨어·wire·매니페스트 변경은 없다.

**구현 단계의 시험(이름은 제안):**

- (a) `contracts/site_device/test/test_signal_profile.py`: `test_readme_status_example_round_trips`, `test_missing_mode_or_lamps_is_bad_response`, `test_every_verb_maps_to_a_firmware_command_mode`, `test_failsafe_verb_maps_to_flash_red_not_failsafe`, `test_lamps_are_claimed_and_observer_lamps_are_measured`
- (a) `contracts/site_device/test/test_dock_profile.py`: `test_readme_status_example_round_trips`, `test_required_fields_match_dock_agent`, `test_charging_is_claimed_and_load_present_is_measured`, `test_dock_profile_has_no_verbs`
- (a) `test_contract_types_carry_no_raw_io_fields`: 계약 타입·동사·인자 이름에 `pin`·`gpio`·`coil`·`register`·`relay`가 없다
- (b1) `test_server_signals.py` 전부 통과, `/api/fleet/state` 신호 행 모양 불변
- (b2) `test_reassert_requires_continuous_supervision`, `test_reassert_refuses_manual_intent_without_operator_presence`, `test_failsafe_after_supervision_gap_waits_for_operator_command`, `test_poll_resyncs_seq_from_device_last_seq`, `test_all_red_after_fleet_restart_retries_once_after_resync`, `test_non_safety_verb_is_not_retried_after_stale_seq`, `test_effect_measured_is_not_agree_when_observer_absent_unreachable_unknown_or_pending`, `test_offline_row_carries_link_and_age`
- admission이 장치 상태를 읽게 되는 변경: `test_admission_requires_go_aspect_agree_link_ok_and_fresh`, `test_red_agreeing_with_red_never_admits`
- (c) 도킹 시험 전부 통과, 2소스 확인 불변
- (d) 첫 PLC 어댑터: D-430의 `test_plc_adapter_never_writes_safety_addresses`(FC15/16 범위 겹침 포함) + 맵 밖 주소에 쓰는 API가 없음을 보이는 시험 + `test_watchdog_value_changes_every_write`
- 펌웨어를 건드리는 단계: `test/test_signal_contract.py`, `test/test_dock_contract.py` + `Safety-Review:` trailer. 호스트 pytest 통과는 장치·실주행 수용이 아니다.

**질문과 사용자 결정 (2026-10-04).** 아래 권고안 가운데 Q5·Q8·Q9는 사용자가 따로 정했고, 나머지(Q1–Q4, Q6, Q7, Q10)는 권고안대로 수용됐다.

1. **Q1 `set_aspect` 동사.** 신호등 profile에 네 동사(cycle·hold·all_red·failsafe) 밖의 `set_aspect`(지금 `manual`)를 둘까? **권고: 둔다.** Fleet 콘솔이 지금 쓰는 모드이므로 빼면 동작이 바뀐다. 램프 이름은 신호 의미 단위이며 핀이 아니다.
2. **Q2 `failsafe` 동사 이름.** 운영자 점멸 명령을 `failsafe`로 부를까, wire대로 `flash_red`로 부를까? **권고: 동사는 `failsafe`로 하고, 상태 `mode`는 wire대로 `flash_red`(명령)와 `failsafe`(장치 진입)를 계속 가른다.** 화면이 두 상황을 구별해야 한다는 신호등 README 규칙을 지킨다.
3. **Q3 계약 타입의 자리.** `contracts/site_device`(공유)인가, `operations/site_devices/<kind>`(owner)인가? **권고: 타입·순수 codec은 contracts, 문서 정본·펌웨어·HTTP driver는 owner.** 도크 소비자가 middleware에 있기 때문이다.
4. **Q4 문·컨베이어의 감독자.** D-435(Proposed)는 로봇 외 자원 정책을 Fleet에 자동으로 두지 않는다. 문·컨베이어 감독자는 누구인가? **권고: 이 ADR은 "장치별 단일 감독자, 단일 진입점"만 확정하고 신호등은 Fleet으로 확정한다. 문·컨베이어 감독자는 D-435 수용 판단과 D-429 후속 4에서 정한다.** 어느 쪽이든 문 상태는 Fleet admission의 입력이다.
5. **Q5 무인 시 신호등 감독 — 결정(2026-10-04).** 콘솔을 아무도 보지 않으면 신호등이 failsafe로 간다. 그대로 둘까, Fleet에 상시 heartbeat 루프를 둘까? 초안 권고는 "그대로 둔다"였다. **사용자 결정: Fleet이 등록된 모든 신호등을 상시 감독한다. 수동 점등(`set_aspect`)은 운영자가 콘솔에 있는 동안만 유지되고, 운영자가 떠나면 `failsafe`로 간다(자동 cycle이 아님, §1.4). stale 의도는 다시 보내지 않으며, 감독이 이어지는 동안 일어난 failsafe만 한 번 재단언한다. 나머지는 운영자 명령을 기다린다.** Fleet 동작 변경이므로 이행 (b2)에서 `Safety-Review:` trailer와 독립 리뷰를 받는다.
6. **Q6 새 kind timeout.** 컨베이어 2 s, 문 10 s 제안값을 받을까? **권고: 제안값으로 기록하고, 최종값은 D-429 후속 4(PLC 인터록)에서 실물 PLC watchdog 주기와 함께 확정한다.** 컨베이어는 움직이는 기계이므로 신호등(10 s)보다 짧게 둔다.
7. **Q7 도크 명령면.** 도크가 명령(예: 출력 허용·폴트 해제)을 얻을 때의 조건을 지금 정해 둘까? **권고: §2.4 문장(자격증명·heartbeat·감독 상실 시 0 V·`dock/2`)만 두고 명령 자체는 별도 ADR로 연다.** 도크 README도 명령면이 생기면 평문 HTTP 판단을 다시 하라고 적었다.
8. **Q8 `charging.py` safety 태그 — 결정(2026-10-04).** `core_features/docking/charging.py`는 D-27 과방전 정지 억제 입력인데 D-430 safety 목록에 없다. **사용자 결정: 태그한다. 별도 D-430 매니페스트 변경으로 넣는다.** 이 ADR은 그 변경을 하지 않는다.
9. **Q9 PLC 어댑터 경로 — 결정(2026-10-04).** 초안은 `integrations/control/plc_modbus`였으나 `control`이 D-429 concern 이름과 겹친다(리뷰 지적). **사용자 결정: `integrations/fieldbus/modbus`. `control`은 쓰지 않는다.** D-427 §2 표의 operations integrations 목록에 `fieldbus`를 더하는 일은 첫 어댑터 변경에서 한다.
10. **Q10 profile 자기 신고.** 장치가 `/status`나 mDNS TXT로 profile 이름을 알리게 할까? **권고: 지금은 하지 않는다(wire 변경 없음).** 새 kind의 펌웨어부터 선택 필드로 넣고, 기존 두 장치는 다음 펌웨어 개정 때 D-432 발견 규약과 함께 판단한다.

**후속:**

1. 이행 (a)–(c) 구현 계획(`docs/plans/`)과 단계별 독립 리뷰.
2. D-429 후속 3(ER2 사이트 장치 후보 제안): 후보가 가리킬 수 있는 것은 §1.3 동사뿐이며, 후보 스키마는 `SiteDeviceCommand`의 `fence`를 쓴다.
3. D-429 후속 4(PLC 인터록): §3 레지스터 맵·watchdog·두 겹 인터록의 상세와 Q6 timeout 확정.
4. Q8의 D-430 매니페스트 변경: `core_features/docking/charging.py`를 `safety_modules:`에 넣는다(별도 변경, `Safety-Review:` trailer).
5. **신호등 펌웨어 결함(다음 펌웨어 개정, safety 태그 변경).** `rosy_signal.ino:283-291`은 `bad_cycle` 검사 전에 `cycleGreenMs`·`cycleYellowMs`·`cycleRedMs`를 먼저 바꾼다. 그래서 거절된 명령이 실행 중인 cycle 타이밍을 바꾼다. 또 세 값의 합을 `uint32_t`로 더하므로 넘침이 1 h 상한(`MAX_CYCLE_TOTAL_MS`)을 우회할 수 있다. 고치는 방향은 지역 변수로 검사를 마친 뒤에만 반영하고, 합을 64비트로 더하거나 값마다 상한을 두는 것이다. 펌웨어는 D-430 §1 safety 태그 대상이므로 독립 리뷰, `Safety-Review:` trailer, `test/test_signal_contract.py` 회귀 시험을 함께 넣는다. 이 ADR의 범위 밖이며 여기서는 결함으로만 기록한다.
6. **현재 코드 결함의 일정(사용자 결정, 2026-10-04).** 아래 결함은 D-427 이전이 끝난 직후 첫 안전 작업으로 고친다. 각각 `Safety-Review:` trailer와 독립 리뷰를 받는다. 신호 쪽 B1·S1·S2/S3는 이행 (b2)와 같은 작업이다.
   - **B1 stale 의도 재단언:** 감독 연속성·운영자 presence 조건과 stale 의도 재전송 금지(§1.4). 상시 감독 루프(Q5)와 함께 간다.
   - **S1 seq 재동기화:** 폴링마다 `last_seq`로 맞추고, `all_red`·`failsafe`만 재동기화 뒤 한 번 재시도한다(§1.4).
   - **S2/S3 admission 술어:** non-agree 열거(`absent`·`unreachable`·`unknown`·`pending`)와 다섯 조건 술어(§1.4).
   - **S7 펌웨어 `bad_cycle` 변경과 넘침:** 후속 5의 결함. 다음 펌웨어 개정에서 고친다.

**References:** [D-429](D-429-five-concerns-control-port-and-site-devices.md), [D-430](D-430-safety-as-a-separate-concern.md), [D-163](D-163-signal-observation-readonly-plane.md), [D-337](D-337-robot-signal-source-measured-light.md), [D-12](D-12-mission-fleet.md), [D-200](D-200-docking-owns-the-docking-mode.md), [D-349](D-349-dock-auto-charge-code-readiness.md), [D-350](D-350-dock-hardware-phase-tiers.md), [D-351](D-351-docking-retry-by-failure-kind.md), [D-392](D-392-provider-neutral-model-tool-contract.md), [D-427](D-427-platform-three-parts-middleware-operations-learning.md), [D-435](D-435-work-orchestration-fleet-and-device-authority.md), [D-353](D-353-design-change-seams.md), [D-354](D-354-mdns-service-discovery.md), [D-432](D-432-common-discovery-and-development-link-mode.md), [신호등 계약](../../operations/site_devices/signal/README.md), [도크 계약](../../operations/site_devices/dock/README.md), [관측기](../../operations/vision/signal_observer/README.md), [Fleet 신호 클라이언트](../../operations/fleet/fleet/server/signals.py), [도크 클라이언트](../../middleware/core/services/core_features/docking/agent.py), [충전 확인](../../middleware/core/services/core_features/docking/charging.py), [소유 매니페스트](../../tools/harness/platform_parts.yaml)
