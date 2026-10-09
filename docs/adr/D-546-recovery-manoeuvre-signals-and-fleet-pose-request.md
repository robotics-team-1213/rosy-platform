## D-546 복구 기동 중 로봇은 보이고 들리게 신호한다 — 앰버 비상등·후진 경고음·LCD 한 줄을 먼저 만들고, 위치를 못 잡으면 CORE가 Fleet에 위치 판정을 청한다(프로토콜은 설계만)

**Status:** Proposed (2026-10-09, 사용자 결정: "차선이나 도로를 잃었거나 공간이 없으면 보통 차처럼 위치를 확인하고, 신호를 주며 조심해서 후진하거나 돌고, 매 단계 위치를 다시 확인하며 돌아온다. **신호를 먼저 한다.** 위치는 Rosy Fleet에서 받는다. CORE가 위치를 못 잡으면 증거를 Fleet에 보내 판정을 청하고, Fleet은 자기 로직을 먼저 쓰고 실패할 때만 LLM/VLM을 쓴다"). 이 ADR은 둘로 나뉜다. **결정 1–4a(신호)는 이 브랜치가 구현한다.** **결정 5–8(위치 요청 프로토콜)은 설계이고, 5–7의 첫 조각(VLM 제외)은 `feat/d546-pose-request`가 구현했다(아래 "구현 노트: 위치 요청 첫 조각"). 8(VLM)은 구현하지 않았다.** SIM·DEVICE 수용은 각각 따로다. 표시·소리 경로(`face-inputs`, `rosy-face`)는 Safety-Review 대상일 수 있다.

**부분 개정(수락 뒤 적용):** [D-395](D-395-fleet-assisted-localization.md)·[D-468](D-468-local-lane-departure-return.md)·[D-492](D-492-d438-vision-tier-local-qwen-ai-pc-gated.md)에 대한 개정은 아래 "개정 목록"에 적고, 이 ADR이 Accepted가 될 때 각 ADR 본문에 옮긴다. 그 전에는 세 ADR이 그대로 이긴다.

잇는 결정: [D-260](D-260-robot-shows-its-state-by-sound-light-screen-and-summary.md) 2·3(상태 소리·램프) · [D-380](D-380-lamp-mode-patterns-from-core-status-inputs.md)/[D-381](D-381-blocked-navigation-and-emergency-entry-sound.md)(램프 모드 패턴, 우선순위) · [D-433](D-433-one-face-process-owns-lcd-buzzer-lamp.md)(`rosy-face`가 LCD·부저·램프의 유일한 소유자) · [D-472](D-472-rosy-cam-map-and-lamp-identity.md)(식별 점멸) · [D-476](D-476-lane-loss-expected-road-bridge.md)(차선 소실 다리).

### Context

코드에서 읽은 사실이다(2026-10-09 main).

- D-468 `lane_return`은 tracking → departure_stop → retrace(`measured_path_return`, 후진) → align(`lane_heading_align`) → approach → verify → tracking으로 움직이고, 실패하면 search(`sensor_search`, 제자리 회전) → fleet(`local_deadline`, `local_candidates_exhausted`)로 간다. line_follow 상태는 움직일 때 `state RECOVERING`, `reason lane_return_<이유>`이고, D-476 다리는 `reason lane_bridge`다.
- 이 상태는 사람 눈과 귀에는 닿지 않는다. 램프를 고르는 `robot_state.lamp_pattern(state, mode, nav_state)`에는 line_follow 입력이 없고, `face_cautions`는 HOLD만 `line_follow_hold`로 옮기며, 부저는 상태가 바뀔 때만 울리고 caution 반복은 300 s 막는다. 로봇이 말없이 뒤로 가거나 도는 것이다.
- 위치: D-395 Phase 2는 로봇 토픽(`localization/state`, `candidates`)과 Fleet 중재(`POST /localization/decision`, `source` candidate|overhead|homing_ref|human, `ttl_s`, 로봇의 3 s 스캔 확인)까지 있고 장치에서는 꺼져 있다. 그러나 **lane_return에는 연결되어 있지 않다.** `fleet_required`는 D-407 stuck 경로로만 간다. CORE에는 "나를 찾아 달라"는 나가는 요청이 없다.
- D-492 VLM은 "무엇이 막고 있나"(`{thing, confidence}`)만 답한다. 위치는 답하지 않는다.

### Decision

**신호 (구현)**

1. **파생 필드 `recovery`.** CORE는 `face-inputs.json`에 `recovery`를 더한다. 값은 `line_follow.mode != "OFF"`이고 `state == "RECOVERING"`일 때만 있다: `reason == "lane_return_measured_path_return"` → `"retrace"`(후진), `reason == "lane_bridge"` → `"bridge"`, 그 밖의 `lane_return_*` → `"return"`(정렬·접근·탐색 회전). 아니면 `null`이다. HOLD 중의 `lane_return_*`(정지 대기, `fleet_required`)는 움직이는 것이 아니므로 `recovery`가 아니다. `schema`는 1 그대로다: `validate_face_inputs`는 모르는 키를 읽지 않으므로 옛 `rosy-face`는 새 필드를 무시하고, 새 `rosy-face`는 필드 없는 옛 CORE 파일을 `recovery None`으로 읽는다. 모르는 값은 `None`이다(D-385 1항).
2. **램프.** `robot_state.lamp_pattern`이 선택 인자 `recovery`를 받는다. 우선순위는 FAILED > EMERGENCY > **RECOVERING** > CAUTION > BOOTING > DOCKING > BLOCKED > NAVIGATING > MANUAL > READY다. 비상 정지가 늘 이기고, 복구 기동이 식별 점멸과 나머지를 이긴다.
   - `return`/`retrace` → 새 패턴 `recovering`: **앰버 1.5 Hz 점멸**(켜짐 333 ms / 꺼짐 333 ms, `DIM` 밝기). 방향지시등·비상등의 1–2 Hz 안이다. caution(주황 0.5 Hz)과 같은 색 계열이지만 3배 빠르고, blocked(청록 2 Hz)·failed(빨강 1 Hz)·emergency(빨강 4 Hz)와 색이나 속도가 다르다.
   - `bridge` → 새 패턴 `bridging`: **앰버 호흡 3 s 주기, 최대 25 %**(D-476 다리는 차선이 곧 돌아올 것이라 기대하는 약한 상태다). 램프만 쓰고 소리와 LCD는 없다.
   - 새 패턴 이름 둘은 C 도우미 `lamp_pattern`에 더한다. 도우미가 옛 것이면 모르는 이름이라 종료 코드 64로 끝나고 `rosy-face`는 램프를 뺀다(fail-open, D-260 3). 소리와 LCD는 그대로 동작한다.
3. **부저.** `retrace`(후진) 동안만 **후진 경고음**: 1 kHz 한 번, 80 ms(`BUZZER_ON_S`), **1.0 s 주기**. 근거: 차량 후진 경고음은 대략 1 Hz 단음이고, 이 부저는 passive piezo에 `BUZZER_DUTY` 10 %라 새 음량 설정이 필요 없다. 주기가 `POLL_S` 0.5 s보다 느려 호출 한 번이 폴링을 0.1 s 넘게 막지 않는다. 경고음은 caution 반복 제한(`BUZZER_REPEAT_S` 300 s)과 **무관**하다: 후진하는 동안은 계속 울린다. 후진은 D-468 지연 제한(`local_deadline`)으로 유한하다. 비상 정지·EMERGENCY·`recovering`이 아닌 패턴이면 울리지 않는다. `recovery`가 `retrace`에서 벗어나면(정렬로 넘어가거나 HOLD) 다음 폴링부터 멈춘다. 정렬·접근·탐색 회전·다리는 소리가 없다(앞으로 가거나 제자리 회전은 후진 경고음의 의미가 아니다).
   - **조용한 시간·현장 음소거(사용자 결정, 2026-10-09):** 조용한 시간 규칙은 **두지 않는다.** 음소거는 `/etc/rosy/boot-display.env`의 `ROSY_BUZZER_ENABLED=false` 하나뿐이고 후진 경고음도 같은 스위치로 꺼진다.
4. **LCD와 Fleet.** `return`/`retrace`에는 LCD 띠에 ASCII 한 줄을 띄운다: `Recovering: reversing`(retrace), `Recovering: returning to lane`(return). 톤은 caution이고 식별 호출 띠와 일반 caution 띠를 이긴다(상황표 9–11행의 맨 위). 비상 정지·정지 카드(행 1–8)는 이 띠 위에 그대로 있다. `bridge`는 LCD가 없다. 식별 점멸은 `recovery`가 `return`/`retrace`인 동안 거절된다(`unsafe_identity`). 식별 API는 다른 모든 거절처럼 `accepted: true`로 답하고, 거절은 결과 파일의 `state: failed`로 나타난다. Fleet은 이미 `line_follow.state/reason`을 상태로 받으므로 **새 Fleet 필드는 없다.**

4a. **신호 유지(사용자 결정, 2026-10-09).** 마지막 RECOVERING 틱 뒤 **1.5 s** 동안 램프와 LCD 띠를 유지해 단계 사이에서 깜박이지 않게 한다(`rosy-face`의 `RECOVERY_HOLD_S`, `return`으로 유지). 후진 경고음은 `retrace`가 끝나는 즉시 멈춘다. `face-inputs`의 `estop`이 거짓이 아니면 `recovery`를 바로 지우므로, 10 s 지연되는 `status-inputs` 모드를 기다리지 않고 비상 정지가 이긴다.

**위치 요청 프로토콜 (설계만, 구현은 따로)**

5. **언제 청하나.** lane_return이 위치 증거가 없어서 못 가거나(`pose_stale`, `fleet_required`), 운영자·CORE가 부를 때, CORE가 요청을 올린다. 요청은 D-395의 로봇 토픽에 **`localization/request`**(이벤트 겸 상태)로 싣는다: `{request_id, robot_id, reason, since, evidence {last_pose, lane_state, scan_ref, camera_ref?}, ttl_s}`. 새 채널을 만들지 않고 Fleet이 이미 보는 `localization/state`와 같은 길로 나간다. 요청 중에는 `recovery`가 아닌 HOLD이고, **로봇은 멈춰서 신호를 켠 채 기다린다**(앰버 점멸은 결정 2의 `bridging`이 아니라 `caution` + LCD `Waiting for position`).
6. **누가 답하나, 어떤 순서로.** Fleet은 **자기 로직을 먼저** 쓴다: ① 천장 카메라 자세(D-457 보정·D-515 탑다운), ② D-395 중재기(후보 점수), ③ 차선 그래프 제약. 이 셋이 믿을 수 있는 하나를 내면 끝이다. **하나도 못 낼 때만** VLM 층을 부른다.
7. **답의 형식.** 답은 기존 `POST /localization/decision`이다(`source`, `ttl_s`, 로봇의 3 s 스캔 확인 포함). 새 값은 `source: "vlm"` 하나다. 로봇은 스캔이 자세와 맞는지 **직접 확인한 뒤에만** 받고, 안 맞으면 거절한다. TTL이 지나면 답은 사라지고 요청은 다시 열린다. VLM은 **제안만** 하고 규칙(좌표 범위, 차선 그래프 위에 있는가, 직전 자세와의 거리)이 판정하며 로봇 스캔이 확인한다.
8. **VLM 자세 계약은 D-492와 따로다.** `pose_hint` VLM은 **AI PC**(D-492 호스트)에서 돌린다(사용자 결정, 2026-10-09). 그 PC 주인의 동의는 아직 필요하다. D-492의 `{thing, confidence}`는 "무엇이 막나"이고 자세가 아니다. 위치는 별도 계약 `pose_hint {x, y, yaw, frame, confidence, evidence}`로 두고, 같은 서버·같은 게이트를 쓰되 응답 스키마·파서·검증을 따로 둔다. [D-523](D-523-ai-pc-ask-returns-facts-or-candidates.md) 파서는 이 계약에 연결하지 않는다. 열린 질문 3 참조.

**나중 단계 (메모만)** — 여러 번 "조금 앞 / 조금 뒤"로 움직이며 한 걸음마다 위치를 확인하는 기동은 별도 ADR이다. 이 ADR의 신호는 그 기동에도 그대로 쓰이도록 `recovery`를 단계 이름이 아니라 "움직이는 복구"로 정의했다.

### 구현 노트: 위치 요청 첫 조각 (2026-10-09, `feat/d546-pose-request`, API v1.163)

결정 5–7을 설계에서 이렇게 좁혀 구현했다. 상태는 여전히 Proposed다. 호스트 pytest만 있고 SIM·DEVICE는 없다.

- **전송은 토픽이 아니라 CORE 읽기 경로다.** 설계의 `localization/request` 토픽 대신 `GET /api/v1/localization/request`(`LOCALIZE_ASSIST`, 없거나 만료면 404 `NO_REQUEST`)다. Fleet이 이미 로봇마다 REST로 읽고, 새 ROS 채널과 sensing 노드 변경이 없다. 이벤트 `localization.request`·`localization.request_cleared`가 함께 난다.
- **필드:** `{request_id, robot_id, reason: pose_stale|fleet_required, created_at, age_s, ttl_s, evidence}`. `ttl_s`는 30 s(열린 질문 2의 기본값). `evidence`는 `{phase, odom_pose {x, y, yaw, frame, stamp_ns, age_s}|null, lane {visible, confidence, error, quality_reason, stamp}|null}`이고 카메라 프레임은 싣지 않는다. `since`는 `created_at`+`age_s`로 대신한다. 같은 사유로 열려 있는 동안은 `request_id`·`created_at`을 유지하고 증거만 갱신한다. `ttl_s`가 지나면 사라지고 lane_return이 다음 틱에 새 `request_id`로 다시 연다.
- **언제 연다:** lane_return이 `fleet` 단계(`fleet_required`, 즉시)이거나, `pose_stale` HOLD가 1 s 넘게 이어질 때(`POSE_STALE_ASK_S`; odom 한 샘플 누락은 요청이 아니다). lane_return의 다른 틱, line follow 리셋·OFF, 수락된 결정은 닫는다. 로봇은 그동안 기존 HOLD로 선다(`recovery`는 HOLD라서 없다).
- **답과 재개:** Fleet은 기존 `POST /localization/decision`으로 답하고 `request_id`를 그대로 싣는다. 로봇의 3 s 스캔 확인이 통과해 `localization.result accepted`가 오고 그 `request_id`가 열린 요청의 id이며 Fleet이 보낸 결정일 때만 CORE가 요청을 닫고(사람의 initialpose·homing 결과는 닫지도 RESUME하지도 않는다), `fleet` 단계였다면 기존 D-407 `RESUME`(`by: fleet_pose`)으로 차선 확인을 다시 연다. RESUME이 거절되면(스캔 없음 등) 요청이 다음 틱에 새로 열린다. `pose_stale`만이었다면 odom 증거가 돌아오는 즉시 lane_return이 이어간다. 결정 TTL은 `ttl_s` 5 s(로봇이 수신 시각부터 센다).
- **Fleet 답의 순서 (결정 6):** (a) 천장 카메라 지도 자세 — `MapPoseService.arbitrated_pose`가 `LOCALIZED`이고 기준 sighting이 2 s 안일 때만(`DEGRADED`·`UNKNOWN`·낡은 기준·로봇 자신의 odom 자세는 쓰지 않는다). `source: overhead`, `cues: [overhead]`. D-257 5 개정(아래)에 따라 `--localization-overhead-cue`가 기본 켜짐이고 `--no-localization-overhead-cue`로 끈다. (b) 로봇이 `CANDIDATES`이고 D-395 중재기가 결정할 수 있으면(`Arbiter.pending`) 중재기에 맡긴다(`source: candidate`는 기존 경로가 보낸다). (c) `fleet.localization.pose_request.resolve_pose_with_model` — **구현하지 않았고 늘 `None`을 돌려준다.** 결정 8(VLM, AI PC)이 들어올 자리이고 `source: "vlm"`도 아직 없다. (d) 아무것도 못 내면 콘솔 배지 "위치 확인 필요"(`needs_human`)를 켠다. `fleet_required`는 CORE가 이미 D-407 정지 요청을 올린 상태이므로 콘솔에는 둘 다 보인다. 같은 요청은 8 s(결정 TTL 5 s + 스캔 확인 3 s) 뒤에야 다시 답하고, 3번 답해도 요청이 열려 있으면(로봇이 거절했거나 실패) `needs_human`으로 올리며 lane_return이 놓을 때까지 다시 답하지 않는다. `ttl_s`가 지난 요청은 무시한다.
- **이 조각에 없는 것:** 요청 중 LCD `Waiting for position`·`caution` 신호(결정 5의 표시), `source: vlm`, 차선 그래프 제약(결정 6 ③), 장치·SIM 수용. 신호 쪽 결정 1–4a와는 파일이 겹치지 않는다.
- **Safety-Review:** line_follow/recovery와 localization을 건드린다(`python tools/harness/safety_review.py main HEAD` 결과는 PR/보고에 적는다).

### 개정 제안: D-257 5 (2026-10-09, 사용자 결정, 미수락)

천장 카메라는 로봇의 위치 요청(결정 5)에 **믿을 수 있을 때** 답할 수 있다: 지도 자세가 `LOCALIZED`이고 기준 sighting이 2 s 이내일 때. 답은 `source: overhead` 결정이고 **로봇의 3 s 스캔 확인이 받을지 정한다.** 이 ADR이 Accepted가 될 때 D-257 5 본문에 옮긴다. 사용자 결정으로 `--localization-overhead-cue`는 기본 켜짐이다(끄기: `--no-localization-overhead-cue`). 이 플래그는 중재기·감시의 sighting 단서도 함께 켠다.

### 개정 목록 (수락 뒤 적용)

- **D-395:** 새 `localization/request`와 `source: "vlm"`을 더하고, "lane_return에는 연결 안 됨" 문장을 "결정 5로 연결된다"로 바꾼다. 장치 기본값 꺼짐은 그대로다.
- **D-468:** 신호 의무를 더한다 — RECOVERING 동안 `recovery` 필드·앰버 램프·(후진 시) 경고음. `fleet_required`가 D-407 경로 외에 결정 5의 요청도 올린다.
- **D-492:** 자세는 D-492의 범위가 아니라고 명시하고 결정 8의 별도 계약을 가리킨다.

### 열린 질문

3. `pose_hint`의 모델·프롬프트·프레임 정의. 실행 위치는 AI PC(D-492 호스트)로 정했고 그 PC 주인의 동의가 아직 필요하다.
2. `localization/request`의 `evidence`에 카메라 프레임을 실을지(대역·개인정보)와 TTL 기본값.
3. 장치 수용: 앰버 1.5 Hz와 1 kHz 80 ms가 현장 소음에서 들리고 보이는가(SIM 불가, DEVICE).
4. 신호가 켜진 채 `lamp_pattern` C 도우미를 새 릴리스로 배포하기 전까지 옛 도우미를 가진 로봇은 램프가 빠진다 — 릴리스 순서(도우미 먼저)로 충분한가.
