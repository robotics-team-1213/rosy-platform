## D-383 편대 역할은 계기 셋의 네 번째 칸이고, 대형에 속한 로봇만 말한다

**Status:** Accepted (2026-10-01, 사용자 요청·위임). 계기 셋(모드·안전)의 문법을 그대로 이어 세 번째 상태 칸을 만든다. 식별줄은 소프트웨어 버전을 계보의 일부로 함께 말한다.

잇는 결정: [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-82](D-82-oklch.md) · [D-362](D-362-per-code-type-file-size-budget.md) · [D-260](D-260-robot-shows-its-state-by-sound-light-screen-and-summary.md).

### Context

운용 콘솔의 계기 셋은 CURRENT MODE와 SAFETY CIRCUIT 두 칸만 있었다. 편대(SWM)에 참여한 로봇의 역할(리더/팔로워)은 스냅샷 `swarm.role`에 이미 있으면서 화면 어디에도 없어서, 편대 운용 중 누가 이끄는지 알려면 다른 화면을 봐야 했다. 운용자는 "이 로봇이 지금 무엇인가"를 첫 화면 상단에서 한 줄로 읽어야 한다(D-280).

### Decision

1. **계기 셋의 네 번째 칸 `FORMATION ROLE`**: `swarm.role`이 leader/follower일 때만 나타나고(기본 `hidden`), 리더·팔로워를 한국어로, 대형 이름을 뮤트 모노로 띄운다. role이 none이면 칸 전체가 사라진다 — 편대 밖 로봇에게 이 칸은 잡음이다.
2. **색은 쓰지 않는다.** 역할은 경보가 아니고 리더·팔로워는 단어로 충분히 다르다. 상태 색 예산(D-82)은 건강이 쓴다. `hidden`이 flex 레이아웃을 이기는 규칙(`.hero-formation[hidden] { display: none; }`)을 명시한다 — 빈 칸이 지도 높이를 훔치지 않게.
3. **emoji가 아니라 계기 문법.** 요청은 emoji였지만 화면 체계는 토큰·타이포 문법(D-359)으로 말한다. 칸·라벨·값의 동일 문법이 emoji보다 차분하고 색약에도 같다.
4. **식별줄에 버전**: `robot-id / 모델 / v버전 / runtime_mode`. "지금 무엇으로 돌리는가"는 정체성의 일부다. `/api/v1/system/info`의 `software_version`을 쓴다(새 엔드포인트 없음).
5. 렌더는 D-362 분할 규칙을 따른다: `telemetry.js`가 렌더하고(`renderFormationHero`) `app.js`의 상태 렌더가 `state.swarm`을 넘긴다. 새 모듈·새 파일 없음.

### Alternatives

- **emoji(👑/🚶)로 역할 표시:** 토큰 체계 밖이고 크로스플랫폼 렌더가 일정하지 않으며, 차분한 계기 문법과 충돌한다. 거부.
- **역할별 색(리더=초록 등):** 초록은 안전(nominal)의 말이다. 역할에 색을 빌려주면 건강 신호와 섞인다. 거부.
- **상시 칸(없으면 "없음" 표기):** 편대 밖에서 대부분의 시간을 보내는 로봇에게 항상 떠 있는 "없음"은 소음이다(D-280). 거부.

### Consequences

역할 칸은 편대 참여 여부에 따라 나타났다 사라진다 — 레이아웃이 상태에 따라 접히는 첫 칸이 된다(높이 변화 없음, 가로 칸). 사이트 콘솔(다중 로봇)의 역할 표기는 이 결정의 어휘(리더/팔로워, 색 없음)를 공유해야 한다.

### Validation

- 계약 시험(호스트): 칸의 존재와 기본 hidden, hidden-flex 규칙, 상태 렌더가 swarm을 넘기는 배선, 한국어 라벨, 버전 계보. 변이 증명 2종(배선 제거·hidden 규칙 제거 → 빨강).
- 브라우저 회귀(선택): `ROSY_RUN_BROWSER_TESTS=1`로 편대 참여 화면 확인. 편대 시나리오 자체는 SIM/FIELD 단계.
