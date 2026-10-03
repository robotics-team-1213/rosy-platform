# Task 3: Console document and credential lifetime

2026-10-03 Windows Python 3.14.5 / Node v24.15.0 / Chromium, `refactor/ui-ownership`.

## 책임과 구현

두 Console 문서가 `createPageScope()`를 각각 소유한다. 공통 도구는 요청 취소, interval/listener/subscription 정리, 한 번 쓰는 timeout과 wait, 이전 작업의 결과 거절을 맡는다. 문서가 읽기 재개 콜백을 제공하며 공통 도구에는 Fleet 권한·저장소·명령 재전송 정책이 없다. `request()`는 호출자 signal과 문서 signal을 함께 사용한다.

문서 종료와 토큰 교체는 이전 요청을 취소한다. JSON façade뿐 아니라 등록/카메라 승인 패널의 직접 fetch, Vision lease/blob/JSON/image decode, map/formation/roster/line-stuck callback과 catch/finally까지 같은 경계에 연결했다. 응답을 받은 뒤 본문이나 하위 비동기 작업을 기다렸다면 다시 현재 작업인지 확인하고 상태를 적용한다. 이전 요청의 finally가 새 요청의 busy flag를 풀지 않게 했다.

정적 입력·폴링·IntersectionObserver·Vision frame 구독은 종료 때 해제하고 복귀 때 한 번씩 다시 연결한다. 다시 그린 카드의 handler는 DOM을 공통 scope에 보관하지 않고 생성 당시의 epoch를 검사한다. 이전 카드의 확인·명령 handler는 복귀 이후에도 종료 상태다. 열린 확인 창과 아직 보내지 않은 목표 선택을 취소한다. 조작 요청의 응답을 받지 못했을 때 성공이나 물리 정지를 추정하지 않는다.

복귀 콜백은 인증·발견·지도·영상의 새 조회를 시작한다. Vision 프리뷰 lease 발급을 제외한 이전 운영 명령은 재전송하지 않는다. JSON 오류 해석, sessionStorage key, poll cadence와 기능 미설정 404 gate는 기존 owner에 남겼다. 이미 서버에 전달된 명령의 취소를 보장하는 기능은 아니다.

## 검증

- request/scope/page-scope/Fleet adapter/authorization/poll-gate Node **56 passed**. 새 page-scope 계약 9개는 종료·토큰 교체·복귀·영구 종료·해제·동적 handler·확인 대기 취소·one-shot wait·외부 구독을 검사한다.
- 실제 두 HTML/JS를 읽는 Chromium lifetime/session/origin **14 passed**. JSON, 등록과 별도로 직접 요청하는 카메라 대기 목록, Vision 프레임에서 fetch와 body 단계에 늦은 응답을 주입한다. 종료 후 요청과 repaint 없음, interval/observer 0개, 복귀 후 중복 구독 없음, 이전 tick 무효화, 늦은 401의 새 인증 잠금 방지, 확인 대기 취소와 명령 재전송 없음을 검사한다.
- `pagehide/pageshow`의 persisted 이벤트는 시험이 주입한다. 브라우저가 실제 뒤로 가기에서 BFCache를 선택한다는 증거와 구별한다. API는 통제된 fixture이며 실제 현장·장치 수용은 아니다.
- X: 사본의 자산 43개가 현재 product bytes와 같은지 먼저 확인했다. 종료 시 epoch disposal을 제거하면 **8 failed**, 카메라/Vision의 현재 작업 검사를 제거하면 종료 후 HTML 변화로 **4 failed**였다. 사본 bytes 복원과 현재 source 대조 후 Chromium **14 passed**. 제품 worktree에서 변이하지 않았다.
- 공유 UI·ownership·Fleet site-lanes/static·quick 검사 **351 passed, 24 skipped, 26 warnings**. 새 비활성 사유 누락과 기존 설치 wiring 문자열 검사 실패를 수정한 뒤 재검사했다. 최초 Fleet 전체는 **1584 passed, 7 skipped, 1 failed**였으며 무실패 실행으로 표현하지 않는다.
- 수정 후 Fleet 전체를 다시 실행해 **1585 passed, 7 skipped**를 확인했다. harness lint는 **0 errors, 26 warnings**였다. 선택한 운용 browser 검사에서는 **11 passed, 1 failed, 55 deselected**였고 실패한 등록 dialog 사례는 위 전체 inventory의 기존 OPEN 항목과 같다. 전체 browser 무실패 결과로 표현하지 않는다.
- Fleet production 합계 증가를 **29017 lines**에서 다시 판단했다. 증가분은 기존 Console panel의 취소/정리 경계이며 backend owner나 명령 정책을 추가하지 않는다. D-425 Task 9가 UI source를 `ui/console`로 옮기며 Fleet server 분해와 기존 +150 package allowance는 계속 유효하다.

임시 시험·변이 로그는 `X:/DevTemp/rosy-ui-ownership/task3-lifetime-*.txt`, `task3-mutant-*.txt`, `task3-lifetime-mutations/`에 있다.

## 남은 수용

이 기록은 Task 3의 SOURCE/LOCAL 수명 계약이다. [기존 전체 browser 실패 목록](task3-browser-regressions.md)의 20개는 Task 5/11에서 실제 화면 역할과 대조해 해결해야 한다. skip은 browser 수용으로 계산하지 않는다. 전체 D-425, installed-only 자산, Android/LCD DEVICE, ARM64 image, FIELD 완료 증거가 아니다. Tasks 4–13과 D-413의 남은 의존 gate를 계속 실행한다.
