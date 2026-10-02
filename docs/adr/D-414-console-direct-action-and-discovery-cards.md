## D-414 관제 콘솔은 바로 동작한다 — 비상 정지는 확인 없는 한 번 누름, 발견 장치는 등록 버튼이 붙은 카드, 안내 문장은 title로 물러난다

**Status:** Accepted (2026-10-02, 사용자 지시 — "설명하지 말고 명확하게, 그냥 누르면 되게"). D-218·D-280을 좁힌다.

이는 결정: [D-218](D-218-web-dialogs-name-the-action.md) · [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-371](D-371-list-row-irreversible-actions-confirm-before-danger-fill.md) · [D-410](D-410-console-operate-and-install-documents.md).

### Context

2026-10-02 회차 감상: 제어 대상 기기는 고정 목록이 아니라 mDNS 등으로 그때그때 등록되는
것인데, 화면은 "보이기만 하고 대충"이다. 안내 문장이 모든 조작을 미리 설명하며, 전체
정지마저 확인 대화상자를 건너야 한다. 로그는 한 줄짜리로 박혀 있다.

### Decision

1. **비상 정지는 확인 없는 한 번의 누름이다.** 브라우저 시험이 고정하던 "전체 정지 확인"
   (test_fleet_console_browser, D-92a 계보)을 폐지한다 — 비상 정지는 비상 출구이며 마찰은
   사고다(D-371이 대화상자 위에서 살아 있게 한 이유를 끝까지 밀어 어떤 사위에서도 즉시
   눌린다). `console.js`/`install.js`의 estop 처리에서 `window.confirm`을 제거하고,
   대화상자 핀(test_web_dialog_contract)에서 console.js의 전체 정지 확인을 뺀다.
   브라우저 시험은 "한 번 누르면 즉시 POST, 대화상자 0회"를 단정한다.
2. **발견(mDNS) 장치는 설치 화면의 주인공이다.** `/console/install`의 발견 목록이
   장치 카드(이름·주소:포트·부팅 단계·상태 라벨)를 그리고 `enrollment.decorateDiscoveryRow`가
   붙이는 `등록` 버튼으로 코드 대화상자가 곧장 열린다(D-410 이관 때 빠졌던 렌더를 채웠다).
3. **안내 문장은 title로 물러난다.** 상시 노출 힌트 문단(대형·신호등·지도·카메라·목표
   안내)은 제목의 `title` 속성으로 옮기고 문단 자리는 운용 상태가 쓴다. 비활성 사유처럼
   접근성이 필요한 안내는 그대로 글로 남는다(D-359 §5.3). 기록(#log)은 `기록` 제목을 얻어
   스캔 대상이 된다.

### Alternatives

- **확인 유지(안전 상식라인):** 거절 경로 자체가 사고 시나리오다. 업계 관례(비상 정지는
  무확인 즉시)도 같은 쪽이다. 거절.
- **힌트를 details로 접기:** 여전히 조작 앞에 문서를 둔다. title이면 자료는 남고
  소음은 사라진다. 거절.

### Consequences

누르면 즉시 정지·등록·조작된다. 안내는 마우스를 올렸을 때와 스크린리더에만 존재한다.
`window.confirm` 수 핀과 estop 브라우저 시험이 이 결정을 지킨다.

### Validation

- 대화상자 핀: console.js 2(목표 지정·재허가). 브라우저: 원클릭 estop POST + 대화상자 0회 통과.
- 설치 문서: 모의 발견 스냅숏으로 장치 카드·등록 버튼 렌더 확인.
- 문구·공용 컨트롤 게이트 재녹색.
