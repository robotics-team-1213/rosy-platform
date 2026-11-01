# Monitoring UI evidence

LOCAL 화면 검증 기록이다. 실제 관제 PC 설치·LAN/TLS·장치·현장 수용은 HOLD다.

## G1

- 소스 `42404e6d6c`: 실제 backend Chromium16건과 registry/shared-controls/typography/token/palette를 합쳐 원격151 PASS, SKIP0, NEW/KNOWN/FLAKY0.
- 같은 소스 앞선 실행에서 compact overflow·빈 theme-color·임의 opacity를 검출했고 수정 뒤 위 전체 검사가 통과했다. 실패 기록을 성공으로 바꾸지 않았다.
- `impeccable detect --json`은 세 UI 파일에서 finding `[]`. 소스 트리에는 배포 common 사본이 없어 detector의 linked CSS 해석은 불완전했다. canonical token·component 검사는 위 G1과 실제 조립한 브라우저에서 별도로 통과했다.

## G2

실제 Collector·SQLite·HTTP 서버·Chromium을 사용했다. API intercept는 없다.
사이트 owner 파일을 준비·갱신·제거하고 API 단절에서는 실제 서버를 종료했다.
인증/범위 거부는 실제 서비스의 401/403이다. 지연 응답 교차는 실제 ASGI 응답을 지연시켜 확인했다.

| 상태 | 320×844 | 390×844 | 1366×768 | 1920×1080 |
|---|---|---|---|---|
| startup | PASS | PASS | PASS | PASS |
| auth-denied | PASS | PASS | PASS | PASS |
| scope-denied | PASS | PASS | PASS | PASS |
| fresh | PASS | PASS | PASS | PASS |
| delayed | PASS | PASS | PASS | PASS |
| unavailable | PASS | PASS | PASS | PASS |
| empty | PASS | PASS | PASS | PASS |
| error | PASS | PASS | PASS | PASS |
| disconnected | PASS | PASS | PASS | PASS |
| api-disconnected | PASS | PASS | PASS | PASS |

40개의 원본 PNG는 [g2-captures.zip](g2-captures.zip)에 보존했다. 파일 이름은 `상태-폭x높이.png`다.
모든 archive entry를 원격에서 복사한 파일과 byte 비교했고 fresh 기준선4개도 archive와 일치한다.
archive SHA256: `cd3e960a66dfa243a5808542e629f63d4098b045f3216383baa76027313a43a4`.
API 단절 캡처는 `42404e6d6c`, 나머지는 동일 UI 코드에 scope 시험을 추가한 `8e92f7f658`의 원격6 PASS 회차다.
두 회차의 known_failures 비교는 NEW/KNOWN/FLAKY0이다.
키·원본 private owner 본문은 캡처에 넣지 않았다. 시험 등록 ID와 합성 보고만 사용했다.

직접 열 수 있는 fresh 기준선: [320](fresh-320x844.png), [390](fresh-390x844.png),
[1366](fresh-1366x768.png), [1920](fresh-1920x1080.png).

## G3

`42404e6d6c` 코드와 실제 대표 캡처를 별도 읽기 전용 검토자가 확인했고 차단 결함이 없었다.
fresh320/1920, delayed, unavailable, error, disconnected, api-disconnected를 시각 확인했다.

| 항목 | 판정과 근거 |
|---|---|
| 정직 | GO — 원천 판정과 수집·보고 경로 신선도를 별개로 표시한다. 논리 연결을 물리 배선으로 주장하지 않는다. |
| 증거 | GO — 최신·지연·끊김·정보 없음과 나이를 표시한다. 오래된 건강 판정은 마지막 판정이다. |
| 색 | GO — 정상은 무채색, 실제 오류는 빨강, 실패 경로는 주의색이다. |
| 위계 | GO — 보고는 flat, 입력·갱신은 canonical control이다. |
| 불가역 | N/A — 명령·복구·안전 해제 입력이 없다. |
| 어휘 | GO — 운영자 상태·원천·시각·실패 단계는 한국어로 읽힌다. |
| 질문 | GO — 어디서 무엇을 언제 관측했는지, 현재 근거가 유효한지 답한다. |
| 문법 | GO — exception shell과 shared topbar/button/field를 사용한다. compact 표는 판독 가능하며 그래프는 명시한 제한 영역 안에서 가로 이동한다. |

그래프는 첫8경로, 연결 표는 검색 결과 첫100건을 보여준다. 전체 규모의 수용은 실제 운영 등록으로 별도 확인한다.
G3 대표 검토는 모든 G2 셀의 재검토나 동적 키보드 전수 검증을 의미하지 않는다.
