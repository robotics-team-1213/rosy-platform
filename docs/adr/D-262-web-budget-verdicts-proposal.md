## D-262 웹 자산에도 예산 판정을 — 셸 분해는 계획으로, 진단은 수락으로

**Status:** Proposed (2026-09-26). 아키텍처 시험의 주인이 판단할 제안이다.
이 문서는 시험을 고치지 않는다.

잇는 결정: D-168(구조 기준) · [D-150](D-150-web-node-control-navigation-map.md) ·
D-92 제5항 · D-130.2.

**Context (실측):**

`test_module_structure.py`의 예산(`FILE_BUDGET` 600줄)은 `CODE_SUFFIXES`
(`.py`·`.cpp`·`.hpp`)에만 든다. 웹 자산은 측정 밖이다. 현행 규모:

| 파일 | 줄 | 비고 |
|---|---|---|
| `src/runtime/sensing/web/dashboard.html` | 1837 | 단일 파일 |
| `src/hmi/dashboard/app.js` | 1529 | 셸 1개(인증·세션·teleop·호스트·로스그래프) |
| `src/site/fleet/fleet/server/web/console.js` | 878 | 단일 파일 |
| `src/hmi/dashboard/index.html` | 674 | 셸 마크업 |
| `src/hmi/dashboard/settings.js` | 482 | 예산 내 |

**Decision (초안 — 판정 제안):**

| 경로 | 판정 제안 |
|---|---|
| `sensing/web/dashboard.html` | accept: D-150이 1파일 1IIFE를 못박았다. 나누면 디버그 표면의 무빌드 계약이 깨진다 |
| `dashboard/app.js` | split: 세션·인증은 `client.js`에 이미 있다. teleop·호스트카드·로스그래프·vision을 셸에서 뺀다. 단, 한 번에가 아니라 D-130.2 자격이 설 때마다(2표면 필요) |
| `fleet console.js` | split: 로스터·대형·신호등·큐 렌더를 함수 다발이 아니라 모듈로. 단, Fleet 단일 표면이라 급하지 않다 — 600줄 판정의 첫 적용은 app.js부터 |
| `dashboard/index.html` | accept: 마크업은 셸이 아니라 문서다. 줄 수보다 `test_shared_controls.py`(ui-shell 문법)가 지킨다 |

**분해 실적 (2026-09-26, 제안이 실행으로):**

| 모듈 | 원천 | 검증 |
|---|---|---|
| `dashboard/vision.js` | app.js 카메라 블록 | 브라우저 52 passed |
| `dashboard/ros-network.js` | app.js 격리·그래프 블록 | 브라우저 ROS 경로 + 계약 단언(식별자 복원 1건) |
| `dashboard/host-cards.js` | app.js 호스트 4카드 | 유닛 42 + 브라우저 52 passed |
| `fleet/formation.js` | console.js 대형 패널 | 유닛 409 + 브라우저 12 + 변이 |
| `fleet/signals.js` | console.js 신호등 카드 | 유닛 409 + 브라우저 12 + 변이 |
| `fleet/roster.js` | console.js 명렬·큐 | 유닛 461 + 브라우저 12 + 변이 |
| `fleet/map-view.js` | console.js 지도·오버레이 | 유닛 461 + 브라우저 12 + 변이(폴링 상수는 셸로 복귀 1건) |

남은 셸 코어(인증·세션·소켓·refresh·명렬·큐·토큰·폴링)는 분리 대상이 아니다.
`hold-ticker.js`는 L2 추출(D-250)로 별도 관리한다.

**결산 (2026-09-26, 재평가):** 잔여 600줄 초과분(app.js 잔여·index.html·진단)은
모두 유지/동결 판정이다. D-130.2 자격을 만족하는 후보가 0건이라 컴포넌트화
트랙은 종료한다. settings.js(507)·board.js(151)는 예산 내 유지.
panels/*는 타 세션 범위라 판정하지 않는다.

**Alternatives:** 웹을 예산에 넣지 않는 안 — 지금 상태 유지. 셸을 한 번에
 넷으로 가르는 안 — D-92 제5항(쓰이지 않는 분리) 위반 소지, 단계 분할이 맞다.
줄 수 대신 복잡도로 재는 안 — 측정기가 없어 제안이 서지 않는다.

**Consequences (Accepted되면):** 아키텍처 시험의 주인이 `CODE_SUFFIXES`에
웹을 넣을지, 별도 웹 예산을 둘지 정한다. 이 문서는 제안으로 남는다.

**Validation / Transition:** (1) 위 표의 파일:행 대조, (2) 시험 주인의 채택
여부. `ROSY ADR Log.md`에 `D-262 | 웹 예산 판정 제안 | Proposed` 1행 추가가
이 초안의 착지다.

**References:** D-92, D-130, D-150, D-168, D-233, D-250.

---
