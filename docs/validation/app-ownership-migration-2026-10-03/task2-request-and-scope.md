# Task 2: 공통 request와 화면 scope

기준: `6892863be`, 브랜치 `refactor/ui-ownership`, 2026-10-03 Windows Python 3.14.5/Node v24.15.0. `request.js`·`scope.js`의 계약과 shared manifest/CMake 목록을 검증했다. 서비스별 client와 화면 연결은 Tasks 3/4의 범위이며 아직 전환하지 않았다.

## 공유하는 계약

`createRequest({origin, credential, fetchImpl})`은 요청마다 credential 공급자를 읽고 `{status,ok,body}`를 반환한다. HTTP 실패의 body/status는 CORE/Fleet adapter가 해석하고 network/abort는 reject한다. 204/비 JSON은 body null이다. 기존 소비자의 다른 decoding/오류/감사 의미는 client 연결 단계에서 보존한다.

- browser 밖에서는 origin을 명시한다. 다른 origin, non-HTTP scheme, URL에 든 자격은 credential 읽기와 fetch 전에 거절한다.
- caller의 Authorization을 전달하지 않고 해당 instance의 credential만 Bearer로 사용한다. credential이 없는 instance는 anonymous다. cookie credential은 omit, redirect는 error로 고정한다. 서버 redirect에 의존하는 caller가 발견되면 올바른 canonical route를 먼저 확인한다.
- timeout과 외부 AbortSignal을 결합하고 요청이 끝나면 timer/listener를 해제한다. fetch/body가 뒤늦게 끝나도 취소된 요청은 결과를 반환하지 않는다.
- token/store 저장, 도메인 endpoint 선택, HTTP 오류 정책, 작업 성공 판정, 재시도/명령 재전송은 넣지 않는다. 이미 서버가 받은 POST를 취소가 되돌린다는 의미도 없다.

`createScope()`는 AbortSignal·generation·handler guard·cleanup 등록을 제공한다. owner가 요청 결과를 적용할 때 capture/isCurrent로 늦은 결과를 거절하고, timer/subscription을 onDispose로 해제한다. advance는 오래된 결과를 무효화하며 dispose는 signal을 취소한다. 하나의 cleanup이 실패해도 나머지를 실행하고 오류를 합쳐 전달한다.

scope가 끝난 뒤 guard로 감싼 handler는 새 요청/paint를 수행하지 않는다. 별도 scope의 signal/generation은 공유하지 않는다. polling interval, freshness 판정, WS close policy, 조종 재개는 화면/장치 owner에 남긴다.

## 증거와 한계

- 구현 전 Node 실행은 request/scope module 없음으로 실패했다.
- 구현 후 Node request/scope: **27 passed**, skip/cancel 0. pytest wrapper·asset manifest·역할 가드: **15 passed**.
- origin 검사 제거, 늦은 응답 abort 검사 제거, dispose 이후 handler 허용, CMake request 자산 누락 변이 모두 예상한 실패를 만들었다. 원본은 byte/digest를 비교해 복원했다.
- 변이 로그: `X:/DevTemp/rosy-ui-ownership/task2-mutations/`. pytest 임시 폴더와 Node log도 X:에 둔다.
- `package.json`은 Node에서 기존 ES module을 시험하기 위한 private/type metadata뿐이다. npm 의존성·bundler·runtime 서버를 추가하지 않으며 정적 allowlist에 넣지 않는다.
- request/scope 자산은 shared-assets.json과 CMake install 목록에 함께 추가했다. 이는 SOURCE 설치 목록 검사이고 실제 ament install/이미지 또는 DEVICE 수용은 Task 6/11에서 별도 확인한다.

공유 UI·API static 회귀·소유권·quick 검사 합계는 **370 passed, 24 skipped**였다. harness lint는 **0 errors, 26 warnings**였다. 건너뛴 browser 검사는 브라우저 수용 증거로 계산하지 않는다. source 폴더와 public identity는 아직 이전하지 않았다.
