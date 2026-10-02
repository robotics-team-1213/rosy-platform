## D-410 관제 콘솔은 운용 화면(/console)과 설치·보정 화면(/console/install)의 두 문서로 나뉜다

**Status:** Accepted (2026-10-02, 사용자 지시 — 남은 설치 요소도 분리하고 역할을 명확히). D-406·D-409의 접힌 서랍을 이관해 역할 분리를 완성한다.

이는 결정: [D-201](D-201-fixed-grammar-surfaces-fit-contract.md) · [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-406](D-406-console-camera-operate-install-split-and-goal-toggle.md) · [D-409](D-409-device-install-drawer-and-compact-roster-cards.md).

### Context

2026-10-02 회차 4. D-406/D-409로 설치 일(카메라 보정, 기기 등록·승인)을 접힌 서랍에 두었지만 여전히 운용 문서 안에 살았다. 운용 화면의 문서 높이·마크업·JS 배선이 설치 흐름에 계속 매여 있었다. 운용자(감시·목표·정지)와 설치자(등록·승인·보정)가 같은 문서를 쓰는 한 "이 화면이 무엇을 말하는지"가 흐려진다.

### Decision

1. **두 문서.** 운용 화면 `/console`(index.html + console.js) — 로스터·지도·대형·신호등·기록·카메라 프리뷰. 설치·보정 화면 `/console/install`(install.html + install.js) — 기기 등록·카메라 연결 승인·경기장 찾기·맵 맞춤·왜곡 보정·설치 기록. 같은 정적 자산 규칙·CSP·스타일시트 목록을 쓴다(test_grammar_separation이 두 문서 다 검사한다).
2. **운용 화면은 링크만 남긴다.** 등록·승인·보정 자리에 설치 화면 안내 문장이 있고, 주소 이동 안내 목록의 조작도 설치 화면으로 가는 링크다(이동 대화상자는 설치 문서가 소유).
3. **설치 화면의 문법은 procedure다.** 단계가 순서대로인 설치·점검 일에 맞는다(ui-shell grammar). 운용은 exception 그대로.
4. **토큰은 문서가 공유한다.** 같은 sessionStorage 키(`rosy-console-token`) — 운용 화면에서 접속했으면 설치 화면도 풀려 있다. 전체 정지 버튼은 두 화면 모두 첫 화면에 있다(D-280).
5. **운용 셸의 배선 정리.** console.js는 등록·카메라 승인·경기장/맵 보정 뷰를 더 만들지 않는다. vision-view는 보정 칸이 없는 프리뷰 전용 모드를 지원한다(빈 패널 스텁 — 읽기는 비고 쓰기는 무해). 발견 요청은 검색기 건강 로그와 고정 주소 판정(로스터 안내)만 남긴다.
6. **아이디 보존 이관.** 등록·승인·보정 마크업은 아이디와 조상 구조를 그대로 옮겨 기존 시험(`test_console_camera_pairing`·`test_task_contract_docs`)과 모듈이 그대로 붙는다 — 시험의 대상 문서만 install.html로 바뀐다.

### Alternatives

- **한 문서 + 탭 전환:** 문서 하나가 두 직업을 계속 들고 있다. 거절.
- **서랍 유지(D-409 그대로):** 마크업·폴링·권한 배선이 운용 문서에 남는다. 거절.

### Consequences

운용 문서가 가볍고 말하는 것이 하나가 된다(문서 1,154px @1920). 설치자는 북마크 가능한 자기 화면을 가진다. 설치 화면의 로스터 의존 값(주소 이동 등)은 각 화면의 안내가 이어 준다. 나중에 설치 화면이 독립 표면(별도 등록)으로 갈 때 이 문서가 그 뿌리가 된다.

### Validation

- 계약 시험: fleet 전체 — `test_server_app`의 신규 라우트/자산/링크 시험, camera-pairing·task-contract 문서 갱신, grammar_separation 두 문서 검사. web_common(등록부 audience 갱신 포함).
- 브라우저: 두 화면 모두 페이지 오류 0, 설치 화면이 세션 토큰을 공유받아 자동 인증됨, 운용 화면에 등록·보정 마크업 부재·링크 2개 확인.
- SOURCE/LOCAL 증거뿐, 사람 G3 관측은 별도.
