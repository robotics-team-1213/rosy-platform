# D-581 Fleet TRAIL 앵커 사후 독립 안전 검토 — 2026-10-10

**판정:** `ae08cac38`의 통합 소스에 한해 D-430 CI의 과거 커밋 4개를 사후 검토 목록에 기록한다. 이것은 TRAIL 실구동 승인이나 각 중간 커밋의 단독 승인이 아니다. 작성 세션과 다른 검토 에이전트가 각 diff, D-430·D-581 계약, 후속 보완, 원격 호스트 시험을 확인했다.

| 커밋 | 독립 판단 |
|---|---|
| `b64ce7a4f` | **단독 거절.** 기준 상실·낡음·점프에서 정지 표본을 보내지 않았고 odom epoch 전환에서 옛 변환을 재사용할 수 있었다. `1c362f141`(epoch), `efba0585f`(명시적 hold), `ee79d749a`(stream evidence)가 보완한 최종 통합본에 한해 과거 이력을 격리한다. |
| `198986fef` | 상태 조회가 릴레이 더블의 앵커도 읽게 한 표시 변경이다. 정지·재무장·명령 권한을 바꾸지 않는다. |
| `93ec99d5b` | 앵커 릴레이 팩토리를 `swarm/anchor.py`로 옮겼다. TRAIL 조건과 세션별 앵커 생성은 유지된다. |
| `8754cc2b5` | 팩토리 인자와 상태 조회를 헬퍼로 옮겼다. 제공된 팩토리 우선, pose 부재 시 기본 릴레이와 `status=None` 동작을 유지한다. |

직전 원격 `main` 후보 `f89aa643a`에는 위 D-581 커밋과 보완 커밋이 없다. 다음 원격 후보 `ae08cac38`에는 모두 포함됐다. 로컬 공유 `main`에는 중간 커밋이 순서대로 존재했으므로 이를 원자적 착지라고 부르지 않는다. `ae08` 후보는 CI의 D-430 검사에서 차단돼 현장에 설치되지 않았다.

원격 AI 시험 PC에서 정확한 `ae08` HEAD로 `operations/fleet/test/test_trail_anchor.py`, `operations/fleet/test/test_trail_anchor_e2e.py`, `middleware/core/gateway/test/test_swarm_trail_anchor.py`를 실행해 **24 passed**를 얻었다. `test/known_failures.py` 비교는 **0 new, 0 known**이었다. 원본 로그는 `X:\DevTemp\d581-independent-review\run-1.txt`에 보관한다(SHA-256 `0e0bbc3cac0934d95d7baa3a804366277eddadd14bc132d353ff5eeb6414003d`).

D-581은 Proposed다. Gazebo SIM, 두 로봇 DEVICE 시험, 로봇–사이트 시계 차이 0.1초 이하 측정, 마커 크기·관측 신뢰도, 현장 주행 수용은 미완료다. 이 기록은 CI 이력의 사후 검토 근거이며 TRAIL 기능 활성화·주행을 허용하지 않는다.
