## D-249 FieldMap — 세 지도는 다른 물건이다. spec만 못박고 코드는 뽑지 않는다

**Status:** Accepted (2026-09-25). 코드 변경 0줄이 결과인 파일럿으로 착지. (번호: D-249로 확정. 롤아웃 계획의 실행 순서와 맞춘다.)

잇는 결정: [D-92](D-92-l2.md) 제5항 · [D-130](D-130-l2-headless.md) 2항 · [D-201](D-201-fixed-grammar-surfaces-fit-contract.md) · [D-233](D-233-design-system-component-token-draft.md)(인벤토리 P0) · concept 16 Law 0.

**Context (실측):**

| 항목 | 운용 `src/hmi/dashboard/map.js` | Fleet `server/web/console.js` | 진단 `src/runtime/sensing/web/dashboard.html` |
|---|---|---|---|
| 좌표 | GridFrame — occupancy 세계좌표로 리샘플, costmap도 occupancy 세계좌표로 샘플 (D-201 결정 3의 흔적) | 1:1 셀→픽셀, y 뒤집기 (`paintGrid`, `cellOf`) | base-fit + 사용자 zoom/pan/회전 `{z, A, angle}`, pan clamp |
| 레이어 | occupancy/costmap/path 토글 | 격자 + 로봇/목표/슬롯/중재 오버레이 | 남은/후보/지나온 경로 + 목표 + 실측 로봇원 |
| 클릭 | 초기자세/목표 모드 전환 | 선택된 로봇에게 목표 1건 | 핀 찍기 → 보내기/지우기 |
| 팔레트 | tokens.css (`--raster-*`, `--status-warn`, `--series-primary`) | tokens.css (`--paper`, `--ground-*`, `--series-goal`) | 자체 `:root` + `T` 객체 + PNG 파이프라인과 짝 |
| 점유 밴드 | 20/60 + uncertain | FREE 25 / OCCUPIED 65 | PNG 쪽 |

공유되는 것은 y-뒤집기 관례와 "팔레트는 토큰에서" 규칙뿐이고, 둘 다 이미 지켜지고 있다. 오버레이(슬롯·중재·실측 로봇원)는 각 표면의 계약물이라 뽑으면 Law 0 위반(없는 능력을 그리는 틀) 또는 문법 오염이다. 점유 밴드·legend 항목을 맞추면 거짓말이 된다 — 세 지도가 보는 데이터가 다르다.

**Decision (초안):**

1. **FieldMap spec을 못박는다.** (a) 격자는 행 0이 아래(y 최소), 캔버스는 y를 뒤집는다. (b) 래스터 색은 토큰에서 읽는다 — 단 진단 PNG 파이프라인은 예외로 둔다(D-194). (c) legend는 그 표면이 그리는 것만 말한다(없는 층을 적지 않는다).
2. **코드는 뽑지 않는다.** D-92 제5항과 D-130.2 자격 미달. 셋째 표면이 같은 로직을 필요로 할 때 재심사한다.
3. **파일럿 커밋은 이 ADR + 로그뿐이다.** 코드 변경 0줄이 이 파일럿의 결과다.

**Alternatives:** GridFrame을 Fleet에 이식하는 안 — 1:1 래스터를 리샘플로 바꾸는 화질·성능 회귀, 대가 없이 치른다. Fleet 오버레이를 headless로 뽑는 안 — 소비자가 Fleet 하나뿐이라 자격 미달. 점유 밴드 통일안 — 색이 바뀌는 시각 회귀이자 Law 0 위반.

**Consequences (Accepted되면):** FieldMap 인벤토리는 닫힌다. 새 지도 표면은 spec 3항을 만족해야 한다.

**Validation / Transition:** (1) 기존 지도 시험 전부 녹색(변경 없음 확인), (2) 이 ADR이 세 구현의 파일:행을 가리키므로 리뷰자가 대조 가능. `ROSY ADR Log.md`에 `D-249 | FieldMap — spec 고정, 코드 미추출 | Accepted` 1행 추가가 이 초안의 착지다.

**References:** D-92, D-130, D-194, D-201, D-233, concept 16 §4·§7.

---
