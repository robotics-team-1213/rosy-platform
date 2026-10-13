## D-610 문제 상황은 AI가 먼저 판단한다 — AI PC가 두 카메라(Rosy Cam·로봇 앞 카메라)와 맥락을 보고 답을 고르고, Fleet은 증거 신선도만 보고 실행·확인·기록하며, 사람이 맡을 유형은 결과 경향으로 나중에 찾는다

**Status:** Proposed (2026-10-10). 사용자 결정 두 개(아래)를 문서로 옮긴 것이다. 실제 로봇에서 켜는 것은 로봇별 플래그이고 기본은 꺼짐이며, 켜기 전에 재생 평가·Gazebo 시나리오·독립 Safety-Review(이 ADR 「Safety-Review」·「켜는 관문」)가 필요하다. 구현은 단계 P1–P5로 따로 착지한다.

사용자 결정(2026-10-10):
- "거의 모든 것을 AI가 판단하도록 하되, 추후에 정말 위험하거나 혹은 사람이 판단해야 할 부분을 역으로 추후에 경향을 파악해서 처리하는 걸로 맥락을 생성하는 걸로 해보자." 고른 범위: 닫힌 고리 확인, 로봇-로봇 교착의 AI 판단, 비전 모델(VLM) 연결, 문제 유형 넓히기. "그렇게 해서 지금 말한 부분을 해결하는 ADR을 작성하고 이를 해결해."
- (같은 날, 조정 세션 전달) "AI가 다 판단해도 돼. 단순하게 카메라 2개를 보고 맥락을 보고 판단하는 거잖아 — Rosy Cam과 Pinky(로봇) 영상을 보고." 횡단보도 `RESUME`, 회전 자리 밖 회전, 신뢰하지 못한 자세에서의 움직임, trip lease **판단 규칙**의 예외, 보정 중 상황도 AI가 고를 수 있다. 사람만 하는 것은 비상정지 해제다. 남는 것은 판단 규칙이 아니라 **물리적 마지막 선**(1항)이다. rosy-b3 쪽 사용자도 "AI가 다 판단"을 확인했다.

**고치는 결정:**
- [D-577](D-577-trouble-fleet-rules-and-ai-pc-realtime-situation-facts.md) 7항("AI 사실은 Fleet을 더 조심스럽게만 만든다"), 개정 2026-10-10 「AI PC 제안」 2항(원인별 허용 단어), 개정 2026-10-10 저녁(rosy-b3, `feat/d577-chain-supervision`) 1·6항(AI `RESUME` 금지, `WAIT` 외 단어의 횡단보도 null 조건, `ABORT` 보류, R3 전제의 `BACK_AND_RETRY`, 횡단보도 R5 `crosswalk_human`): **AI 우선 로봇(3항)의 VLM 판단(5항)에 한해** 이 ADR 4항이 대신한다. 그 관문 코드는 지우지 않는다. 결정론 분석기의 대신하기 제안과 AI 우선이 아닌 로봇에는 그대로이고, AI 우선 로봇에서도 로봇별 플래그로 하나씩 되살린다(3항).
- [D-607](D-607-stuck-deadlock-realign.md) 원칙 "AI는 `REALIGN`을 내지 못한다": AI 우선 로봇의 VLM 판단은 `REALIGN`을 고를 수 있다. 조작 계약(8항)과 CORE 재확인은 그대로다.
- [D-517](D-517-multi-robot-lane-traffic.md) 5항 M4: 교착의 `replan`은 운영자 확인(`replan_hold`, [D-489](D-489-fleet-route-planning-concept-and-algorithm.md) 9) 없이 실행할 수 있다(7항). 블록 표의 불변식은 그대로다.
- [D-573](D-573-crosswalk-stop-look-cross.md) "횡단보도 막힘은 사람": AI가 고를 수 있다. AI `RESUME`의 뜻은 "CORE 게이트의 자기 확인이 통과하면 간다"이다(4항 표).
- [D-492](D-492-d438-vision-tier-local-qwen-ai-pc-gated.md) V0·V1: 정체 **사실**을 규칙 입력으로 쓰는 관문은 그대로다. 이 ADR의 VLM 판단은 그 관문 대신 「켜는 관문」을 지난다.
- [D-516](D-516-offline-decision-model-replay-boundary.md)·[D-523](D-523-ai-pc-ask-returns-facts-or-candidates.md) "AI PC는 사실·후보만": 제안 통로(D-577 개정에서 열림)를 4항 유형으로 넓힌다. 사실 통로(`POST /api/fleet/ai/facts`)와 `ai_observer`의 다른 쓰기 거절은 그대로다.

잇는 결정: D-2/[D-18](D-18-rosy-core.md)(CORE만 최종 `cmd_vel`, CORE 재확인) · [D-407](D-407-lane-stuck-recovery-console-then-local.md)(막힘 결정·재검사) · [D-395](D-395-fleet-assisted-localization.md)(지도 자세) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)/[D-424](D-424-one-robot-body-for-every-near-check.md)(몸 정지) · [D-430](D-430-safety-as-a-separate-concern.md)(안전 분리) · [D-438](D-438-fleet-stuck-resolver-rules-model-human.md)(규칙 → 모델 → 사람) · [D-502](D-502-battery-estop-release-and-battery-evidence.md)(비상정지 래치) · [D-541](D-541-core-fleet-trip-lease.md)(trip lease) · [D-560](D-560-rosy-cam-map-plane-fleet-draws-on-it.md)(Rosy Cam 지도 평면) · [D-596](D-596-led-identity-active.md)(LED 식별) · [D-601](D-601-fleet-trip-start-turns-camera-line-on.md)(trip 시작 검사).

### Context

1. **지금의 판단 사슬(main `4508db15e`).**
   - Fleet 판단기 `operations/fleet/fleet/server/stuck_resolver.py`: 규칙 R1/meet/R2/R3/R5/R6, 사람 상승 `estop`·`calibration`(:285–288), `deadline` 60 s(:289), `no_rule`(:315), `rule_budget`(:320), `restuck_after_resume`(:281).
   - AI 제안: `stuck_lane_lost.py` `AI_WORDS`(:90)·`ai_proposal_invalid`(:94)·`ai_answer`(:121), 대기 `ai_wait_s` 5 s(`stuck_resolver.py:39`). 제안은 `fleet.stuck_resolver.ai_facts_acting` 로봇만, 행동 사실은 `rear_blocked`·`path_blocked_by_robot`뿐이다(`ai_facts.py:35`).
   - AI PC `operations/situation/rosy_situation`: 결정론 분석기만(`analyzers.py`, `deadlock.py` `TrafficWatch`). 영상·모델이 없다(`service.py:108` `model_profiles: []`). 제안기는 "뒤 막힘·앞 로봇이면 `WAIT`, 아니면 `BACK_AND_RETRY`"(`analyzers.py:124–143`).
   - 교착 `fleet/traffic/handover.py`: 순환이면 한 대 `replan`(운영자 확인 대기), 나머지 `wait`, 모르면 `human`. AI 입력이 없다.
2. **현장 24 h(2026-10-09–10).** AI 제안 58건 모두 `BACK_AND_RETRY`, CORE로 간 것 10건. 사람 상승 48건 중 36건 `crosswalk_unknown`(허브 횡단보도 키 수정 배포 중). 답이 문제를 풀었는지 아무도 보지 않는다: 판단기는 CORE의 수락·거절만 알고(`stuck_resolver.result`), 다시 막히면 새 막힘으로 다룬다.
3. **기록 결함.** `fleet_ai_proposals.judged_at`에 단조 시계가 들어간다. 루프의 `now = self._clock()`(`time.monotonic`, `stuck_resolver_loop.py:50`)이 `_judge`에서 `judged_at`이 된다(`stuck_lane_lost.py:148`). 현장 표가 1970년으로 보인다.
4. **보이지 않는 문제.** 저조도·과노출 HOLD는 막힘 보고에서 빠지고 분석기 `stalled` 사실(shadow)로만 보인다(D-577 개정 4항). 지도 자세 `DEGRADED`·`UNKNOWN`은 D-395 `needs_human`으로 사람에게만 간다. trip 실패는 trip 상태로만 남는다.
5. **AI PC와 Ollama.** AI PC(Tailscale `ai`)는 공용이다. 관제 PC에서 AI PC의 Ollama 11434는 닿지 않는다. 상황 서비스는 AI PC **안에서** 돌므로 `http://127.0.0.1:11434`로 부르면 그 망 제약과 상관없다. 소유자 동의는 D-492 개정(2026-10-10)에 있지만 Qwen 상주는 열지 않았다.
6. **영상 경로.** Rosy Cam 프레임은 Fleet Vision이 받는다(D-560). 로봇 앞 카메라는 Fleet이 막힘마다 한 장 받는다(D-577 8항, 메모리 한정). AI PC는 로봇·Rosy Cam에 직접 닿지 않는다(D-577 4항).
7. **크기 규칙.** `docs/plans/2026-10-10-fleet-stuck-subpackage.md`, D-607 P0: 막힘 코드는 `fleet/fleet/stuck`로 옮긴 뒤에만 키운다.

### Decision

**원칙.** AI 우선 로봇(3항)의 문제 상황은 AI PC가 판단한다. 입력은 두 카메라(Rosy Cam에서 로봇 둘레를 자른 영상 + 로봇 앞 카메라 한 장)와 맥락이고, 모델은 AI PC의 Qwen3-VL이다. Fleet은 AI 답의 **모양과 증거 신선도**만 보고 실행하며, 실행 뒤 풀렸는지 확인하고, 모든 것을 기록한다. 모델이 없거나 증거가 모자라면 지금의 규칙·관문(D-577 저녁 개정)이 답하고, 그다음은 사람이다. 사람 필요 유형은 처음에 비어 있고 결과 경향으로 운영자가 더한다.

1. **물리적 마지막 선 — AI도 Fleet도 끄거나 돌아가지 못한다.**
   - CORE D-422/D-424 몸 정지, LiDAR 장애물 정지, 300 ms 명령 워치독, 비상정지와 그 래치(SAF-001, D-502: 해제는 관리자만, 사람만).
   - CORE가 모든 움직이는 답을 자기 센서로 다시 확인한다: D-407 재검사(뒤 여유·사각·지나온 길), D-573 게이트의 스캔 확인, D-607 8항 회전 원·뒤 띠, D-541 lease 토큰 확인(주인 아닌 토큰 409), D-517 통행권 권한 확인. AI 답은 규칙 답과 **같은 CORE 거절 경로**를 지난다. 거절은 그 답의 실패이고 2항 고리로 간다.
   - CORE만 최종 `cmd_vel`을 낸다(D-2/D-18). AI PC는 로봇·CORE 주소와 토큰을 갖지 않는다. `ai_observer`는 사실·heartbeat·제안 POST 외의 쓰기에서 지금처럼 403이다.
   - 비상정지 중인 로봇에는 어떤 답도 보내지 않고 사람에게 올린다(지금 `estop` 상승 그대로). AI는 정지를 늦추거나 풀지 못한다.
2. **닫힌 고리.** 답(규칙·AI·사람)을 CORE가 받으면 Fleet이 **확인 창**을 열고 자기 관측으로 판정한다.
   - 막힘: 그 막힘이 닫히고 창 끝까지 같은 로봇에 새 막힘이 없음(지도 자세가 있으면 차로 방향 순 이동 ≥ 0.10 m도). 창 20 s.
   - 정체: 명령 또는 이동이 다시 생김. 창 20 s. 자세 상실: `LOCALIZED`로 돌아옴. 창 30 s. 교착: 그 순환이 표에서 사라지고 `CYCLE_PERIODS` 동안 다시 생기지 않음. 창 30 s.
   - 결과는 `resolved`·`unresolved`·`refused`(CORE 거절)·`superseded`(사람이 맡음·비상정지)다.
   - `unresolved`·`refused`면 같은 문제를 **결과를 붙여** AI에 다시 묻는다. 상한: 문제 하나에 AI 답 3번, 로봇 하나에 움직이는 AI 답 시간당 6번. **진동**: 같은 문제에서 서로 반대인 움직이는 답(예: `BACK_AND_RETRY` ↔ `RESUME`, 왼쪽 ↔ 오른쪽 `REALIGN`)이 두 번 이어지면 그만둔다. 상한·진동·D-438 60 s 기한 중 하나라도 걸리면 `WAIT` + 사람(`ai_exhausted`·`ai_hourly_cap`·`ai_oscillation`·`deadline`).
3. **AI 우선 로봇, 되살리는 관문, 끄는 스위치.**
   - 현장 설정 `fleet.ai_first.robots`(로봇 id 목록, **기본 빈 목록**). 목록 밖 로봇은 지금 그대로다(D-577 규칙·관문).
   - 현장 설정 `fleet.ai_first.keep_gates`(로봇 id → 켜 둘 관문 이름 목록). 관문 코드는 rosy-b3 `fleet/fleet/stuck`에 그대로 있고 이 목록이 AI 우선 로봇에서 켤지 정한다. 이름(rosy-b3 답 2026-10-10): `ai_words`(원인 → 허용 단어, `RESUME`·`YIELD` 없음), `trip_wait_only`(trip 로봇은 `WAIT`만, D-517 M4), `crosswalk`(XW 제거 → `WAIT` + `crosswalk_human`, 현장 지도 횡단보도 0.29 m 보류, `crosswalk_unknown`), `trusted_pose`(LEGACY·신뢰하지 못한 지도 자세면 움직이는 답 없음), `r3_preconditions`(AI에는 R6 동료 면제 없음, CORE의 `rear_blocked`), `acting_fact_hold`(살아 있는 acting 사실이 후진을 R5로), `abort_requires_crosswalk_null`(AI `ABORT`는 횡단보도 null일 때만, 아니면 `ai_abort_held`). **기본값: `trip_wait_only`만 켜짐**(AI 우선 로봇도, Gazebo trip 시나리오와 그 자체 Safety-Review 전까지). 나머지는 AI 우선 로봇에서 기본 꺼짐이다. `after_answer`(이미 답한 막힘의 제안은 감사만)는 관문이 아니고 늘 그대로다. 비상정지·SAF-001은 관문이 아니라 1항이고 끌 수 없다. 시험이 관문마다 "켜면 옛 동작"을 묶고, 바뀌는 규칙마다 D-610을 인용한다.
   - 콘솔 **AI 우선 끄기**: 이름 있는 운영자가 누르면 모든 로봇이 그 자리에서 목록 밖 동작으로 돌아간다(메모리, 재시작 때 설정값). `POST /api/fleet/ai/first {enabled}` 하나다.
   - 꺼진 관문이 막았을 답은 기록에 `floor_would_hold:<관문>:<판정>`으로 남는다(9항).
4. **문제 유형과 AI가 고를 수 있는 답.** 이미 있는 CORE·Fleet 명령만이다. 새 하향 통로는 없다.

   | 유형 `kind` | 찾는 곳 | 답 |
   |---|---|---|
   | `stuck` | CORE 막힘(`lane_lost`·`no_motion`·`obstacle_ahead`·D-607 `no_progress`·`dithering`·`crosswalk_blocked`) | D-407 `WAIT`·`BACK_AND_RETRY`·`RESUME`·`ABORT`·`YIELD`(Fleet meet 기하가 있을 때만)·`REALIGN`(D-607 계약, 로봇 능력 있을 때만) |
   | `stalled` | 차선 주행 켜짐·막힘 없음·명령 0·이동 < 0.05 m 20 s(저조도·과노출 포함) | 그대로 둠·차선 주행 끔·Fleet 정지 |
   | `pose_lost` | 지도 자세 `DEGRADED`·`UNKNOWN`(D-395) | LED 식별 요청(D-596)·그대로 둠·Fleet 정지 |
   | `deadlock` | D-517 순환·livelock(`TrafficWatch`) | 순환의 한 로봇 `replan`(막을 간선), 나머지 `wait`(7항) |
   | `trip_failed` | trip `failed`·`stalled` | 로봇 정지·trip 취소 |

   - **횡단보도 `RESUME`의 뜻.** "지금 건너라"가 아니라 "CORE 게이트의 자기 확인이 통과하면 간다"이다. Fleet은 횡단보도 0.29 m 안(D-577 1항 기준) 로봇의 AI `RESUME`을 CORE가 게이트를 켠 채 `line_follow.crosswalk`에 게이트 객체 상태 `armed`·`approaching`·`looking`·`waiting` 중 하나를 보고할 때만 보낸다(D-573: 게이트 객체는 게이트가 켜져 있을 때만 나온다). `crossing`은 넣지 않는다(건너는 중의 막힘은 장애물·진행 문제로 다룬다). 그러면 CORE는 D-573의 스캔 확인(`crosswalk_clear_s` 5 s, 빈 스캔 비율)을 지나야 움직인다. 게이트가 꺼진 로봇(보고 `null`·`unknown`·`inside`·`ahead`)에는 물리적 확인이 없으므로 보내지 않고 `WAIT` + `crosswalk_human`이다(`floor_would_hold:crosswalk:gate_off`).
   - `YIELD`는 Fleet meet 기하가 길이와 회전을 정한다. AI는 "이 로봇이 비킨다"만 고른다. 기하가 없으면 보낼 수 없다.
   - `MANUAL`을 AI가 고르면 `WAIT` + 사람(`ai_manual`)이다.
   - trip 로봇: `trip_wait_only`가 기본으로 켜져 있어 AI 우선 로봇도 trip 중에는 `WAIT`만이다. 판단기는 trip 주인 자격으로 움직이는 답을 **보내지 않는다**(두 번째 lease 주인이 되기 때문이다, D-541). 뒤에 이 관문을 끄는 결정(Gazebo trip 시나리오 + 별도 Safety-Review)이 나면 AI 결정은 trip 실행기(lease 주인, 하나뿐인 쓰는 이)가 실행한다. 블록 밖으로 나가야 하는 답은 7항 `replan`이다.
5. **증거와 신선도(Fleet 검사).** VLM 판단 하나는 증거를 인용해야 하고, Fleet은 모자라면 그 답을 보내지 않는다(그때는 규칙·관문).
   - Rosy Cam: 프레임 id·촬영 시각, 나이 ≤ 2.0 s. 로봇 앞 카메라: 프레임 id·촬영 시각, 나이 ≤ 3.0 s. 둘 중 하나라도 없거나 늦으면 거절(`evidence_missing:<view>`·`evidence_stale:<view>`).
   - 지도 자세: 상태와 나이(신뢰하지 못한 자세도 상태를 적어야 한다). 모델: `vlm:<profile_id>`(Ollama 모델 digest·프롬프트 id). heartbeat의 `model_profiles`에 없는 프로파일은 거절.
   - 나이는 Fleet이 판정 순간 자기 시계로 잰다(케이스를 만든 시각 기준, 6항).
   - 그 밖의 검사: 열린 문제와 같은 id, `ttl_s` ≤ 8 s, 4항 단어표, 단어에 필요한 몸체, 사람 필요 유형 아님(9항), 비상정지 아님, 같은 문제에서 CORE가 같은 답을 이미 거절하지 않음, 2항 상한.
   - 결정론 분석기 제안(`analyzer:*`, 영상 없음)은 VLM 판단이 아니다. 지금처럼 D-577 저녁 개정 관문 전부를 지난다.
6. **AI PC 상황 서비스 — VLM 판단.**
   - Fleet이 문제마다 케이스를 만든다: `GET /api/fleet/ai/case/{problem_id}`(`ai_observer` 읽기) — 유형·원인·상세, 로봇 상태, 지도 자세·상태·나이, 차로·경로·블록, 같은 로봇 10분의 최근 판단과 결과, Rosy Cam 자른 영상(로봇 둘레 1.0 m, JPEG, 프레임 id·촬영 시각), 로봇 앞 카메라 한 장(같은 꼴). 영상은 Fleet 메모리에만 있다(D-577 8항). AI PC는 영상을 디스크에 쓰지 않는다(sha256만 입력 로그에).
   - 모델: Ollama `qwen3-vl:8b-instruct`(D-492, digest·프롬프트 id 고정)를 AI PC 로컬 `http://127.0.0.1:11434`로, 시간 제한 6 s. 출력은 JSON 하나(`decision`, 몸체, `reason`, `confidence`, 인용 증거)이고 단어표 밖·형식 오류는 버린다.
   - 대신하기: `owner_mode`가 `available`이 아니거나 모델 설정 없음·시간 초과·형식 오류면 결정론 분석기 제안이다(5항 끝: 관문 전부).
   - heartbeat `model_profiles`에 적재된 프로파일(모델 id·digest·프롬프트 id)을 싣고, 제안마다 `source: vlm:<profile>`로 같은 값을 싣는다. `build_commit`(rosy-b3)과 `deploy/ai_pc/deploy-situation.sh`의 커밋별 디렉터리를 그대로 쓴다.
   - Ollama 호출은 자기 스레드에서 시간 제한과 함께 돈다. heartbeat·사실 올리기·분석기 제안을 기다리게 하지 않는다. `owner_mode`를 따르고(`available`에서만 모델), systemd `MemoryMax`·`CPUQuota` 아래에서 돈다(공용 PC).
7. **로봇-로봇 교착.** `handover.decide`가 순환을 찾으면 Fleet은 순환 구성원·블록·경로·자세·두 카메라로 케이스를 만들고 AI가 `replan`(누가, 막을 간선)을 고른다. Fleet은 실행 가능성과 불변식만 본다.
   - 고른 로봇이 순환 구성원이고, 막을 간선이 그 로봇의 `avoidable` 안이다.
   - 새 경로는 처음 trip과 같은 계획 검사를 다시 지난다(경로 계획, `trip_admission` 시작 검사 D-601, 횡단보도·차로 방향).
   - 블록 표가 유일한 쓰는 이다. 재계획은 경로만 바꾸고 블록을 주지 않는다. 새 경로의 블록은 표가 지금 규칙으로 다시 준다(점유된 단위를 지나는 허가 없음).
   - 통과하면 `replan_hold` 없이 경로를 바꾼다. 아니거나 AI가 없으면 지금 M4(운영자 확인·`human`)다.
8. **시간 예산과 정지.** AI를 기다리는 시간은 문제마다 `ai_wait_s`(12 s, D-619 개정: 10 s 추론과 전달 여유 2 s)이고 그동안 로봇은 CORE HOLD에 있다. 판단기 루프·교통 표·비상정지·정지는 AI 응답을 기다리지 않는다(AI 호출은 AI PC에서, 판정은 메모리의 제안 하나). AI가 없거나 늦으면 규칙 → 사람이다.
9. **기록, 경향, 사람 필요 유형.**
   - **문제 기록** `fleet_problem_episodes`(`--tasks-db`, 30일 보관): 문제 id·유형 키, 맥락 요약, 증거 인용(프레임 id·나이·sha256, 영상 자체 아님 — 오래 남는 것은 D-379 녹화), AI 제안·출처·프로파일, Fleet 판정(`floor_would_hold` 포함), 보낸 답, CORE 응답, 확인 결과(2항), 사람 개입. `GET /api/fleet/ai/episodes`(JSONL 내보내기).
   - **유형 키** `<kind>:<cause>:<place>`, `place` ∈ `lane`·`crosswalk`·`turn_spot`·`off_lane`·`unknown`(신뢰 지도 자세와 현장 지도로 Fleet이 정한다).
   - **사람 필요 유형 표** `fleet_human_classes`(버전마다 행: 키, 더함/뺌, 누가, 이유, 근거 통계, 시각). 처음 비어 있다(비상정지는 1항이라 표 밖). 표에 있는 키의 문제는 AI 답을 보내지 않고 `WAIT` + 사람(`human_class:<key>`).
   - **경향 작업**(Fleet 안, 하루 한 번과 콘솔 요청 때): 키마다 지난 7일 `n`, `unresolved` 비율, CORE 거절 비율, 사람 개입 비율, 아깝게 피함(답 뒤 창 안의 몸 정지·비상정지) 비율. `n` ≥ 5이고 (`unresolved` ≥ 0.5 또는 아깝게 피함 ≥ 0.2 또는 사람 개입 ≥ 0.5)이면 **후보**. 아깝게 피함은 한 번(`n` 무관)이어도 후보다.
   - **콘솔 「사람 판단 필요 유형」**: 후보와 근거, 더하기·거절(이름 있는 운영자, D-540 ②). **빼기는 관리자만**(이유 필수). 경향 작업은 표를 스스로 바꾸지 않는다. 검토 주기: 매주 한 번 운영자가 후보와 표를 본다(콘솔이 7일 넘게 안 본 후보 수를 보인다).
10. **`judged_at`.** 기록의 시각(`fleet_ai_proposals.judged_at`, 문제 기록)은 `time.time()`(epoch s)이다. 나이·길이(`ttl_s`, 확인 창, 상한)는 모두 단조 시계로 잰다.

### 단계

| 단계 | 내용 | Safety-Review |
|---|---|---|
| P0 | D-607 P0(막힘 하위 패키지 `fleet/fleet/stuck` 이동)과 rosy-b3 `feat/d577-chain-supervision` 착지를 기다리고 그 위에서 시작 | — |
| P1 | 닫힌 고리(2항), 문제 기록(9항 앞), `judged_at`(10항), 사람 필요 유형 표(빈 표), AI 우선 로봇·되살리는 관문·끄는 스위치(3항), 증거 검사(5항) | 예 |
| P2 | 유형 넓히기 `stalled`·`pose_lost`(4항) | 예 |
| P3 | 교착 AI `replan`(7항) | 예(D-517 M4) |
| P4 | 케이스 끝점과 AI PC VLM 클라이언트·대신하기(6항) | 예(VLM 판단이 움직임이 되는 첫 단계) |
| P5 | 경향 작업과 콘솔 「사람 판단 필요 유형」(9항) | 아니오 |

P4 전에는 VLM 판단이 없으므로 5항 끝에 따라 모든 AI 제안이 지금 관문을 지난다. P1–P3은 고리·기록·스위치·유형을 깔 뿐 AI 판단을 넓히지 않는다.

### 켜는 관문(실제 로봇의 `fleet.ai_first.robots`)

1. **재생 평가**(모델 PC 또는 AI PC, 노트북 아님): D-607의 막힘 39건(`X:\DevTemp\steer-review\deadlock\`), 9dfk·8kcn 횡단보도 주행, 2026-10-09–10 현장 제안·상승 기록을 케이스로 만들어 VLM 판단을 돌린다. 판정 기준: 증거상 위험한 움직이는 답(동료·물체 쪽 후진, 사람·물체가 있는 횡단보도 `RESUME`) 0건, 사람이 고른 답과 맞음 ≥ 0.7.
2. **Gazebo 시나리오**(`tools/remote/remote_pytest.py --pick sim`): 사람·피규어가 있는 횡단보도, 앞뒤 모두 막힘, 역주행, 두 대 정면. 수용: 접촉 0, 사람·피규어 앞 출발 0, 비상정지 뒤 재개 0.
3. **독립 Safety-Review**(작성 세션이 아닌 리뷰어, D-430 §5 trailer).
4. 사용자 승인으로 로봇 하나씩 목록에 넣는다.

### Safety-Review

**바뀌는 것.** 지금까지 AI는 Fleet을 더 조심스럽게만 만들었다(D-577 7항). 이 ADR 뒤 AI 우선 로봇에서는 VLM이 움직이는 답을 고르고, Fleet은 모양·증거 신선도만 본다. 횡단보도 `RESUME`(게이트를 켠 로봇, "비면 간다"), 신뢰하지 못한 자세의 후진·회전, 운영자 확인 없는 재계획이 AI 판단으로 나갈 수 있다.

**남는 위험.**
1. 모델이 장면을 틀리게 보고 움직이는 답을 고른다(예: 횡단보도의 사람 손·물체, 뒤의 동료 몸).
2. 자세가 틀린 로봇에 Fleet 기하(`YIELD`·`REALIGN`)가 붙어 엉뚱한 방향으로 간다.
3. 재계획이 다른 로봇 근처로 경로를 바꾼다.
4. 같은 실수의 되풀이, 두 답 사이의 진동.
5. AI PC가 공용이라 모델이 느리거나 소유자 작업으로 빠진다.
6. 영상이 낡아 지금이 아닌 장면으로 판단한다.

**줄이는 것.**
- 1항 마지막 선이 모든 답에 그대로다. 몸 정지는 LiDAR·IR로 몸 앞뒤 물체에 멈추고, D-407 재검사는 후진 전과 중에 뒤를 보고, D-573 게이트는 스캔이 비지 않으면 건너지 않으며(그래서 AI `RESUME`은 게이트 있는 로봇에만), D-607 `REALIGN`은 회전 원 여유가 없으면 거절·중단한다. 워치독은 명령이 끊기면 멈춘다. 이 확인은 로봇에서 돌고 Fleet·AI가 끄지 못한다(D-430). (위험 1·2)
- 블록 표가 유일한 쓰는 이고 재계획은 처음 trip의 계획 검사를 다시 지난다(7항). (위험 3)
- 고리 상한·시간당 상한·진동 감지·60 s 기한(2항). (위험 4)
- 대신하기는 지금 규칙·관문이고 정지·비상정지는 AI를 기다리지 않는다(5·6·8항). (위험 5)
- 증거 신선도(Rosy Cam ≤ 2 s, 앞 카메라 ≤ 3 s, 두 시점 모두 필수)(5항). (위험 6)
- 전체 맥락 기록과 `floor_would_hold`, 경향 후보(아깝게 피함은 한 번이어도 후보), 운영자 한 번으로 사람 필요(9항).
- 범위: 로봇별 플래그 기본 꺼짐, 켜는 관문, 로봇별로 되살리는 관문, 콘솔 끄는 스위치(3항).
- 사람은 언제나 비상정지·정지를 누를 수 있고 막힘 행을 펼쳐 맡을 수 있다(맡으면 AI는 조용하다, D-438 §1).

**검토자가 볼 것.** (1) 비상정지 중 어떤 답도 없음, CORE 거절이 그대로 실패, (2) 2항 상한·진동·기한, (3) 7항 재계획이 블록 표를 우회하지 않고 계획 검사를 다시 지남, (4) 목록 밖 로봇과 `keep_gates`를 켠 관문의 동작이 옛 동작과 같음, (5) 판단기가 trip 주인 자격을 쓰지 않고 `trip_wait_only`가 기본 켜짐, (6) 증거 없는 AI 제안(분석기)이 옛 관문을 모두 지남, (7) 끄는 스위치가 다음 주기에 듣음.

### Safety-Review — 교착 AI 재계획(7항, P3)

**바뀌는 것.** 지금까지 D-517 M4의 순환 해소는 한 로봇의 경로를 다시 계획하고 그 자리에서 운영자 확인(`replan_hold`)을 기다렸다. P3 뒤에는 순환 구성원이 모두 AI 우선 로봇이고 AI PC의 `vlm:` 제안이 증거 검사를 지나면, 운영자 확인 없이 trip 실행기가 새 경로로 바꾼다. 누구를 다시 계획할지와 막을 간선도 AI가 고른다(결정론 규칙은 "구성원 중 id 순으로 처음 피할 수 있는 로봇").

**구현(이 브랜치).** `fleet/stuck/deadlock.py` `AiReplan`이 `deadlock:<id>:<id>…`(정렬된 구성원) 제안을 본다. `traffic/handover.decide(ai_pick=…)`가 그 고름을 다시 확인하고(구성원인지, 간선이 그 로봇의 `avoidable` 안인지, 비어 있지 않은지) 행에 `ai: true`를 단다. `trip_runner._ai_confirm`이 `_replan`이 만든 보류 경로를 첫 trip과 같은 `_caps_checks`·`_pose_checks`(D-494·D-601)로 다시 확인한 뒤 `_apply_replan`(운영자 확인과 같은 코드)으로 바꾼다. 검사가 실패하면 보류가 그대로 남아 운영자에게 간다(`detail.ai_replan_refused`).

**남는 위험.**
1. AI가 고른 로봇의 새 경로가 다른 로봇 근처나 횡단보도를 지난다.
2. 자세가 틀린 로봇을 다시 계획해 엉뚱한 자리에서 새 경로를 시작한다.
3. 같은 순환에서 재계획이 되풀이된다.
4. 순환 판정이 낡은 입력(D-577 `wait_cycle_stale_input`)에서 나온 거짓 순환이다.

**줄이는 것.**
- 블록 표가 유일한 쓰는 이다. 재계획은 경로만 바꾸고 블록을 주지 않는다. 새 경로의 블록은 표가 지금 규칙으로 다시 주므로 점유된 단위를 지나는 허가는 없다. (위험 1)
- 새 경로는 `plan_again`(경로 계획, 막힌 간선·지나온 자리 제외)과 첫 trip의 시작 검사(로봇 능력·현장 바닥 지도·통행권 권한, 차선 주행 모드, 신뢰 지도 자세 `LOCALIZED`와 앵커 나이)를 다시 지난다. 하나라도 실패하면 운영자 확인으로 돌아간다. (위험 1·2)
- `handover`가 AI 고름을 스스로 다시 확인한다. 고른 로봇이 구성원이 아니거나 간선이 그 로봇의 `avoidable` 밖이면 옛 규칙이 고르고 운영자 확인이 남는다. 같은 경로에서 이미 재계획했으면(`tried`) 사람이다. (위험 3)
- 순환은 `CYCLE_PERIODS`(3주기) 동안 이어져야 AI에 묻는다. 문제당 AI 답 3번(2항). (위험 3·4)
- CORE 마지막 선(몸 정지, LiDAR, 워치독, 비상정지)과 D-541 lease(실행기가 유일한 주인), D-517 통행권 권한 확인은 그대로다. 판단기 자격은 쓰지 않는다. (모든 위험)
- 범위: 구성원 전부가 `fleet.ai_first.robots`에 있고 콘솔 스위치가 켜져 있을 때만. 기본 빈 목록.

**검토자가 볼 것.** (1) `handover.decide`의 AI 분기가 `held`·`tried`·`periods` 검사 뒤에만 오는지, (2) `_ai_confirm`이 `_replan` 직후 같은 잠금 안에서 돌고 검사 실패 때 보류를 지우지 않는지, (3) `_apply_replan`이 운영자 확인과 같은 코드인지(`confirm_replan`에서 뽑아냄), (4) 재계획이 블록을 직접 주지 않는지.

### rosy-b3 검토 답(2026-10-10)

| # | 질문 | 답 |
|---|---|---|
| 1 | 물리적 마지막 선 | 1항. 몸 정지·LiDAR 정지·워치독·비상정지 래치(관리자 해제)·CORE 재확인·lease·통행권 권한은 AI가 끄거나 돌아가지 못하고, AI 답은 같은 CORE 거절 경로를 지난다 |
| 2 | 횡단보도 `RESUME` | 4항 표 아래: "CORE 게이트 확인이 통과하면 간다", 게이트를 켠 로봇의 `armed`·`approaching`·`looking`·`waiting`에만 |
| 3 | 증거 신선도 | 5항: 두 카메라 프레임 id·나이(2 s·3 s), 지도 자세 나이, 모델 프로파일, 없으면 거절. `ai_observer`는 그 밖의 쓰기 403 그대로(1항) |
| 4 | 닫힌 고리 | 2항: 확인 → 결과 붙여 재질의 → 문제당 3번·로봇당 시간 6번 → 진동 감지 → 사람 |
| 5 | AI PC 없음·느림 | 6·8항: 규칙 → 사람, 대기 12 s, 정지를 막지 않음 |
| 6 | 사람 필요 학습 | 9항: 기록, 운영자 수락, 매주 검토, 빼기는 관리자 |
| 7 | 켜기 전 | 「켜는 관문」: 재생 평가(39건·횡단보도 주행), Gazebo 4개, 로봇별 플래그(기본 꺼짐), 콘솔 끄는 스위치, 독립 Safety-Review. trip은 `trip_wait_only` 기본 켜짐 |
| 8 | 운영자 확인 없는 재계획 | 7항: 블록 표 유일한 쓰는 이, 점유 단위 허가 없음, trip 계획 검사 재실행 |
| 9 | 관문 코드 | 3항: 지우지 않고 `keep_gates` 일곱 이름으로 로봇별 복원(`trip_wait_only` 기본 켜짐), 바뀌는 규칙마다 D-610을 인용하는 시험 |
| 답 2 | 관문 이름·횡단보도·trip·`judged_at`·heartbeat | 3항 이름 일곱, 4항 `crossing` 제외·게이트 꺼진 로봇은 `crosswalk_human`, 4항 trip 주인 자격 금지, 10항 기록은 벽시계·길이는 단조, 6항 Ollama 별도 스레드·`build_commit` 유지 |

### 먼저 실패해야 하는 시험

- P1: 답 수락 뒤 창 안에 같은 로봇이 다시 막히면 `unresolved` + 결과 붙인 재질의, 세 번 뒤 `ai_exhausted`. 시간당 7번째 움직이는 AI 답은 `ai_hourly_cap`. 반대 답 두 번 이어지면 `ai_oscillation`. 풀리면 `resolved`. `judged_at`이 벽시계. 사람 필요 키는 사람. 비상정지 중 답 없음. AI 우선 로봇의 VLM 제안이 프레임 하나 없거나 늦으면 거절. 목록 밖 로봇과 `keep_gates` 관문은 옛 동작. AI 우선 로봇도 `keep_gates` 기본값에서 trip 중에는 `WAIT`만이고 판단기는 trip 주인 자격을 쓰지 않음. 끄는 스위치 뒤 다음 주기부터 옛 동작. 분석기 제안은 관문 전부.
- P2: 20 s 정체에 AI 차선 주행 끔이 실행·확인. `UNKNOWN` 자세에 LED 식별 요청.
- P3: AI `replan`이 `avoidable` 안이고 계획 검사를 지나면 `replan_hold` 없이 경로가 바뀌고 블록은 표가 다시 준다. 밖이면 지금 M4.
- P4: 모델 시간 초과·형식 오류·단어표 밖에서 분석기로 대신함. 영상이 AI PC 디스크에 남지 않음. heartbeat `model_profiles`.
- P5: 문턱 넘는 키가 후보가 되고, 수락 전에는 동작이 바뀌지 않으며, 수락 뒤 그 키는 사람. 빼기는 관리자만.

### Alternatives

- **보수적 시작(rosy-b3와 그쪽 사용자의 처음 설계).** 사람 필요 유형을 오늘의 보수적 집합(횡단보도 `RESUME` 금지, 회전 자리 밖 회전 금지, 신뢰 지도 자세 없는 움직임 금지, trip lease 규칙, 보정·비상정지)에서 시작해 증거와 검토가 쌓일 때만 푼다. 장점: 첫날 위험이 작다. 단점: 지금 사람 상승 대부분(24 h 48건 중 36건 `crosswalk_unknown`)이 그대로 사람에게 가고, 사람이 콘솔을 보지 않으면 로봇이 선다. AI가 그 유형에서 어떻게 판단하는지 기록이 생기지 않아 푸는 근거도 생기지 않는다. **검토했고 사용자 결정(AI 우선, 2026-10-10)으로 거절했다.** 그 관문은 `keep_gates`(로봇별 복원)와 `floor_would_hold` 기록으로 남는다.
- **AI는 사실만, Fleet 규칙이 답한다(D-577 7항).** 지금 모습. 규칙이 없거나 막다른 상황이 사람에게 간다. 거절(사용자 결정).
- **AI PC가 로봇에 직접 명령한다.** 로봇 토큰이 공용 PC로 가고 확인 고리가 Fleet 밖에 생긴다. 거절.
- **경향 작업이 사람 필요 유형을 스스로 더한다.** 운영자 모르게 동작이 바뀐다. 후보만 낸다.

### Consequences

- 사람에게 가는 문제가 줄고 사람 행은 "AI가 못 풂(고리 상한·진동·기한)"·"사람 필요 유형"·비상정지로 좁아진다.
- AI 판단 오류는 CORE 마지막 선과 고리가 받는다. 그 비용(CORE 거절, 몸 정지, 재시도)은 기록과 후보로 보인다.
- 실효의 전제는 AI PC Qwen 상주와 「켜는 관문」이다. 그 전에는 분석기가 대신하고 관문 전부를 지나므로 지금과 같다.
- Fleet API에 케이스·문제 기록·사람 필요 유형·AI 우선 스위치 끝점이 생긴다(API Reference 행, D-18). 로봇 API는 바뀌지 않는다(`REALIGN`은 D-607의 계약).

### 사용자 쪽 전제

1. AI PC 소유자에게 Qwen3-VL 상주(VRAM 약 8 GB, `keep_alive`)와 `owner_mode: available` 동의.
2. AI PC에 Ollama 설치와 `qwen3-vl:8b-instruct` 받기. 서비스는 로컬 127.0.0.1로 부르므로 tailnet ACL 변경은 필요 없다.
3. AI PC 서비스 재배포(`deploy/ai_pc/deploy-situation.sh`, rosy-b3 절차).
4. 「켜는 관문」 통과 뒤 로봇별 `fleet.ai_first.robots` 승인.

### Verification

- 이 기록은 문서다. `python tools/harness/rosy_harness.py lint`는 형식 증거다.
- 단계별 시험은 위 목록이고 원격 pytest(`tools/remote/remote_pytest.py`)로 돈다. 호스트 pytest는 장치·현장 수용이 아니다.

### 열린 질문

1. 확인 창(20/30 s)과 상한(3번, 시간당 6번)을 현장 기록으로 다시 정할지.
2. 경향 문턱(`n` ≥ 5, 0.5/0.2/0.5)을 운영 1주 뒤 다시 정할지.
3. 재생 평가의 "사람 답과 맞음 ≥ 0.7"이 적당한지(사용자).

**Related:** D-2, D-18, D-379, D-395, D-407, D-422, D-424, D-430, D-438, D-489, D-492, D-502, D-516, D-517, D-523, D-540, D-541, D-560, D-573, D-577, D-596, D-601, D-607.

### 구현 정정: Rosy Cam 영상 전달

Fleet은 Rosy Cam JPEG를 케이스에 넣거나 중계하지 않는다. `ai_observer` 전용 케이스에는
활성 지도에서 최근 수용된 로봇 sighting이 있을 때만
`views.rosy_cam`의 `frame_path`와 10초짜리 서명 lease를 넣는다. Lease에는 지도 평면의
관측된 로봇 중심 1.0 m crop 좌표와 지도 ID·보정 revision이 포함된다. 위치 상실 시에도
수용된 sighting은 영상 위치 근거로만 쓰며 제어 권한을 넓히지 않는다. AI PC는 현장 프록시를 통해 Vision에서 JPEG와
프레임 번호·촬영 시각을 직접 읽고, 메모리에서만 VLM 입력으로 바꾼다. Vision은 승인된
보정 기록이 맞지 않으면 409를 반환하고 원본 영상을 대체 응답으로 내보내지 않는다.
AI PC가 어느 영상을 읽지 못해도 VLM 판단은 생략하고 규칙 분석기 경로를 유지한다.

AI case는 재판단마다 앞 카메라를 새로 읽는다. 운영자용 한 장 보관을 재판단 근거로
재사용하지 않는다. 교착 case는 안정된 대기 순환과 로봇별 `avoidable` 간선을 포함하고,
모든 구성원의 두 영상을 제공한다. VLM이 고른 로봇의 근거를 제안에 연결하고 모든
구성원 근거의 신선도·현재 간선·trip admission을 다시 확인한다.
