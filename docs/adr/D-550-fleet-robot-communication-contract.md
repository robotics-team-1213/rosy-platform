## D-550 Fleet↔로봇 통신 계약 — 아는 쪽이 보내고, 모든 메시지는 스스로 만료하며, 허가와 참고는 섞지 않는다

**Status:** Accepted (2026-10-09, 사용자 결정 J1–J4: J1 "목표 임대", J2 "아직은 경고만", J3 "표시 먼저", J4 "지금 페어링"). 계획은 `.omc/plans/fleet-robot-contract.md` rev 3.1(독립 critic 승인 rev 3)이다. 이 ADR은 원칙·목록·규칙 M이고 코드는 없다. 코드가 생기는 항목 가운데 목표 임대(10항)만 **Safety-Review 대상**이다. 허브 페어링(11항)은 살아 있는 로봇과 현장 설정을 바꾸므로 사용자가 로봇마다 명시적으로 "진행"을 말한 뒤에만 한다.

잇는 결정: [D-5](D-5-outbound-ws-fleet-rest.md)(로봇이 WS로 나가 상태·사건을 밀고, 명령은 Fleet→로봇 REST) · [D-81](D-81-fleet-v1-gather-core-rest.md)(REST 수집은 D-5를 대신하지 않는 대체 경로) · [D-419](D-419-saf003-fleet-link-loss-policy.md)(SAF-003 링크 끊김 정책) · [D-517](D-517-multi-robot-lane-traffic.md) 4항(CORE 통행권) · [D-494](D-494-fleet-trip-execution-m2-contracts.md)(trip·교차로 지시) · [D-407](D-407-lane-stuck-recovery-console-then-local.md)(차선 막힘) · [D-395](D-395-fleet-assisted-localization.md)(Fleet 도움 위치 찾기) · [D-474](D-474-caution-point-zone-grant.md)(구역 허가) · [D-337](D-337-robot-signal-source-measured-light.md)(로봇은 신호기 주장을 허가로 읽지 않는다) · [D-18](D-18-rosy-core.md)(CORE만 최종 `cmd_vel`) · [D-12](D-12-mission-fleet.md)(Fleet 임무) · [D-525](D-525-virtual-signal-fleet-zone-gate.md)(가상 신호등, "CORE가 묻는 길" 미정) · [D-536](D-536-fleet-robot-situation-and-coordinate-guide.md)(로봇 상황 안내).
고치는 결정: D-525 "CORE가 묻는 길"(선택 (a)·(b) 둘 다 아님, D-551이 REST 전달로 정한다) · D-474 4항 `expires_at`(벽시계, 구현 때 `ttl_s`로 바꾼다) · D-419 적용 범위(페어링한 로봇에 SAF-003, 11항).
관련(Proposed): [D-541](D-541-core-fleet-trip-lease.md) trip lease는 **누가 로봇을 쥐는가**(소유)다. 10항 목표 임대는 **Fleet 목표가 언제 끝나는가**(움직임의 한도)다. 둘은 다른 질문이고 같이 있을 수 있다.

### Context

2026-10-09 코드와 ADR을 다시 읽은 결과다.

- **기본 규칙은 이미 있다.** D-5: 로봇이 Fleet WS로 나가 상태·사건을 밀고, 명령은 Fleet→로봇 REST다. API Reference §7(v1.155) §7.5 "명령은 REST"가 같은 말이다. 어지러운 것은 규칙이 없어서가 아니다. (1) 현장 로봇이 허브에 페어링되지 않아 상태도 REST 폴링으로 모이고, (2) D-407 뒤 기능마다 만료 단어를 따로 골랐다(`ttl_s` 2, `expires_s` 15, `ttl_s` 5, 벽시계 `expires_at` 5 s).
- **허브 하트비트 답은 비어 있다.** `Envelope(HEARTBEAT, payload={})`(`operations/fleet/fleet/hub/hub.py:221`). 소켓 위의 유일한 Fleet→로봇 자리이고 쓰지 않는다.
- **로봇이 보낸 `command`는 거절된다.** `ROLE_VIOLATION`(`hub.py:125-126`). 허브는 `cmd_vel`·`image`·`twist` 키도 거절한다. `COMMAND`·`ACK`·`POSE` envelope 종류는 있지만(`contracts/foundation/core_common/protocol/schemas.py:812-820`) 이 소켓에서 쓰지 않는다. envelope에는 seq가 없다. seq는 payload마다 있다.
- **CORE는 Fleet REST를 부르지 않는다.** `middleware/core`에 `/api/fleet/` 클라이언트가 없다(OMX agent `fleet_fence.py`만 예외). 그러나 CORE가 밖의 HTTP 서비스를 폴링하는 클라이언트는 있다(`middleware/core/services/core_features/traffic_policy/observer_source.py:148-186`, D-337). 로봇 쪽 풀링 클라이언트 자체는 새것이 아니다.
- **FleetAgent 사건은 한 방향이다.** 허브 답은 `{accepted:true}`뿐이다(`hub.py:246`). 그래서 지금 로봇이 "묻는" 길은 질문을 상태에 올리는 것뿐이다(`line_follow.stuck`, 위치 후보). Fleet은 폴링으로 찾는다.
- **Fleet REST 클라이언트**(`operations/fleet/fleet/swarm/transport.py`): 로봇마다 현장 `robots.yaml`의 REST 토큰(`:215`), `trust_env=False`(`:208`), 기본 한도 5 s(`:200`), 로봇마다 `AsyncClient` 하나(`:209`). 페어링 토큰은 따로다(`hub.py:67-71`).
- **통행권은 기본으로 꺼져 있다.** Fleet `fleet.traffic.authority` 기본 false(D-517 M2 노트), CORE `authority_required` 기본 `False`(`middleware/core/services/core_features/line_follow/model.py:222`).
- **링크 끊김.** 페어링한 로봇은 `link_fresh_s` 1 + 2 + 0.5 = 3.5 s(`middleware/core/services/core_features/fleet_agent/agent.py:26,148-152`), SAF-003 `FleetLossMonitor` 기본 5 s, Fleet `navigation/goal`이 진행 중일 때만(`core_features/safety/fleet_loss.py:30,119-123,171-181`). REST만 쓰는 로봇은 로봇 쪽 링크 신호가 없다(D-419:38). 그 안전은 Fleet dispatch 제어(D-330)와 로컬 정지 경로에 있다.
- **현장 로봇은 페어링되지 않았다.** 로봇은 `pairing_token`과 (`hub_url`|`discovery`)가 있을 때만 페어링한다(`agent.py:63-70`). 기본 `rosy_default.yaml:334`에는 둘 다 없고, `deploy/site/robots.yaml.example`에 `fleet_pairing_token`이 없다. 그래서 현장 로봇은 `gather_source: rest`다(`operations/fleet/fleet/server/console.py:254-259,282,292`). 각 로봇 덮어쓰기 설정은 확인하지 않았다.
- **D-525 참고 정보가 로봇에 갈 길이 없다.** `GET /api/fleet/traffic/signals/ahead/{robot_id}`(`server/trip_routes.py:180-186` → `lane_traffic.py:354-362`)에 `pose_stamp`·`leg_id`·`ttl_s`·`seq`·`map_version`이 없다. `distance_m`은 계산한 자세에서만 맞다.

### Decision

**원칙.**
- 아는 쪽이 먼저 보낸다. Fleet이 계산한 것(허가, 지도 기준 참고)은 Fleet이 민다. 로봇의 사실(상태, 사건, 질문)은 로봇이 밀고, 허브 링크가 없으면 Fleet이 가져온다.
- 모든 메시지는 스스로 만료한다. 허가가 만료하면 선다. 참고가 만료하면 "모름"이다.
- 허가와 참고는 한 필드나 한 엔드포인트를 같이 쓰지 않는다.
- 위치에 따라 달라지는 데이터는 trip 구간과 로봇 자신의 odom 시각을 단다.
- 변경은 추가만 하고 능력 플래그로 연다.

1. **두 상호작용.**

   | 상호작용 | 뜻 | 필수 필드 | 규칙 |
   |---|---|---|---|
   | **물음/답**(ask/answer) | 로봇이 혼자 풀지 못한 질문을 드러내고(막힘, 위치 후보, 뒤에 "앞에 무엇이 있나"), Fleet이 답한다 | 물음: 로봇이 만든 `question_id`. 답: `question_id`, `ttl_s` | 로봇은 질문마다 이름 있는 **시간 초과 대체 동작**을 가진다. 답은 `question_id`가 열린 질문과 같고 `ttl_s`가 지나지 않았을 때만 쓴다. 질문마다 최악 지연(물음 → Fleet이 봄 → 답 도착)을 적는다 |
   | **관찰/전달**(watch/deliver) | Fleet이 로봇에 대해 보거나 계산한 것(블록, 신호, 지도 자세)을 묻지 않아도 보낸다 | `seq`, `ttl_s`, 종류. 위치 의존이면 `leg_id`, `pose_stamp` | 순서는 4항. 만료는 종류를 따른다 |

   지금 D-407 막힘(`stuck_id`)과 D-395 위치 결정은 물음/답이다. D-517 통행권, D-494 교차로 지시, D-525 신호 참고는 관찰/전달이다.

2. **네 종류.** 종류는 닫혀 있다.

   | 종류 | 예 | 만료·끊김 규칙 | 로봇을 움직이나 |
   |---|---|---|---|
   | **허가**(permission) | 통행권, 교차로 지시, 구역 허가, 위치 결정, 목표 임대(10항) | 자기 `ttl_s`. 만료 = 허가 없음 = 서거나 멈춤 | 예. 허가 안에서만 |
   | **명령**(command) | 목표, 차선 주행 모드, follow, 정지, 막힘 결정, 위치 찾기 임무 | **이름 있는 링크 끊김 규칙**: TTL, SAF-003(페어링), 스트림 시간 초과, 자기 에피소드 한도 중 하나. 없으면 OPEN HAZARD(7항) | 예 |
   | **참고**(advice) | D-525 앞 신호 | 자기 `ttl_s`. 만료 = 모름. 로봇을 더 조심스럽게만 할 수 있다 | **아니오** |
   | **사실**(fact) | 상태 스냅숏, 사건, 관측 | 신선도 시각. 읽는 쪽은 오래된 것을 모름으로 본다 | 아니오 |

   허가와 참고는 같은 필드·같은 엔드포인트를 쓰지 않는다. 참고를 읽는 CORE 코드는 허가 판정에 닿지 못한다(D-551 import-lint). 위 표에 없는 Fleet→로봇 데이터는 모두 참고다.

3. **위치 의존 데이터.** `leg_id` + `pose_stamp` + 경로 미터 거리를 단다. CORE는 `pose_stamp` 뒤 자기 odom 주행 거리로 다시 잰다(통행권과 같은 방식, `core_common/protocol/line_authority.py:34-37`). 구간이 바뀌거나, odom 궤적이 바뀌거나, `ttl_s`가 지나면 버린다.

4. **시간 기준과 순서.**
   - `ttl_s`는 **받는 쪽 단조 시계**로 받은 순간부터 잰다. 벽시계 `expires_at`은 쓰지 않는다.
   - `pose_stamp`는 Fleet이 스냅숏 `odom_pose.stamp`에서 읽어 그대로 돌려주는 CORE 시각이다. CORE만 비교한다. CORE 벽시계(UTC epoch 초, `line_authority.py:34`)이고 Pi에는 RTC가 없어 시계가 튈 수 있다. 장치 실측은 아직이다(D-517:138).
   - 순서: `(pose_stamp, seq)`로 비교하되 **저장된 항목이 만료 전이고 같은 `leg_id`일 때만**이다. 더 오래되면 버린다. 저장 항목이 만료했거나 구간이 바뀌면 다음 유효한 메시지를 시각과 관계없이 받는다. 단 통행권과 같은 odom 기록 검사(`AUTHORITY_POSE_STALE/FUTURE`)는 거친다. `seq`는 (로봇, 구간)마다 하나다. `fleet_epoch`(Fleet 시작 때 무작위 id)는 기록용이다.

5. **추가만, 능력 플래그.** 로봇이 받는 새 필드는 추가 선택 엔드포인트·필드(API-002)이고 `rosy.controls/1` 능력 플래그 뒤에 둔다(`core_common/protocol/controls.py:72-73` 꼴). 옛 로봇은 무시하고, Fleet은 플래그가 없는 로봇에 보내지 않는다.

6. **운반 경로.**

   | 상호작용 | 허브 페어링 로봇 | 페어링 없는 로봇(지금 현장) |
   |---|---|---|
   | 로봇 사실(상태·사건) | WS 하트비트 1 Hz + 사건 밀기(D-5) | Fleet REST 수집 1 s(`server/console_routes.py:72`). 사건은 밀리지 않는다(D-81 비용, 대체 경로로 받아들임) |
   | 물음 | 하트비트 상태 안의 질문. 뒤에 명시적 `question {question_id, kind}` | `GET /robot/state` 안의 질문, 수집이 폴링 |
   | 답 | REST POST. 하트비트 답에는 **참고 종류 답만** 실을 수 있다 | REST POST |
   | **허가·명령** 전달 | **REST만**(D-5, D-517 검토를 다시 열지 않는다). WS 답에 싣지 않는다 | REST만 |
   | **참고** 전달 | 하트비트 답 `advice`(목표) **또는** REST, 한 저장소로, 최신이 이긴다 | REST(D-551, 먼저 나간다) |

   - **하트비트 답**은 페어링한 로봇의 상황 답(참고 종류)에만 쓴다. 허가·명령은 싣지 않는다.
   - 참고는 **로봇마다 보내는 쪽 하나**다. Fleet은 주기마다 운반 경로를 하나 고른다(페어링이고 허브 하트비트가 신선하면(≤ 3 s, `console.py:257`) 하트비트 답, 아니면 REST). 한 주기에 둘 다 보내지 않는다. CORE 저장소는 하나다.
   - 허브 `COMMAND`/`ACK` envelope 종류는 **예약이고 허가 경로가 아니다.**
   - REST 수집은 D-81대로 대체 경로이고 D-5를 대신하지 않는다. 페어링(11항)이 목표다.

7. **Fleet이 시작한 움직임 × 링크 끊김.** "페어링" = 허브 페어링 + D-419 동작. "REST만" = FleetAgent 없음.

   | 움직임 | 페어링: 끊기면 | REST만: 끊기면 | 정지까지(REST만) | 상태·주인 |
   |---|---|---|---|---|
   | `navigation/goal`(D-316) | 마지막 수신 5 s 뒤 SAF-003 STOP(`fleet_loss.py:30`). 정책 `CONTINUE`면 한도 없음 | **없음**: 목표까지 간다(D-419:38) | 목표 도착까지 | **OPEN HAZARD**. 주인: 이 ADR. 고침: 10항 목표 임대(J1) |
   | `swarm/follow` | `stream_timeout_ms` 1000 → HOLD(`swarm/manager.py:348-352`) | 같음 | ≤ 1 s | 한도 있음 |
   | trip 밖 `line-follow/mode` LINE_FOLLOW | 없음(SAF-003은 목표만) | 없음 | 지시 없는 다음 교차로까지(D-494:37). 교차로 없는 차로면 한도 없음 | **OPEN HAZARD**(양쪽). 주인: D-494 후속. 고침: Fleet은 trip 안에서만 LINE_FOLLOW를 연다. J2로 지금은 경고만 |
   | lane trip + 통행권(`traffic_authority: core`, `authority_required` 참) | 통행권 만료 2 s(`line_authority.py:14`) | 같음 | ≤ ttl 2 s + d_stop | 한도 있음 |
   | lane trip `hold_back`(기본, 통행권 꺼짐) | 교차로만: 무장한 지시가 만료하면(`expires_s` 15, D-494:131,153) 다음 교차로에서 선다 | 같음 | (다음 교차로까지) + ≤ 15 s | **OPEN HAZARD**(교차로 사이). 주인: D-517/D-494. 고침: 현장 lane trip에 통행권 요구. J2로 지금은 경고만 |
   | 교차로 지시 | `expires_s` 15(무장 상태만) | 같음 | ≤ 15 s. 실행 중인 회전은 끝낸다 | 한도 있음(김) |
   | 막힘 결정 동작(D-407) | 로컬 복구 에피소드, 후진 ≤ 0.35 m | 같음 | 에피소드 한도 | 한도 있음 |
   | 위치 찾기 임무(D-395) | 끝남·시간 초과·장애물·E-stop에서 끝(`localization/mission.py:37,290`) | 같음 | 임무 한도 | 한도 있음 |
   | 위치 결정 | `ttl_s` ≤ 30(자세 주입, 움직임 없음) | 같음 | 해당 없음 | 한도 있음 |
   | `safety/stop`, 전체 E-stop | 정지 걸림 | 같음 | 즉시 | 안전 쪽 |

   지금 규칙 M을 어기는 것: `navigation/goal`(REST만, 또는 `CONTINUE`), trip 밖 `line-follow/mode`(양쪽), `hold_back` lane trip(양쪽).

8. **규칙 M.** Fleet이 시작한 모든 움직임은 TTL 또는 로봇이 볼 수 있는 링크 신호로 한도가 있어야 한다.
   - 로봇마다 판정한다. 7항에서 그 로봇의 현재 링크와 읽어 온 정책으로 "OPEN HAZARD"인 행이면 위반이다.
   - SAF-003 정책은 로봇마다 다르다(`PUT /api/v1/safety/limits` `fleet_loss_policy`, 기본 STOP `middleware/core/gateway/core/services.py:327`). Fleet은 trip이나 목표를 받을 때 `GET /api/v1/safety/limits`(또는 `safety/state` `fleet_link`)로 읽는다. `STOP`·`HOLD`·`RETURN_HOME`만 링크 한도로 센다. **`CONTINUE`는 한도 없음**이다.
   - **지금은 경고만(J2).** 위반은 관제 예외 큐의 주의 행과 로봇 카드 `link:` 옆 표시로 보인다. 거절하지 않는다.
   - 강제(`422 LINK_UNBOUNDED_MOTION`)는 로봇마다 켠다. 그 로봇이 한도를 얻을 때(목표 임대 지원, 통행권 요구, 비 `CONTINUE` 정책으로 페어링)이고, 사이트 전체 날짜는 없다. 다시 보는 시점: D-517 M2 Safety-Review 뒤(J2).
   - 이 판정은 Fleet 쪽이다. Pilot(D-344)과 로봇 대시보드는 CORE에 바로 닿으므로 Fleet이 시작한 움직임이 아니고 규칙 M 밖이다.

9. **로봇이 묻기: 지금과 페어링 뒤.**

   | 로봇 | 경로 | Fleet이 질문을 볼 때까지 최악 |
   |---|---|---|
   | 페어링 | 사건 즉시 밀기(`nav.line_stuck_opened`) + 하트비트 상태 | ≤ 1 s, 나쁜 링크면 답 한도 2 s 더 |
   | REST만 | 수집 주기 1 s + REST 한도 5 s(`transport.py:200`) | ≤ 6 s |

   답 자체는 막힘이면 사람·사다리 시간(D-407 관제 유예 3 s 뒤 로컬), 위치면 D-395 사다리(60 s 뒤 `needs_human`)다. 페어링 뒤에는 하트비트 상태에 추가 필드 `question {question_id, kind}`를 둘 수 있고, 참고 종류 답은 다음 하트비트 답(≤ 1 s)에 온다. 허가·명령 답은 여전히 `question_id`를 단 REST POST다.

10. **목표 임대(J1).** Fleet이 보낸 `navigation/goal`의 한도는 링크와 관계없이 TTL로 둔다. 통행권과 같은 "허가 = TTL" 꼴이다.
    - **계약(추가).** `POST /api/v1/navigation/goal`에 선택 `lease_ttl_s`(0 < s ≤ 5, 제안 2)를 더한다. 갱신은 `POST /api/v1/navigation/goal/lease {correlation_id, ttl_s}`다. `lease_ttl_s`가 없는 목표는 지금과 같다.
    - **묶임.** 임대는 활성 `correlation_id`에 묶인다(`navigation/manager.py:151`이 정하고 `fleet_goal()` `:168-176`). 활성이 아닌(취소·도착·교체된) `correlation_id`의 갱신은 `409 GOAL_LEASE_NOT_ACTIVE`이다. 갱신은 목표를 되살리지 않는다.
    - **만료.** SAF-003 STOP과 같은 취소 경로(`nav.cancel(source="goal_lease", correlation_id=…)`)로 목표를 취소하고 `_active_correlation_id`를 비운다. 사건 `nav.canceled`의 source는 `goal_lease`다. `ttl_s`는 CORE 단조 시계다.
    - **갱신하는 쪽은 목표 출처마다 하나다.** Fleet trip `free` 구간: trip 주기(0.5 s). D-316 dispatch 목표: 시도가 열려 있는 동안 dispatcher가 주기마다. Fleet을 거친 운영자 목표: 이름 있는 운영자가 있는 동안 관제 세션이. 운영자가 없으면 갱신하지 않고 만료한다. 대시보드·로컬 목표는 임대가 없다(Fleet이 시작하지 않음).
    - **능력.** CORE는 `rosy.controls/1`에 `goal_lease: true`를 알린다. `lease_ttl_s`를 무시하는 옛 CORE는 규칙 M에서 한도 있음으로 세지 않는다.
    - **덮는 범위.** 임대는 `navigation/goal`만 덮는다. trip LINE_FOLLOW는 `fleet.traffic.authority: true`이고 그 로봇의 `authority_required: true`일 때만 한도가 있다. 그 전에는 규칙 M 경고 행이다(J2).
    - Fleet 재시작: 임대한 모든 로봇이 ttl 안에 선다. 의도한 동작이다.
    - **Safety-Review**를 받는다. 구현 전에 API Reference 행을 확정한다(지금은 "계획" 행).

11. **허브 페어링(J4).** 현장 로봇을 지금 허브에 페어링한다. 목적은 로봇→Fleet 밀기(D-81), 하트비트 답 참고 경로, 그리고 SAF-003이다. 목표 임대가 안전 한도이고 페어링은 그 전제 조건이 아니다.
    - **받아들인 비용.**
      - 로봇마다 페어링 토큰이 필요하다. 현장 등록부(`fleet_pairing_token`, `hub.py:67-71`)와 로봇 덮어쓰기 설정에 넣는다. 등록은 D-361/D-341 흐름이다.
      - D-407 `console_linked` 타이밍이 바뀐다. 링크 신선도로 디바운스된다(D-419:37: `linked_within(recovery_console_grace_s)` **또는** 마지막 허브 수신이 신선도 안). 막힘 사다리가 관제에 묻다가 로컬 복구로 넘어가는 때가 바뀐다.
      - 목표가 진행 중일 때 Fleet이 재시작하거나 죽으면 STOP/HOLD 정책인 **모든 페어링 로봇이 5 s 뒤 선다.** 의도한 사이트 전체 동작이다.
    - **실행.** 살아 있는 로봇과 현장 설정을 바꾸므로 사용자가 명시적으로 "진행"을 말한 뒤 로봇 하나씩 한다. 로봇마다 페어링 뒤 카드 `link: hub`와 정책 읽기를 확인한다.
    - 대체 (a) "CORE가 Fleet 신원의 마지막 인증 REST 호출 시각을 SAF-003 신선도로 쓴다"는 기록만 하고 만들지 않는다. `robots.yaml` REST 토큰은 운영자 공유 자격이라 "Fleet이 불렀다"와 "토큰 가진 누군가가 불렀다"를 가리지 못하고, Fleet이 폴링을 계속할 때만 동작한다. 페어링할 수 없는 현장에서만 다시 본다.

12. **관찰.** 로봇 카드에 `link: hub|rest|none`(`gather_source`, `console.py:282,292`)을 보인다. 규칙 M 경고 행은 예외 큐의 기존 규칙(D-493 1항) 안에 둔다.

13. **이행 순서.** 앞 단계가 착지해야 다음 단계를 한다.

    | 단계 | 무엇 | 검토 | 되돌림 |
    |---|---|---|---|
    | 1 | 문서: 이 ADR, D-551, API Reference "계획" 행 | ADR 검토 | 문서 되돌림 |
    | 2 | Fleet: 카드 `link:`, 로봇마다 정책 읽기, 규칙 M **경고만**(예외 큐 행, 거절 없음) | 없음(표시) | 되돌림(Fleet만), 설정 `rule_m: warn` |
    | 3 | 목표 임대: CORE `lease_ttl_s`·`/navigation/goal/lease`·`goal_lease` 능력, Fleet 갱신자 셋 | **Safety-Review** | Fleet이 `lease_ttl_s`를 보내지 않음(설정). 임대 없는 목표는 지금과 같다 |
    | 4 | 허브 페어링(J4): 로봇마다 명시적 "진행" 뒤 하나씩 | 사이트 운영 확인 | 그 로봇 페어링 토큰 제거 = 지금의 REST 수집 |
    | 5 | 로봇마다 규칙 M 강제(`422 LINK_UNBOUNDED_MOTION`). trip 밖 LINE_FOLLOW 거절과 현장 lane trip 통행권 요구는 J2 재검토(D-517 M2 Safety-Review) 뒤 | 사용자 결정 | 그 로봇을 `rule_m: warn`으로 |
    | 뒤 | D-474 `expires_at` → `ttl_s`(구현 때), 하트비트 `question` 필드 | 별도 ADR 행 | — |

### 확인: 현장 로봇은 설정만으로 페어링되지 않는다 (2026-10-09)

J4(지금 페어링)를 준비하며 현장을 읽기 전용으로 확인했다.

- 현장 로봇 둘은 콘솔 등록(D-361)으로 들어왔다. 등록에서 만든 로봇 끝점은 REST 토큰만 가진다(`operations/fleet/fleet/server/enrollment.py:281`, `enrollment_tls.py:175`). `fleet_pairing_token`이 없다.
- Fleet은 `robots.yaml`의 로봇 중 `fleet_pairing_token`이 있을 때만 허브를 켠다(`operations/fleet/fleet/cli.py:438`). 현장 `robots.yaml`의 `robots`는 비어 있다. 그래서 현장에서는 허브 자체가 돌지 않는다.
- 따라서 페어링은 새 코드가 필요하다: 등록이 로봇별 허브 페어링 자격을 만들어 저장하고(digest만), Fleet이 등록 로봇에도 허브를 켜고, 로봇이 `fleet.pairing_token`과 `hub_url`(또는 승인된 발견 프로필)을 받는다. 새 자격 경로라 보안 검토가 필요하다. 별도 설계로 사용자에게 가져간다(J4는 그때까지 보류가 아니라 '설계 필요'로 남는다).

### Alternatives

| 대안 | 판단 |
|---|---|
| **O2** 허브 WS를 양방향 유일 경로로(하트비트 답에 참고, 뒤에 허가를 `command`로) | 허가·명령에는 기각. D-517 검토가 다시 열리고, WS는 1 Hz라 0.5 s trip 주기보다 느리고, 페어링 없는 로봇에는 결국 REST가 필요하다. 페어링 로봇의 **참고**에만 쓴다(6항) |
| **O3** 로봇이 Fleet을 가져옴(`GET /api/fleet/traffic/signals/ahead/{id}`, D-525 (a)) | 기각. 아는 쪽은 Fleet이라 폴링이 매 주기에 한 폴링 주기를 더한다. 로봇마다 Fleet 자격과 발견·URL이 필요하고 새 신뢰 방향이다(D-474 Alternatives 41행 "로봇이 Fleet REST를 직접 호출 … 새 인증 방향·자격이 생김. 기각", `docs/adr/D-474-caution-point-zone-grant.md:41`). CORE odom과 잇는 `pose_stamp`가 없다. 폴링 클라이언트 꼴(observer 폴러)은 이미 있으므로 "새것"은 이유가 아니다. D-474 40행(FleetAgent EVENT로 묻고 응답에 허가)은 허브로 묻는 것을 기각하지만, 이미 있고 허가를 싣지 않는 하트비트 **답**의 참고는 막지 않는다 |
| **O4** 참고를 통행권 POST의 선택 필드로 | 기각. 안전 검토를 받는 한 schema에 허가와 참고가 섞인다(원칙). 통행권이 없는 `hold_back` 로봇은 참고를 받지 못한다 |
| 목표의 한도를 허브 페어링(SAF-003)으로만(J1 다른 선택) | 기각. 페어링한 로봇에만 되고, 정책 `CONTINUE`면 한도가 없다. 목표 임대는 링크와 정책에 관계없다 |
| CORE `authority_required: true`를 모든 로봇에 | 기각. 대시보드 로컬 차선 주행도 멈춘다 |
| D-81을 대체(REST 폴링을 정식 경로로) | 기각. 로봇→Fleet 밀기를 버린다(D-81:22) |

### Consequences

- Fleet→로봇 메시지마다 종류와 만료 규칙이 하나로 정해진다. 새 기능은 이 표에 행을 더하고 종류를 고른다.
- 지금 규칙 M을 어기는 세 행이 관제에 경고로 보인다. 거절은 아직 없다(J2). 그동안 현장 lane trip과 trip 밖 차선 주행은 지금 위험을 그대로 가진다.
- 목표 임대가 들어가면 Fleet이 보낸 `navigation/goal`은 링크와 관계없이 ttl 안에 끝난다. Fleet 재시작은 임대한 로봇을 모두 세운다.
- 페어링하면 사건이 밀리고 SAF-003이 붙지만, 로봇마다 토큰이 생기고 D-407 막힘 타이밍과 Fleet 재시작 동작이 바뀐다(11항).
- REST만 쓰는 로봇은 여전히 로봇 쪽 링크 판정이 없고 TTL에 기댄다.
- D-474 구현은 `ttl_s`로 시작한다.
