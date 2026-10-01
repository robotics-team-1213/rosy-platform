## D-395 UI/UX 공용화·일관성 목표 체계 — 여섯 목표와 승격 규칙을 계약으로 강제한다

**Status:** Accepted (2026-10-01, 사용자 승인). 개별 화면을 하나씩 고치는 일은 이 결정의 목표 아래에서만 한다.

잇는 결정: [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-359](D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) · [D-370](D-370-site-app-roles-names-and-shared-link.md) · [D-394](D-394-display-cards-are-a-contract-devices-are-profiles.md) · [D-153](D-153-ui-ux.md).

### Context

ROSY의 화면 자산은 이미 단일 출처 위에 서 있다: `web_common/tokens.css`(색·공간), `ui.js`(공유 컴포넌트 13종), 화면 문법 4종(spatial·exception·focal·procedure), 서피스 등록부(`surfaces.yaml`), 그리고 `DESIGN.md`(D-359 §8). 그러나 일관성은 대부분 **관례**로 유지됐다 — "두 서피스 이상 쓰면 web_common 으로 옮긴다"는 규칙이 검사 없이 사람 기억에만 있었고, 서피스 등록의 계약 칸이 비어 있어도 아무 것이 붉어지지 않았다. 화면이 아홉 개(LCD·Android 네이티브 포함)로 늘어난 지금, 관례는 이미 한계다.

### Decision

여섯 목표를 세우고, 강제 가능한 것은 계약 시험로, 아닌 것은 진행 추적으로 유지한다.

1. **G1 단일 언어**: 모든 서피스가 `tokens.css`·`ui.js`를 소비하고 재정의하지 않는다. 완료 기준 — raw 색 0(기존 계약)에 더해 **① 서피스가 web_common 밖에서 커스텀 엘리먼트를 정의하지 않고 ② 서피스 CSS가 `:root`에서 토큰 변수를 재정의하지 않는다**(신규 계약 시험). 두 서피스 이상이 같은 패턴을 쓰면 `web_common`으로 승격한다 — 승격은 관례가 아니라 이 계약이 만드는 압력이다.
2. **G2 문법 일관성**: 등록된 모든 서피스가 문법(`grammar`)과 계약(`contracts` 또는 `contract_reason`)을 채운다. 완료 기준 — 빈 칸 0. sim/dev 도구는 `contract_reason` 한 줄로 예외를 선언한다(예외도 기록이다).
3. **G3 장치 독립**: D-394의 원칙을 전 장치에 — 화면 내용은 페이로드 계약이, 장치는 프로파일이 말한다. 완료 기준 — 로봇 얼굴 렌더러가 페이로드만으로 검증되고, 새 장치가 웹·LCD 코드를 고치지 않고 추가된다.
4. **G4 역할 소유**: 모든 조작이 정확히 한 서피스의 소유다(D-370). 완료 기준 — `transitional` 소유가 0으로 수렴한다(현재 manual-drive 1건, Pilot 이행 대기).
5. **G5 검증 상시화**: 옵트인 브라우저 회귀를 **한 번의 문서화된 명령**으로 전 서피스 돌린다. 완료 기준 — 명령이 문서에 있고 매 서피스 baseline 이 등록부에 있다. 돌리지 않는 옵트인 시험은 시험이 아니다(test/AGENTS 의 원칙).
6. **G6 지식의 단일 출처**: DESIGN.md 가 '왜'를, ADR 이 결정을, solutions/ 이 학습을 소유한다. 완료 기준 — 새 UI 결정은 ADR 없이 랜딩하지 않는다(2026-10-01 의 D-383·D-385·D-394 가 이미 이 패턴).

실행 순서와 세부는 `docs/plans/2026-10-01-ui-ux-consistency-goals.md` 이 추적한다.

### Alternatives

- **목표 없이 화면 단위 개선 계속:** 오늘까지 해 온 방식. 각각 옳지만 방향이 없어 서피스마다 같은 논의가 반복된다. 거부.
- **전면 재디자인(새 디자인 시스템 도입):** 이미 좋은 기반 위에서 새 옷을 사는 격. 일관성 문제는 자산 부족이 아니라 강제 부족이다. 거부.
- **계약만 늘리고 목표 문서 없이:** 계약은 '지금'만 검사한다. 어디로 가는지(예: e-ink, Fleet 콘솔 확장)는 목표가 말해야 다음 계약이 나온다. 거부.

### Consequences

서피스마다 있던 편의 정의가 사라지고 승격 대상이 늘면 `web_common` 이 커진다 — 그것이 목적이다. 승격 판단(무엇이 '같은 패턴'인가)은 사람이 하고, 계약은 승격을 미루는 것을 붉게 만든다. G4 는 Pilot 이관 같은 외부 일정에 의존하므로 추적 항목으로 남는다.

### Validation

- G1: `src/hmi/web_common/test/test_single_language.py` (신규) — 변이 증명으로 승격 압력이 실제로 붉어지는지 확인.
- G2: 서피스 등록부 계약 시험 확장 — 빈 칸이 빨개지는지 확인.
- G5: 회귀 스윕 명령 문서화 + baseline 존재 검사.
- G3·G6: 각각 D-394 의 계약 시험과 ADR 동반 랜딩 관행으로 이미 측정 가능.
