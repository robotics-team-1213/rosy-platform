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
   - **Safety-Review 보완(2026-10-09, 구현 (a)).** R3 조건은 닫힌 쪽으로 읽는다. 자세: Fleet이 그 로봇의 목격 출처를 한 번도 가진 적이 없을 때만 `UNKNOWN`을 "모름"으로 본다. 출처가 있었는데 `UNKNOWN`(odom 낡음·anchor 잃음)이면 R5 `pose`다. 뒤 띠: 자신과 동료 모두 D-395 신뢰 지도 자세(`LOCALIZED`·map 또는 미보고 legacy)로만 잰다. 동료가 온라인인데 어느 한쪽 자세가 없거나 신뢰되지 않으면 R5 `peer_unknown`이다. 횡단보도: CORE가 `line_follow.crosswalk`를 보고하지 않으면(지금의 모든 CORE) R5 `crosswalk_unknown`이다. D-573 구현은 구역 밖에서 `crosswalk: null`, 안에서 객체를 내야 R3가 열린다. (2026-10-10 개정: CORE는 게이트와 무관하게 늘 보고하고, 모를 때 내는 `{state: unknown}`도 R5 `crosswalk_unknown`이다. 현장 지도 `crosswalks[]`가 기준이다: 신뢰 지도 자세가 다각형에서 `stuck_lane_lost.CROSSWALK_REACH_M`(0.29 m) 안이면 R5 `crosswalk`, 지도에 횡단보도가 있는데 신뢰 지도 자세가 없거나 출처 없는 `UNKNOWN`이면 R5 `crosswalk_unknown`이다. D-573 6항 보고 개정.)
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

1. ~~뒤 띠는 `localization`을 보고하지 않는 LEGACY 로봇의 odom 자세도 받는다.~~ **닫힘(2026-10-10, `feat/stuck-5s-fleet-ai`).** 뒤 띠는 이제 자신과 동료 모두 `localization`을 보고하는 신뢰 지도 자세로만 잰다. 동료가 온라인인데 어느 한쪽이 LEGACY(odom)면 R5 `peer_unknown`이다(`stuck_lane_lost.peer_behind`). D-573 횡단보도 관문을 켜도 R3가 odom 자세로 열리지 않는다.
2. ~~R5 전송이 실패한 뒤 다음 주기에 R3 조건이 모두 참이면 R3가 고를 수 있다.~~ **닫힘(2026-10-10, `feat/crosswalk-null-outside-zone`).** 한 막힘에 R5를 보냈으면 판단기는 그 막힘의 다시 보내기를 같은 R5(`WAIT`, 같은 `<cause>_hold:<이유>`)로만 한다. R3·R6·AI 답이 그것을 대신하지 않는다(`_Chain.held`).
3. ~~Fleet 정지(작업 취소)로 끊긴 R5 전송은 사람에게 올라가지 않는다.~~ **닫힘(2026-10-10, 같은 브랜치).** 응답 전에 Fleet이 멈추면 결과 `STUCK_DECISION_OUTCOME_UNKNOWN`을 남기고 그 R5의 사람 행(`<cause>_hold:<이유>`)도 올린다(`stuck_resolver_loop._answer`). 다음 Fleet이 막힘을 새로 보면 같은 규칙으로 다시 판단한다.

### 개정 (2026-10-10): 5 s 무동작 막힘(`no_motion`)과 등록 로봇 자격

사용자 지시(2026-10-10): "로직에서 우리가 멈추게 되거나 어떤 상황 때문에 전혀 안 움직이는 게 5초 이상 지속되면, 이를 fleet 서버를 통해서 ai pc에서 이걸 어떻게 처리할지에 대해서 판단받고 이를 처리하게 하는 등의 로직이 필요할 것 같아. 신호등 진입을 관제 PC의 신호등을 보고 하듯이." 조정 세션은 이 지시를 9dfk(`rosy_41`)·8kcn(`rosy_40`)의 차선 주행 경로에 대한 사용자 승인으로 전했다.

1. **규칙.** CORE 새 원인 `no_motion`([D-407](D-407-lane-stuck-recovery-console-then-local.md) 개정 2026-10-10)은 1항의 `lane_lost`와 같은 조건을 쓴다: 모두 참이면 R6 `BACK_AND_RETRY`(R3와 같은 후진·재판단, 규칙 예산을 쓴다), 하나라도 거짓이면 R5 `WAIT` + 사람(`no_motion_hold:<이유>`). `RESUME`·`YIELD`는 나가지 않는다. 원인 문자열만 본다는 1항의 규칙에 `no_motion`이 더해진다. 상세(HOLD 사유)는 표시에만 쓴다.
2. **등록 로봇 자격(2항, D-503 6항).** 현장 설정 `fleet.stuck_resolver.enrolled_robots`(로봇 id 목록)에 적은 등록 로봇은 판단기가 Fleet이 D-361 등록 때 받은 CORE 자격(operator, `STUCK_DECIDE` 포함)으로 답한다. 별도 `stuck_resolver` 토큰을 새로 발급하지 않는 지름길이다: 판단기 코드는 `line_stuck_decision`만 부르고 `MANUAL`을 고르지 않지만, CORE 기록의 `principal_ref`는 Fleet의 등록 토큰 id가 된다. 기본은 빈 목록이고, 목록에 적는 것이 로봇별 승인이다. 이 개정은 `rosy_40`·`rosy_41`을 적는 것을 승인한다. 전용 최소 권한 자격은 후속이다.
   - **같은 날 보완(실주행).** 9dfk가 릴리스 077에서 `HOLD lane_departure`(IR 가운데가 고리 바깥 선 위)로 25 s 섰다. 두 로봇이 온라인이고 둘 다 `localization`을 보고하지 않으면(LEGACY) R6가 매번 R5 `peer_unknown`이 되어 막다른 길이었다. 그래서 **`no_motion`(R6)에 한해 동료 자세를 모르는 것은 막지 않는다.** 뒤 여유·사각·지나온 길은 후진 전과 중에 CORE D-407 §4 몸 재검사가 판정한다(LiDAR가 뒤의 로봇 몸을 본다). 신뢰 지도 자세로 뒤에 동료가 보이면(`peer_behind`) 여전히 R5다. 횡단보도·시도·로컬 꺼짐·자세 조건도 그대로다. `lane_lost`(R3)는 3항의 닫힌 규칙 그대로다.
3. **남은 항목 1 닫힘.** 위 「남은 항목」 1(LEGACY odom 자세)은 이 개정과 같은 브랜치에서 닫혔다. D-573 횡단보도 관문을 켜는 릴리스와 같이 가야 한다.
4. **AI PC.** AI 사실은 이 개정에서도 shadow다(6·7항 그대로). `rosy-situation`(구현 (c))의 분석기는 아직 비어 있어 `no_motion` 막힘에 대한 사실을 내지 않는다. 사람 단계 행에 사실을 붙이는 경로는 (c)의 `ai_facts[]` 그대로다. `ai_facts_acting`은 7항 관문(재생 평가·Gazebo·shadow 3 운행일) 전에는 켜지 않는다. 사용자 승인은 그 관문 하나를 채울 뿐이다.

### 개정 (2026-10-10, 오후): AI PC 판단 경로 — 분석기 사실이 Fleet 후진 답을 멈춘다

사용자 지시(2026-10-10): "로직에서 우리가 멈추게 되거나 어떤 상황 때문에 전혀 안 움직이는 게 5초 이상 지속되면, 이를 fleet 서버를 통해서 ai pc에서 이걸 어떻게 처리할지에 대해서 판단받고 이를 처리하게 하는 등의 로직이 필요할 것 같아. 신호등 진입을 관제 PC의 신호등을 보고 하듯이." 조정 세션은 이 지시를 9dfk(`rosy_41`)·8kcn(`rosy_40`) 차선 주행에서 AI PC 실시간 경로를 켜는 사용자 승인으로 전했다. 이 승인은 7항 켜는 관문의 (1)–(3)(재생 평가·Gazebo·shadow 3 운행일)을 이 두 로봇, 아래 두 종류에 한해 건너뛴다. 위 개정 4항의 "`ai_facts_acting`은 7항 관문 전에는 켜지 않는다"를 이만큼 고친다.

1. **분석기 (d) 첫 조각 `analyzer:stuck_scene@1`.** AI PC `rosy-situation`이 Fleet 폴링 스냅샷만으로 세 사실을 낸다(프레임 없음, 결정론). 3항 종류 목록에 `rear_blocked`·`path_blocked_by_robot`을 더한다.
   - `rear_blocked`: 열린 막힘의 `rear_state: blocked`(허브 사건), 또는 CORE가 후진을 `rear_blocked`로 거절한 뒤 로봇이 odom으로 0.05 m 넘게 움직이지 않은 동안(최대 120 s). 근거는 CORE 자신의 판정이다.
   - `path_blocked_by_robot`: 막힌 로봇의 앞 띠(R1과 같은 0.383 m × ±0.15 m)에 동료 몸이 있다. D-395 신뢰 지도 자세(보고된 `localization`, LEGACY 아님)로만 잰다. 로봇마다 다른 odom 원점을 비교하지 않는다.
   - `stalled`(기존 종류): 차선 주행이 켜져 있고 열린 막힘 없이 명령 0·이동 0.05 m 미만이 20 s. CORE가 5 s 보고에서 빼는 HOLD(저조도·과노출, 아래 4항)를 Fleet에 보이게 한다. shadow다.
2. **행동 단계(7항 (2)만).** 현장 설정 `fleet.stuck_resolver.ai_facts_acting`(로봇 id 목록, 기본 빈 목록)에 적은 로봇에서 `rear_blocked`·`path_blocked_by_robot` 사실은 `stage: acting`이다. 살아 있는 동안(`ttl_s` 3 s, 서비스 `present`) 판단기가 그 로봇에 보낼 후진 답(R2·R3·R6 `BACK_AND_RETRY`)은 R5 `WAIT` + 사람(`<cause>_hold:ai:<kind>`)이 된다. 다른 답을 새로 만들지 않는다. AI가 없거나 사실이 없으면 지금 규칙 그대로이고, CORE D-407 재검사도 그대로다. 이 개정은 `rosy_40`·`rosy_41`을 적는 것을 승인한다.
3. **AI PC 설치.** 사용자 단위 `rosy-situation.service`(`MemoryMax=2G`, `CPUQuota=100%`, `Nice=10`), `owner_mode` `shared`(분석기만, GPU 없음). 현장 사용자 파일에 `ai_observer` 주체 `ai-pc-situation` 하나. 서비스는 관제 PC의 `.local` 이름과 사이트 CA로 LAN을 통해 Fleet에 닿는다(tailnet grant 없음). 같은 PC의 다른 작업(SAM 작업자 GPU 약 2 GB, Nav2·rosbridge, 원격 pytest)을 건드리지 않는다. 비전(Qwen3-VL, 6항·D-492)은 V0·V1과 소유자 동의 전이라 설치하지 않았다.
4. **저조도·과노출 HOLD는 5 s 막힘 보고에 넣지 않는다.** CORE는 무효 영상에서 매 틱 복구를 초기화한다("Invalid vision cannot authorize obstacle back-off", D-407). 막힘으로 올리면 R6 후진이 나가므로 넣지 않고, 1항 `stalled` 사실로 Fleet에 보인다. 사람 단계 행으로 올리는 것은 CORE 변경(막힘 원인과 R5 전용 상세)이 필요한 후속이다.
5. **현장 관찰(2026-10-10 00:39–00:47Z, 릴리스 081).** 9dfk `stuck-d5b3c15f7783`(`obstacle_ahead`, 경기장 왼쪽 위 모서리)은 3 s 만에 R2 `BACK_AND_RETRY`를 받았고 CORE가 `rear_blocked`로 거절했다. 다른 후보가 없어 4 s 뒤 사람(`no_rule`)에게 갔고, 아무도 답하지 않아 20 s 뒤 스스로 풀렸다. 앞·뒤가 모두 막힌 모서리에서 남는 움직임은 제자리 회전뿐인데, 이것은 AI 사실이 만들 수 없는 답(7항)이고 별도 규칙·Safety-Review 대상이다. 8kcn `stuck-61efc8e8473d`의 R1 `WAIT`은 두 로봇 모두 LEGACY(odom) 자세에서 `peer_ahead`가 참이었기 때문이다. R1은 지금 odom 자세를 서로 비교하므로 동료가 없는데도 `WAIT`할 수 있다(남은 항목 4).

남은 항목에 더한다:

4. 판단기 R1 `peer_ahead`와 meet 규칙은 LEGACY 로봇의 odom 자세를 지도 자세처럼 쓴다. 현장 두 로봇은 모두 LEGACY이고 Fleet 지도 자세는 지금 `UNKNOWN`(천장 카메라 목격 없음)이다. R1은 신뢰 지도 자세로만 재야 한다. Safety-Review와 함께 고친다.

### 개정 (2026-10-10, 사용자 결정): AI PC 제안 → Fleet 검증 후 실행

사용자 결정(2026-10-10, 조정 세션 전달): "AI PC 제안 → Fleet 검증 후 실행". 이 결정은 **제안 통로 하나에 한해** 3항의 "사실만, 명령 단어는 거절"을 바꾼다. 사실 통로(`POST /api/fleet/ai/facts`)는 그대로 명령 단어를 거절한다.

1. **제안.** AI PC는 열린 막힘 하나에 CORE가 이미 받는 결정 단어 하나(`WAIT`|`BACK_AND_RETRY`|`YIELD`|`ABORT`|`RESUME`|`MANUAL`)를 이유·근거·신뢰도와 함께 `POST /api/fleet/ai/proposals`로 올린다(`ai_observer`, `ttl_s` ≤ 8 s). Fleet은 `fleet.stuck_resolver.ai_facts_acting` 로봇의 것만, AI가 `present`일 때만, 로봇마다 가장 새 것 하나만 메모리에 둔다.
2. **Fleet 검증(봉투만).** 판단기가 그 막힘을 처음 본 뒤 `ai_wait_s`(5 s) 동안 제안을 기다린다. 제안이 오면 한 번 판정한다: `stuck_id` 일치, 신선도(`ttl_s`), 원인별 허용 단어(`lane_lost`·`no_motion`: `WAIT`·`BACK_AND_RETRY`·`ABORT`; `obstacle_ahead`: 여기에 `RESUME`; `crosswalk_blocked`: 없음 — 사람), trip 로봇은 `WAIT`만, `BACK_AND_RETRY`는 R2·R3·R6와 같은 전제(로컬 복구 켜짐, 시도·규칙 예산, 횡단보도, 뒤 띠 동료(신뢰 지도 자세), 지도 자세 신선도, `rear_state: blocked` 아님), 같은 막힘에서 CORE가 AI 답을 거절한 적 없음. `YIELD`(Fleet meet 기하가 필요)와 `MANUAL`(사람에게 넘김)은 AI 제안으로 나가지 않는다. 통과하면 CORE에 그 결정으로 보낸다(`tier: ai`, `rule: ai`). AI의 `WAIT`은 R5처럼 사람 행도 올린다(`ai_wait:<reason>`).
3. **되돌아감.** 제안이 없거나 늦거나(5 s), 검증에 떨어지거나, CORE가 거절하면 지금 규칙(R1–R6)이 답한다. AI가 없으면 기다리지 않는다.
4. **감사.** 모든 제안의 판정(`forwarded` 또는 거절 이유)과 CORE 결과를 `fleet_ai_proposals`(`--tasks-db`)에 남기고, 보낸 답은 `fleet_line_stuck_answers`에 `tier: ai`로 남는다. `GET /api/fleet/ai`가 최근 판정 64개를 보인다.
5. **CORE가 최종이다.** 모든 답은 지금처럼 D-407 재검사를 지난다. AI 제안은 안전 기능이 아니다(D-430).
6. **AI PC 제안기(`analyzer:stuck_scene@1`).** 결정론이다: 뒤가 막혔으면(`rear_blocked`) 또는 앞에 로봇이 있으면 `WAIT`, 아니면 `BACK_AND_RETRY`. 막힘·결정·이유 조합마다 한 번 보낸다. 비전 모델은 아직 쓰지 않는다(D-492 V0·V1 전).

### 개정 (2026-10-10, 저녁, Safety-Review 대상): 소유자 동의 기록, AI 제안 관문 강화, 연동 상태

사용자 결정(2026-10-10): 현장 AI PC의 `rosy-situation`은 지금처럼 `shared` 모드로 돌고 `rosy_40`·`rosy_41`은 AI 실행(`fleet.stuck_resolver.ai_facts_acting`) 로봇으로 남는다. 대신 검사를 강화한다. AI PC 소유자 동의(D-492 4항)는 사용자가 2026-10-10에 주었다.

1. **AI 제안은 판단기 규칙과 같은 관문을 지난다.** 위 개정 2항의 "봉투만" 검사에서 `ABORT`·`RESUME`은 어떤 전제도 보지 않았다(`stuck_lane_lost.py`). 이제 AI는 Fleet을 더 제한적으로만 만든다.
   - `WAIT`은 봉투(원인별 단어, trip, CORE 거절 이력)만 본다.
   - 그 밖의 단어는 CORE가 `line_follow.crosswalk`를 보고하고 그 값이 null일 때만 보낸다(`crosswalk_unknown`·`crosswalk`). 횡단보도 안의 멈춘 로봇은 사람이 맡는다(D-573).
   - `ABORT`(차선 추종 끔, IDLE)는 위를 지나면 보내고, 같은 주기에 사람 행 `ai_abort:<reason>`을 올린다.
   - `RESUME`은 AI 단어가 아니다(어느 원인에서도 `word_not_allowed`). 규칙도 막힘에 `RESUME`을 보내지 않는다(아래 6항: XW 제거). 위 개정 2항의 `obstacle_ahead`: `RESUME` 허용을 이 항이 바꾼다.
   - `BACK_AND_RETRY`는 R3 전제 전부(로컬 복구 켜짐, 시도·규칙 예산, 횡단보도, 지도 자세 신선도, 신뢰 지도 자세의 뒤 띠)를 만족해야 한다. R6의 `peer_unknown` 면제는 AI에 주지 않는다. 그 로봇에 살아 있는 acting AI 사실이 있으면 보내지 않는다(`ai_fact:<kind>`). `rear_state: blocked`가 아니어야 하고, 앞에 동료가 있으면 R1 `WAIT`이 먼저다(`peer_ahead`).
   - 보류된 AI `ABORT`는 같은 주기에 규칙의 움직이는 답으로 넘어가지 않고 R5 `WAIT` + 사람(`ai_abort_held:<판정>`)이 된다. 이미 답한(또는 비켜 가는) 막힘에 온 제안은 감사에만 남긴다(`after_answer`).
   - 속성 시험(무작위 행 1000개): 보낸 AI `BACK_AND_RETRY`마다 R3 관문이 열려 있고(신뢰 지도 자세 동료 행 포함), AI `RESUME` 없음, trip 로봇에는 `WAIT`만.
2. **연동 상태.** `GET /api/fleet/ai`에 `chain`(판단기 켜짐, 로봇별 자격 유무 `enrolled|token|none` — 비밀은 내보내지 않는다, AI 실행 여부, 마지막 판단기 답과 시각, 1시간 제안 수 `accepted|held|refused|pending`)을 더한다. 관제 화면은 레일 끝 「대형·신호·기록」의 「진단」 옆 접힘 「연동 상태」에 보인다. D-540 2항이 머리를 한 줄로 묶고, 레일은 예외가 없을 때 상태를 접힘으로 두기 때문이다. 문제는 지금처럼 큐 행으로 나온다.
3. **막힘 행에 제안 결과.** 막힘 행은 그 막힘의 가장 새 AI 제안과 Fleet 판정, CORE 결과를 한 줄로 보인다("AI 제안 대기: CORE 수락", "AI 제안 중단: Fleet 보류 (횡단보도 여부 모름)").
4. **AI PC 배포 추적.** heartbeat에 `build_commit`(서비스가 도는 git 커밋)을 더한다. `deploy/ai_pc/deploy-situation.sh <커밋>`이 커밋마다 분리 worktree를 만들어 그 커밋에서 돌린다(`deploy/ai_pc/README.md` 「상황 서비스」). 현장 AI PC 재배포는 이 절차로 따로 한다.
5. CORE D-407 재검사는 그대로 마지막이다. AI 제안은 안전 기능이 아니다(D-430).
6. **XW 제거.** XW removed after independent Safety-Review 2026-10-10 — RESUME at a crosswalk only after CORE arms Fleet-map zones and reports a looked-and-clear armed zone, trip robots excluded, with its own Safety-Review. Fleet 지도 횡단보도 위의 `lane_lost`·`no_motion` 막힘은 trip 여부와 AI 제안에 앞서 R5 `WAIT` + 사람(`crosswalk_human`)이다.

**Related:** D-2, D-18, D-356, D-361, D-379, D-395, D-407, D-430, D-434, D-438, D-492, D-493, D-495, D-503, D-511, D-516, D-517, D-523, D-540, D-541, D-568, D-573.

### 개정 (2026-10-10): 사건 원인 초안의 맥락

AI PC는 열린 차선 정지마다 한 번 `GET /api/fleet/site-map/active`, `GET /api/fleet/sightings`를 읽고 기존 state 및 line-stuck 센서 필드와 함께 `incident_context` 사실을 남긴다. 이 사실은 `analyzer:incident_context@1`의 shadow 출력이며 CORE 원인을 검증된 근본 원인으로 승격하지 않는다. `value.cause_draft`는 `line_marking|obstacle|unknown`, `support[]`에는 CORE·신선한 Rosy Cam 관측 메타데이터·신뢰할 수 있는 지도 위치·센서값을 출처별로, `missing[]`에는 빠진 증거를 넣는다. `no_motion`이면서 전방 거리 센서가 0.3 m 이하일 때만 낮은 신뢰도의 `obstacle` 초안을 낸다. 지도 위치는 `localization.trusted=true`, `legacy=false`인 경우에만 비교한다. 프레임은 요청하거나 해석하지 않으며 `camera_frame_interpreted=false`와 `interpreted_front_image` 부족을 명시한다. 사람의 append-only 검토는 D-608 보고서에서 별도로 남긴다. 이 사실은 resolver의 acting kind나 motion proposal 입력이 아니다. 영상 모델과 실제 이미지 해석은 기존 V0·V1 및 소유자 동의 관문을 유지한다.
