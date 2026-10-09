# D-581 Fleet TRAIL 앵커 사후 독립 안전 검토 — 2026-10-10

**판정:** `ae08cac387f4`의 통합 소스에 한해 D-430 CI의 과거 커밋 4개를 사후 검토 목록에 기록한다. 이것은 TRAIL 실구동 승인이나 각 중간 커밋의 단독 승인이 아니다. 작성 세션과 다른 검토 에이전트가 각 diff, D-430·D-581 계약, 후속 보완, 원격 호스트 시험을 확인했다.

| 커밋 | 독립 판단 |
|---|---|
| `b64ce7a4f341` | **단독 거절.** 기준 상실·낡음·점프에서 정지 표본을 보내지 않았고 odom epoch 전환에서 옛 변환을 재사용할 수 있었다. `1c362f1411b2`(epoch), `efba0585fe34`(명시적 hold), `ee79d749ad7b`(stream evidence)가 보완한 최종 통합본에 한해 과거 이력을 격리한다. |
| `198986fef424` | 상태 조회가 릴레이 더블의 앵커도 읽게 한 표시 변경이다. 정지·재무장·명령 권한을 바꾸지 않는다. |
| `93ec99d5ba4b` | 앵커 릴레이 팩토리를 `swarm/anchor.py`로 옮겼다. TRAIL 조건과 세션별 앵커 생성은 유지된다. |
| `8754cc2b5ed9` | 팩토리 인자와 상태 조회를 헬퍼로 옮겼다. 제공된 팩토리 우선, pose 부재 시 기본 릴레이와 `status=None` 동작을 유지한다. |

직전 원격 `main` 후보 `f89aa643ad05`에는 위 D-581 커밋과 보완 커밋이 없다. 다음 원격 후보 `ae08cac387f4`에는 모두 포함됐다. 로컬 공유 `main`에는 중간 커밋이 순서대로 존재했으므로 이를 원자적 착지라고 부르지 않는다. `ae08` 후보는 CI의 D-430 검사에서 차단돼 현장에 설치되지 않았다.

원격 AI 시험 PC에서 정확한 `ae08` HEAD로 `operations/fleet/test/test_trail_anchor.py`, `operations/fleet/test/test_trail_anchor_e2e.py`, `middleware/core/services/test/test_swarm_trail_anchor.py`를 실행해 **24 passed**를 얻었다. `test/known_failures.py` 비교는 **0 new, 0 known**이었다. 원본 로그는 `X:\DevTemp\d581-independent-review\run-1.txt`에 보관한다(SHA-256 `0e0bbc3cac0934d95d7baa3a804366277eddadd14bc132d353ff5eeb6414003d`).

D-581은 Proposed다. Gazebo SIM, 두 로봇 DEVICE 시험, 로봇–사이트 시계 차이 0.1초 이하 측정, 마커 크기·관측 신뢰도, 현장 주행 수용은 미완료다. 이 기록은 CI 이력의 사후 검토 근거이며 TRAIL 기능 활성화·주행을 허용하지 않는다.

## 03d530eab 연결 구조 검토

`03d530eab` 작성자가 아닌 통합 담당자가 diff를 독립 검토했다. 앱 조립부가 같은 지도 pose 서비스의 앵커 릴레이 팩토리를 주입하며, 안전 태그가 붙은 콘솔은 판단 계층 import를 제거했다. 제공된 시험용 팩토리 우선순위, pose가 없을 때 기본 릴레이, 앵커 상태의 조회 전용 동작은 유지된다. 원격 모델 PC에서 편대·앵커·CORE·D-430 구조 시험 **55개가 통과**했고 기존 실패는 **0 new, 0 known**이었다(`X:\DevTemp\d581-console-injection-green\run-1.txt`; 원격 실행기 출력의 실행 SHA와 함께 판단). 주행 승인은 계속 HOLD다.

## 74b87f13b 후속 검토

독립 검토자가 `74b87f13b`와 직전 통합 커밋 `2b655f16d`의 diff를 비교했다. 콘솔 변경은 주석 축약, 동일한 `getattr(..., "anchor", None)` 상태 조회의 walrus 표현, 빈 팩토리 사전 검사로 한정된다. 중지·재무장·전송·권한 경로나 D-430 import 경계는 바뀌지 않았다. 원격 실행기에서 `74b87f13b`를 모델 PC에 보낸 후 크기 판정·비밀값 검사·안전 경계·편대 앵커·Safety Review 시험 **16개가 통과**했고 기존 실패 비교는 **0 new, 0 known**이었다(`X:\DevTemp\d581-release-guards\run-1.txt`). 이 사후 이력 예외는 CI의 정확한 커밋 검사에만 적용하며 TRAIL 실구동 승인 범위는 넓히지 않는다.
