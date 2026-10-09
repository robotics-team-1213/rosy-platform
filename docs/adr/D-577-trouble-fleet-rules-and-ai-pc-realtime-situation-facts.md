## D-577 문제 상황의 로봇은 내버려 두지 않는다 — Fleet 판단기는 기본으로 켜져 차선 상실에도 답하고, AI PC 상황 서비스는 실시간으로 교착·정체·추론 불일치를 찾아 사실만 올리며, 답은 Fleet 규칙이 고르고 CORE가 다시 확인한다

**Status:** Accepted (2026-10-09, 사용자: "D-577을 만들고 진행해"). 사용자 답(2026-10-09): 열린 질문 1 — 비전 정체 사실의 그림자는 지금부터 연다(소유자 동의 조건). 열린 질문 2 — 사람 알림은 지금은 콘솔 안에만 둔다(휴대폰·메신저 없음). 이 수락은 (a) 구현(판단기 기본 켜짐)을 승인한다. 등록 로봇 resolver 자격 발급, `recovery_local_enabled`, `ai_facts_acting`, `ai_vision`, AI PC 상주 서비스 설치, Qwen 상주, Tailscale 정책 변경, 실기 활성화는 여전히 로봇별·단계별 사용자 승인이다. 구현 계획은 [docs/plans/2026-10-09-d577-trouble-fleet-ai-pc-realtime.md](../plans/2026-10-09-d577-trouble-fleet-ai-pc-realtime.md)다. 구현 단계 (a)·(g)·(i)는 Safety-Review 대상이다.

사용자 지시(2026-10-09):
- "문제상황에서 fleet으로 해서 서로 소통하고 ai pc가 상황을 판단해주는 로직이 있어야지, 그냥 두는게 아니라"
- "교착상태나 추론이나 이런것들이 문제가 될 수 있어서 이런 문제를 해결하기 위해서 아예 ai pc 에서도 실시간으로 이를 파악하고 처리할 수 있는 방안도 필요해"

**고치는 결정:**
- [D-438](D-438-fleet-stuck-resolver-rules-model-human.md) §2: 차선 상실 규칙 R3의 조건을 좁히고 R5를 더한다(1항). 구현 메모의 "`--stuck-resolver` 켤 때만"을 기본 켜짐으로 바꾼다(2항). §3의 "Fleet은 그 장을 저장하지 않는다"에 메모리 한정 예외 하나를 더한다(8항).
- [D-503](D-503-autonomy-chain-facts-and-exception-queue.md) 8·9항의 순서: 결정론 분석기와 그림자 기록은 9항 트리거를 기다리지 않는다. 비전 사실의 **그림자**도 기다리지 않는다(소유자 동의 조건). 비전 사실이 규칙 입력이 되는 것(D-492 R4)은 여전히 V0·V1과 이 ADR 7항의 재생 관문 뒤다(6항, 아래 「열린 질문」 1).
- [D-523](D-523-ai-pc-ask-returns-facts-or-candidates.md) 4항: "AI PC 소켓 없음"을 이 ADR의 전송(4항)으로 연다. 정체 파서·후보 파서의 출력 규칙은 그대로다.
- [D-568](D-568-compute-pool-headroom-placement.md) 4항: AI PC 풀 여유 계산에 상황 서비스 예약분을 뺀다(10항).

잇는 결정: [D-2](D-2-cmd-vel.md)·[D-18](D-18-rosy-core.md)(CORE만 최종 `/cmd_vel`) · [D-395](D-395-fleet-assisted-localization.md)(`needs_human`) · [D-407](D-407-lane-stuck-recovery-console-then-local.md)(막힘 질문·다섯 답·재검사) · [D-430](D-430-safety-as-a-separate-concern.md)(안전 분리) · [D-434](D-434-model-pc-and-site-pc-roles.md)(PC 역할) · [D-492](D-492-d438-vision-tier-local-qwen-ai-pc-gated.md)(정체 사실, V0·V1) · [D-511](D-511-fleet-lane-compliance-watch-and-correction-cue.md)(차로 준수) · [D-516](D-516-offline-decision-model-replay-boundary.md)(Fleet 결정, AI PC 추론, CORE 재확인) · [D-517](D-517-multi-robot-lane-traffic.md) 5항(M4 교착·인계) · [D-540](D-540-fleet-console-structure-v2.md)(예외 큐 펼침, 이름 있는 운영자) · [D-541](D-541-core-fleet-trip-lease.md)(trip lease) · [D-573](D-573-crosswalk-stop-look-cross.md)(횡단보도 막힘은 사람)

### Context

1. **계기(2026-10-09 22:20 KST).** 9dfk(`rosy_41`, release 2026.10.09-064)가 CAMERA_LINE에서 `camera_line_not_visible`로 약 7 s HOLD한 뒤 D-407 로컬 `stuck_back_off`(v = −0.03)를 하고 멈췄다. 아무도 답하지 않았다. 로봇 녹화 `20261009T130633Z_rosy_41`(10.6 s)가 있다. HOLD가 `recovery_ask_s`(15 s)보다 짧게 끝났으므로 CORE가 관제 연결 없음(`no_console`)으로 본 경로로 보인다.
2. **이 저장소 기준으로 답이 없었던 이유는 셋 이상이다.** 어느 하나만 고쳐도 다음 것에 막힌다.
   - 판단기는 `fleet console --stuck-resolver`를 줄 때만 돈다(`operations/fleet/fleet/cli.py`). 기본은 꺼짐이다.
   - 9dfk는 등록 로봇(D-361)이다. 판단기 클라이언트는 `robots.yaml`의 `resolver_token`으로만 생기므로 막힘은 `no_resolver_token`으로 사람에게 간다. D-503 6항(등록 로봇의 추가 자격)은 코드에 없다(`robot_enrollment_credentials` 없음).
   - CORE가 막힘 원인으로 보내는 값은 `camera_line_not_visible`이 아니라 `lane_lost`다(`stuck_wiring.py`). 규칙은 `lane_lost`에 R3 `BACK_AND_RETRY` 하나뿐이고, 로컬 후진이 `recovery_max_attempts`(2)를 다 쓰면 후보가 없어 `no_rule`이다.
   - 사람 단계는 예외 큐 행 하나다(`queues.js` "판단 요청"). 콘솔을 아무도 보지 않으면 알림이 없고, 기한도 없다.
3. **교착은 Fleet이 이미 본다.** D-517 M4의 `fleet/traffic/handover.py`가 매 주기 대기 그래프의 순환을 찾고 한 대에 `replan`, 나머지에 `wait`, 모르면 `human`을 준다. 순환 판정은 "보유자 하나라도 기다리면 순환"으로 넓다. 입력 자세가 낡거나, `wait`로 표시된 로봇이 실제로 움직이거나, 순환이 풀렸다 다시 생기기를 되풀이하는 경우(livelock)는 표가 스스로 보지 못한다.
4. **추론 문제는 지금 아무도 감시하지 않는다.** 차선 관측(규칙 기반)과 학습 차선 그림자(D-356), LiDAR·IR 앞 거리, Fleet `MapPose`·현장 지도 페인트, Rosy Cam 자세가 서로 어긋나도 그 어긋남을 사실로 올리는 곳이 없다. D-511은 차로 준수 하나만 본다.
5. **AI PC는 공용이다.** Tailscale `ai`, RTX 5080 Laptop 16 GB, RAM 15 GB, 다른 사람의 작업이 돈다(D-492 4항, D-568 4항). D-568은 이 PC를 시험·시뮬레이션 풀에도 넣었다. Fleet 쪽에는 스트림 끝점이 없고, 읽기는 REST 폴링과 `GET /api/fleet/events?after_id=`(커서) 둘이다. AI PC로 가는 소켓은 없다(D-523 4항).

### Decision

1. **Fleet 판단기 규칙: 차선 상실(`lane_lost`)에도 답한다. 안전한 답만 낸다.** trip 로봇은 D-517 M4 그대로(R1 `WAIT`만, 나머지 사람)다. 아래는 trip이 아닌 로봇이다.
   - **R3 `lane_lost_back_off` = `BACK_AND_RETRY`는 아래가 모두 참일 때만.** 로컬 복구 켜짐, 시도 수가 `recovery_max_attempts` 미만(D-438 그대로), Fleet이 아는 동료 로봇의 몸이 뒤 띠(`resolver_peer_reach_m`, 기본 0.30 m) 안에 없음, 로봇이 횡단보도 구역(D-573) 안이 아님, 그 로봇의 `MapPose`가 `LOCALIZED`이고 `age_s` ≤ 2 s이거나 Fleet이 자세를 전혀 모름(모름이면 뒤 띠 판정은 CORE 재검사에만 맡긴다). 뒤 여유·사각·지나온 길은 CORE가 판정한다(D-407 §4). 판단기는 `rear_state`로 후진을 허락하지 않는다.
   - **Safety-Review 보완(2026-10-09, 구현 (a)).** R3 조건은 닫힌 쪽으로 읽는다. 자세: Fleet이 그 로봇의 목격 출처를 한 번도 가진 적이 없을 때만 `UNKNOWN`을 "모름"으로 본다. 출처가 있었는데 `UNKNOWN`(odom 낡음·anchor 잃음)이면 R5 `pose`다. 뒤 띠: 자신과 동료 모두 D-395 신뢰 지도 자세(`LOCALIZED`·map 또는 미보고 legacy)로만 잰다. 동료가 온라인인데 어느 한쪽 자세가 없거나 신뢰되지 않으면 R5 `peer_unknown`이다. 횡단보도: CORE가 `line_follow.crosswalk`를 보고하지 않으면(지금의 모든 CORE) R5 `crosswalk_unknown`이다. D-573 구현은 구역 밖에서 `crosswalk: null`, 안에서 객체를 내야 R3가 열린다.
   - **새 R5 `lane_lost_hold` = `WAIT` 후 바로 사람.** R3 조건이 거짓이면(동료가 뒤에 있음, 횡단보도, 시도 소진, 로컬 복구 꺼짐) `WAIT`을 보내고 같은 주기에 `lane_lost_hold:<이유>`로 큐에 올린다. `WAIT`은 CORE를 `console_wait`로 두어 로컬 후진 타이머를 멈춘다. 동료 로봇 쪽으로의 무인 후진을 막는 것이 목적이다. R5는 규칙 예산을 쓰지 않는다(멈추는 답이고 한 막힘에 한 번).
   - **`RESUME`은 `lane_lost`에 어떤 단계도 보내지 않는다(D-438 §3 그대로).** 차선 증거 없이 상실 래치를 풀기 때문이다. `ABORT`·`MANUAL`은 사람만 고른다.
   - 원인 문자열은 CORE 막힘 `cause`(`obstacle_ahead`|`lane_lost`)만 본다. HOLD 사유(`camera_line_not_visible` 등)는 큐 표시와 에피소드 기록에만 쓴다.
2. **판단기는 기본으로 켠다.** `fleet console`의 판단기는 기본 켜짐이고 `--no-stuck-resolver`로 끈다(`--stuck-resolver`는 호환용으로 받고 아무것도 바꾸지 않는다). 켜져도 **로봇마다 resolver 자격이 있어야 답한다.** 자격이 없으면 지금처럼 `no_resolver_token`으로 사람에게 간다. 그래서 기본 켜짐은 "사람에게 이유와 함께 올라간다"를 보장할 뿐 실제 로봇을 새로 움직이지 않는다.
   - 실제 로봇에서 사용자가 승인할 때까지 꺼진 채 남는 것: 로봇별 resolver 자격 발급(D-503 6항, 한 대씩), 로봇별 `recovery_local_enabled`(D-495 승격 규칙), AI 사실의 행동 단계 `ai_facts_acting`(기본 `false`, 7항), 비전 질의 `ai_vision`(기본 `off`, 6항).
3. **AI PC 상황 서비스(`rosy-situation`)는 상주 프로세스다.** 배치가 아니다. 하는 일은 셋이다: Fleet 상태를 따라 읽고, 문제를 먼저 찾고, **사실**(값·신뢰도·근거 id)만 Fleet에 올린다. 결정은 Fleet 규칙, 실행과 마지막 확인은 CORE다(D-516). 서비스는 로봇·CORE 주소, 로봇 토큰, Fleet 쓰기 권한(사실 올리기 하나 외)을 갖지 않는다.
   - **사실 모양**은 D-503 2항이다: `kind`, `robot_ids`, `value`, `confidence`(0–1), `evidence`(Fleet 사건 id·막힘 `stuck_id`·교통 표 세대·프레임 `captured_at`/순서번호·자기 입력 로그 줄 번호), `source`(`analyzer:<이름>@<버전>` 또는 `vlm:<profile_id>`), `observed_at`, `ttl_s`. 명령 단어(`WAIT`·`RESUME`·`BACK_AND_RETRY`·`YIELD`·`ABORT`·`MANUAL`·`STOP`·`GO`)는 키로도 값으로도 받지 않는다. Fleet이 거절한다(D-523 2항과 같은 규칙).
   - **사실 종류(처음):** `wait_cycle_confirmed`·`wait_cycle_stale_input`·`waiting_but_moving`·`livelock`·`stalled`·`unknown_occupancy_long`(교착, 3항), `lane_obs_vs_range`·`lane_conf_collapse`·`shadow_active_drift`·`pose_vs_paint`·`pose_sources_disagree`(추론, 4항), `obstacle_identity`(D-492 정체, 6항). 종류를 더하는 것은 이 ADR 개정이다.
4. **전송 — 읽기는 AI PC가 끌어오고, 사실은 AI PC가 올리고, 프레임은 Fleet이 밀어 준다.**
   - **읽기(AI PC → Fleet):** `GET /api/fleet/state`·`/api/fleet/traffic`·`/api/fleet/line-stuck`을 1 Hz로, `GET /api/fleet/events?after_id=`를 커서로 읽는다. 새 스트림 끝점을 만들지 않는다. 막힘 사건이 오면 다음 폴링을 앞당긴다. 공유 gather(D-438 구현 메모)를 쓰므로 로봇에 더 묻지 않는다.
   - **사실(AI PC → Fleet):** `POST /api/fleet/ai/facts` 하나. 한 요청에 사실 최대 32개, 본문 64 KiB, 초당 2 요청(넘으면 429, AI PC는 가장 오래된 사실부터 버린다, 대기열 256). Fleet은 스키마·명령 단어·`ttl_s`(분석기 ≤ 5 s, 비전 ≤ 8 s)·`observed_at` 미래 시각을 검사하고 통과한 사실을 메모리 표와 감사(10항)에 둔다. 이 경로는 비상정지·정지 경로와 잠금·작업을 공유하지 않는다.
   - **비전 질의(Fleet → AI PC):** 막힘 하나에 Fleet이 로봇 미리보기 한 장을 받아(D-438 §3·D-492 6항의 촬영 시각 규칙) `POST <ai>/v1/identity`로 보낸다. AI PC는 로봇 카메라에 직접 닿지 않는다. 응답은 D-523 정체 파서를 지난다.
   - **상태(AI PC → Fleet):** 2 s마다 `POST /api/fleet/ai/heartbeat`(서비스 버전, 적재된 `ModelProfile` id, `owner_mode`, GPU·메모리 사용, 입력 지연). 6 s 동안 없으면 Fleet은 AI를 `absent`로 본다.
   - **인증:** AI PC는 Fleet 사이트 사용자 파일(`--users-file`)의 새 역할 `ai_observer`로 들어온다. 이 역할은 viewer 읽기와 위 두 POST만 통과한다. Fleet → AI PC는 `private/`의 bearer 하나다. 망은 tailnet이다: AI PC(`hosts` 별칭 한 대) → 관제 PC Fleet 포트 하나, 관제 PC → AI PC 서비스 포트 하나만 grant 한다. AI PC → 로봇 grant는 두지 않는다. 서비스와 Ollama는 AI PC의 Tailscale 주소에만 묶는다(D-492 4항).
5. **지연 예산과 비는 경우.**
   - 결정론 분석기 사실: 조건이 생긴 뒤 **2 s** 안(1 Hz 폴링 + 계산). 비전 정체 사실: 막힘이 열린 뒤 **8 s** 안(D-492), 판단기가 쓰는 마지막 시각은 `recovery_ask_s` − 2 s다(설정 검사가 거부, D-438 §3과 같은 방식).
   - Fleet은 `ttl_s`가 지난 사실, `absent` 동안의 사실, 프로파일이 승인 목록에 없는 사실을 없는 것으로 본다. **AI가 없으면 지금 동작이다: 규칙 → 사람.** 판단기·교통 표·비상정지·정지는 AI 응답을 한 번도 기다리지 않는다. AI 호출은 별도 작업에서 시간 제한과 함께 돈다.
   - 큐에는 AI 상태 한 칩만 둔다: "AI 판단 있음 / 없음(꺼짐·바쁨·소유자 사용 중)".
6. **모델과 단계.**
   - 교착·정체·추론 불일치는 **결정론 분석기**(순수 파이썬, 모델 없음)가 낸다. GPU를 쓰지 않는다. 같은 입력 로그면 같은 사실이다.
   - 장면 정체는 D-492의 `qwen3-vl:8b-instruct`(Ollama, digest·프롬프트 id 고정)다. 막힘 원인 `obstacle_ahead`에서만 묻는다(D-492 1항). `lane_lost`에는 묻지 않는다.
   - **단계는 셋이다.** `shadow`(사실은 감사·큐 표시에만, 규칙 입력 아님) → `advisory`(큐 행에 사실과 근거를 띄우고 사람 알림을 앞당김, 규칙 입력 아님) → `acting`(7항의 보수적 규칙 입력). 분석기는 `shadow`로 시작한다. 비전 사실은 소유자 동의 뒤 `shadow`까지 지금 열고, `advisory` 이상은 D-492 V0·V1과 7항 관문 뒤다.
7. **행동 단계의 규칙 — AI 사실은 Fleet을 더 조심스럽게만 만든다.**
   - `acting`의 사실이 바꿀 수 있는 것: (1) 사람 상승을 앞당긴다(`ai:<kind>`), (2) 판단기의 후진 답(R2·R3)을 건너뛰고 R5 `WAIT`으로 바꾼다, (3) M4의 `replan`을 보류하고 `human`으로 돌린다, (4) 해당 로봇의 차선 주행을 기존 정지 경로로 멈춘다. 이것뿐이다.
   - 바꿀 수 없는 것: 블록 허가·해제, 통행권, `RESUME`·`BACK_AND_RETRY`·`YIELD`를 새로 내기, 비상정지 해제, 속도 올리기, 새 하향 통로. 감속은 이미 있는 Fleet 상한 경로(교통·대형)가 그 로봇에 있을 때만 쓰고, 없으면 (4) 정지와 사람이다. 새 감속 하향 통로는 별도 ADR·Safety-Review다.
   - **엇갈리면 더 제한적인 쪽이 이긴다.** Fleet 표가 "순환 없음", AI가 `wait_cycle_confirmed`면 Fleet은 블록을 바꾸지 않고 큐에 올린다. Fleet 표가 `replan`, AI가 `wait_cycle_stale_input`이면 `replan`을 보류하고 사람에게 간다. AI가 "괜찮다"는 사실은 없다. 그런 사실 종류를 만들지 않는다.
   - **켜는 관문:** 사실 종류마다 따로 `ai_facts_acting.<kind>`. 조건은 (1) 재생 평가(모델 PC, 저장 입력 로그 + 녹화 + `20261009T130633Z_rosy_41`)에서 주입한 문제의 재현율 ≥ 0.9, 문제 없는 구간의 오경보 ≤ 시간당 1건, (2) Gazebo 다중 로봇 시나리오(모델 PC 또는 AI PC, 노트북 아님) 통과, (3) `shadow` 3 운행일 동안 실제 오경보 ≤ 운행일당 2건, (4) 사용자 승인. 비전은 여기에 D-492 V0·V1이 더해진다.
8. **사람 단계.** 예외 큐(D-493 `attentionItems`, D-540 펼침)가 유일한 자리다.
   - 행: 로봇, 원인·HOLD 사유, 판단기가 한 일과 상승 사유, AI 사실(종류·신뢰도·출처·나이), 근거 이미지. 근거 이미지는 Fleet이 그 막힘에서 받은 한 장이다. **Fleet은 그 장을 막힘이 열린 동안 메모리에만 둔다**(막힘마다 1장, 디스크·버스·사건 금지, 막힘이 닫히면 버림). D-438 §3을 이만큼만 고친다. 오래 남는 것은 D-379 녹화다.
   - 답(다섯 답)은 이름 있는 운영자만(D-540 ②, `require_named_operator`). 펼치면 사람이 맡는다(D-438 §1).
   - 알림: 행이 생기면 콘솔 소리와 브라우저 알림. 30 s 답이 없으면 같은 알림을 다시 하고 행을 맨 위 위험 단계로 올린다. 기한이 지나도 **로봇은 HOLD**다. 무응답으로 움직이는 답은 없다. 휴대폰·메신저 알림은 후속이다(열린 질문 2).
   - 횡단보도(D-573 `crosswalk_blocked`)와 위치 확인(D-395 `needs_human`)은 같은 큐에 같은 모양으로 오르고 AI 사실은 참고 칸에만 붙는다. `CROSS_CONFIRMED`는 사람만 낸다.
9. **안전.** 비상정지와 정지는 언제나 열려 있다(콘솔·로봇 화면·하드웨어). AI PC는 정지를 늦추지 못하고 풀지 못한다. CORE가 최종이다(D-18): 모든 답은 D-407 재검사를 지나고 거절은 기록된다. AI 출력은 Fleet 규칙과 CORE 재검사 없이 움직임이 되지 않는다. AI 출력은 안전 기능이 아니다(D-430). **Safety-Review 범위:** 1항 R3 조건·R5, 2항 기본 켜짐의 실제 로봇 효과, 7항 행동 단계 매핑과 엇갈림 규칙, 판단기 `WAIT`이 trip lease(D-541)·통행권 정지와 겹치는 경우.
10. **AI PC 공용 사용과 기록.**
    - 소유자 동의 없이 상주시키지 않는다. `owner_mode`는 AI PC의 로컬 파일(소유자만 쓴다)이다: `available`(분석기 + 비전), `shared`(분석기만, GPU 쓰지 않음), `owner_busy`(heartbeat만). 바꾸면 다음 heartbeat에 Fleet이 안다.
    - systemd 단위 `rosy-situation.service`: `MemoryMax=2G`, `CPUQuota=100%`, `Nice=10`. 비전을 켜면 Ollama 모델 상주(`keep_alive` 무기한, VRAM 약 8 GB)가 더해진다. D-568 풀은 AI PC의 여유에서 이 예약분을 빼고 잰다.
    - 감사: Fleet `fleet_ai_facts`(`--tasks-db` 같은 파일, 사실과 그 결과 — 규칙 입력이 됐는지, 사람이 무엇을 골랐는지) 행. AI PC는 자기 입력 로그(받은 상태 JSON, 프레임 제외)와 출력 사실을 JSONL로 7일 보관한다. 이 입력 로그가 재생 평가의 말뭉치다.
    - 프레임 프라이버시: 프레임은 사이트 밖으로 나가지 않는다. AI PC는 질의한 프레임을 디스크에 쓰지 않는다. 입력 로그에는 프레임 대신 `captured_at`·순서번호·sha256만 남는다.

### Alternatives

- **AI PC가 직접 판단(답)을 낸다.** D-503 1항 실험 v1에서 47/47이 같은 답이었다. D-516·D-523이 거절했다.
- **AI PC가 로봇 카메라·CORE를 직접 읽는다.** 로봇 토큰과 grant가 AI PC로 늘고, 공용 PC가 로봇 쪽 공격면이 된다. Fleet이 한 장씩 밀어 주는 쪽이 범위가 좁다.
- **Fleet에 웹소켓/SSE 스트림을 새로 만든다.** 지금 1 Hz 폴링 + 사건 커서로 2 s 예산을 맞춘다. 예산을 못 맞출 때 연다.
- **분석기를 Fleet 안에 둔다.** 결정론 분석기는 Fleet 안에서도 돈다. AI PC에 두는 이유는 관제 PC 부하(D-434 사이트 스택 전용)와 비전·분석을 한 증거 묶음으로 내기 위함이다. 관제 PC 여유가 충분하다고 측정되면 분석기만 Fleet으로 옮길 수 있다(같은 사실 계약).
- **D-503 9항 트리거를 그대로 기다린다.** 사용자 지시가 실시간 처리를 요구하고, 9항이 필요로 하는 정체 표본도 그림자 기록에서 나온다. 행동 단계는 기다린다.

### Consequences

- 판단기가 기본으로 돌고, 차선 상실 막힘은 후진(조건 충족) 또는 `WAIT` + 사람으로 끝난다. 무응답 HOLD는 큐·알림이 있는 HOLD가 된다.
- 등록 로봇은 D-503 6항 자격이 생기기 전까지 여전히 사람에게 간다. 이 자격이 (a) 단계의 실효를 정한다.
- AI PC에 상주 서비스가 하나 생기고, 공용 PC의 소유자 모드가 Fleet에 보인다. AI가 없을 때의 동작은 지금과 같다.
- Fleet에 POST 두 개, 역할 하나, 표 하나, 큐 칸이 생긴다. API Reference 행과 typed schema는 구현 변경에서 정한다(D-18).

### Verification

- 이 기록은 문서다. `python tools/harness/rosy_harness.py lint`는 형식 증거일 뿐이다.
- 단계별 시험(먼저 실패해야 함), 주인, Safety-Review는 구현 계획 문서에 있다.

### 열린 질문

1. 비전 정체 사실의 **그림자**를 D-503 9항 트리거 전에 여는가(이 ADR의 기본) 아니면 9항을 그대로 기다리는가.
2. 사람 알림을 콘솔 밖(휴대폰·메신저)으로 보낼 채널이 필요한가.

### 남은 항목 (Safety-Review 2026-10-10, 구현 (a))

1. 뒤 띠는 `localization`을 보고하지 않는 LEGACY 로봇의 odom 자세도 받는다. D-573이 `crosswalk: null`을 내서 R3가 열리기 전에 닫아야 한다.
2. R5 전송이 실패한 뒤 다음 주기에 R3 조건이 모두 참이면 R3가 고를 수 있다.
3. Fleet 정지(작업 취소)로 끊긴 R5 전송은 사람에게 올라가지 않는다.

**Related:** D-2, D-18, D-356, D-361, D-379, D-395, D-407, D-430, D-434, D-438, D-492, D-493, D-495, D-503, D-511, D-516, D-517, D-523, D-540, D-541, D-568, D-573.
