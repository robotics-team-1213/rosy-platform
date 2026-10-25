# 외부 앱 ARM 제안의 Fleet 승인 화면

## 구현 범위

기존 중립 ARM 제안은 Cell step을 만들지 않으므로 `/api/fleet/work`의 Cell 목록에 나타나지 않는다. 기존 목록의 승인 단추도 legacy Mission 경로를 사용했다. 알려진 ARM 작업을 해당 목록에 섞지 않고 Fleet 소유의 별도 조회·승인 화면에 연결했다.

`/console?view=work&arm_transfer=<mission_id>`는 원본 조회만 시작한다. 수동 조회도 같은 경로다. 다른 기명 운영자가 물체·출발·목표 참조와 제안자를 읽고 확인 대화상자에서 실행을 승인하면 기존 ARM `/admit` API에 조회한 proposal digest와 dispatch generation을 보낸다. 승인 시 장치 실행이 시작될 수 있음을 표시한다. 조회·로그인·새로고침은 승인하지 않으며, 거절이나 응답 유실 뒤에는 원본 재조회 없이 다시 보낼 수 없다. 서버의 독립 승인·scope·세대·자원 검사가 최종 권한이다.

로그인 복귀는 업무 화면에 있는 단일 ARM 식별자만 보존한다. 입력과 복귀 규칙은 기존 `ArmActionId`의 192자 ASCII 범위와 같고 중복 식별자·경로 문자열은 복귀에 보존하지 않는다. 새 자산은 기존 manifest에 등록했다. 공유 버튼·입력·색상·CSP를 유지하고 기존 work size unit은 1,000줄을 넘어 `small` 표시를 졸업했다. 제어 API·observer credential·장치 owner는 추가하거나 바꾸지 않았다.

## 검증

원본 로그는 작업 공간의 2026-10-25 기록에 아래 폴더 이름으로 보존한다. pytest와 Chromium은 공식 원격 runner가 고정한 커밋에서 실행했다. 합성 capability는 실물 근거가 아니다.

| 소스 | 로그 폴더 | 결과와 범위 |
| --- | --- | --- |
| `900f5e7e4b` | `arm-console-browser` | 최초 브라우저 7 실패. 팩토리가 console의 auth 초기화 전에 주입 콜백을 읽던 문제를 찾았다. |
| `3bf85c7b06` | `arm-console-browser-fixed` | 브라우저 7 passed, skip0, 공식0 NEW. 빈 상태에서는 세션 콜백을 읽지 않도록 고쳤다. |
| `915a46da52` | `arm-console-real-http-fixed` | 브라우저 8 passed, skip0, 공식0 NEW. 실제 HTTP·SQLite의 독립 승인 포함. 최초 API-only fixture의 공유 정적 자산 누락은 `arm-console-real-http`의 1실패/7통과로 보존했다. |
| `4599f29734` | `arm-console-login-final` | 브라우저 9 passed, skip0, 공식0 NEW. 로그인 인계 보존과 기존 비밀번호 로그인 회귀 포함. |
| `4e3f9bc40c` | `arm-console-contract-final` | 계약 matrix·자산·실제 ARM API·설치 패키지·palette 62 passed, skip0, 공식0 NEW. |
| `bfa3872d0c` | `arm-console-controls-final` | 공유 controls·크기 경계·계약 matrix 87 passed, skip0. 광역 선택에서 발견한 네 source guard 실패의 보완이다. |
| `bfa3872d0c` | `arm-console-browser-final` | 최종 UI의 ARM·실제 HTTP·로그인 브라우저 9 passed, skip0, 공식0 NEW. |
| `f3a818e997` | `arm-console-owner-final` | 문서별 import 경계·공유 확인 소유자 핀 4 passed, skip0, 공식0 NEW. |
| `f3a818e997` | `arm-console-g1-strict` | 기존 G1 timing strict 별도 실행 2 failed, 2 passed, skip0. 아래 미해결 경계에 속한다. |

Node 전체는 기존 두 URL loader를 사용해 365 passed, skip0였다. 독립 승인 identity 조건을 반전한 mutation이 실제 diff에 들어간 상태에서 단위 시험이 실패했고, 복원 후 통과했다. Node만으로 팩토리 시작 순서를 검증했다고 주장하지 않는다.

실제 HTTP 브라우저는 다른 Fleet 계정으로 원본을 읽고 확인 대화상자를 거쳐 실제 `/admit`을 호출했다. 제안자는 유지되고 승인자가 독립 operator로 기록되며, 응답 상태 READY·동일 proposal digest·현재 dispatch generation·참여자 capability 두 조회를 검증했다. 클릭 전에는 POST와 capability 조회가 없다. 이 fixture에는 실행 dispatcher나 관측 producer가 없어 액추에이터·물리 확인·외부 앱의 업무 완료를 증명하지 않는다.

광역 선택은 이 작업 직전 `f4a934657ff72fd3d274860c8e6bb524292f6e77`을 기준으로 계산했다. mode는 affected, escalation은 없고 두 invocation을 모두 실행했다. `3bf85c7b06`의 `arm-console-affected-fixed/run-1.txt`는 4 failed/4801 passed/248 skipped/879.04초, run-2는 4 failed/6717 passed/343 skipped/1209.38초다. 공식 분류는 각각 4 NEW다. 앞의 네 실패는 API matrix 미등록·공유 버튼 선언·입력 class 선언·work unit의 small 표시였으며 62/87 focused 범위에서 보완을 검증했다. 뒤의 import allowlist와 확인 소유자 핀 두 실패도 4 focused 범위에서 검증했다. import는 Console OWN에만 추가했고 확인 핀은 추가한 두 호출 위치의 정확한 수만 바꿨다. guard를 제거하거나 범위를 넓혀 면제하지 않았다.

나머지 두 실패는 기존 `test_platform_g1_timing.py`의 tight-segment coordinator liveness와 실제 UDS round-trip bound다. 별도 serial strict 실행에서도 2 failed/2 passed로 재현됐다. UI 작업에서 이 시험·G1 하네스·OMX owner를 바꾸지 않았지만, 이 사실만으로 known failure나 환경 문제라고 확정하지 않는다. 한계를 완화하거나 flaky 목록을 바꾸지 않았다. 전체 affected는 GREEN이 아니며 이 기록은 전역 통과를 주장하지 않는다. 중간 실패·skip·겹치는 suite 수치를 통과로 합산하지 않는다. 최초 `900f5e7e4b` 광역 실행은 소스가 대체된 뒤 정확한 두 owned job을 공식 종료 템플릿으로 TERM해 두 invocation exit143으로 보존했고 수용 근거에서 제외했다.

## 착지와 운영 경계

작업은 기존 `feat/neutral-arm-actions` continuation에 보존했다. `tools/land.py --tests auto --dry-run --no-prune`은 실제 merge 충돌을 보고하고 exit1로 끝났다. 당시 main은 이 브랜치의 조상이 아니었으며 main..topic은 140개 커밋, merge-base부터 175개 파일이었다. 충돌에는 work UI·manifest뿐 아니라 protocol·Fleet app/dispatch·OMX owner·API 정본이 포함됐다. 이 UI 변경의 검토·시험을 전체 기존 주제의 충돌 해결이나 main 착지 근거로 확장하지 않는다. main·다른 세션 파일·실물 서비스는 바꾸지 않았고 push하지 않았다.

외부 앱이 이 ARM 화면을 승인 목적지로 안내하려면 이 UI가 설치된 Fleet 배포인지 별도로 선언해야 한다. 설정 origin이나 health 응답만으로 호환성을 판단하지 않는다. ACTION_SUCCEEDED는 물리 근거 대기이며 GOAL_CONFIRMED도 외부 앱의 업무 완료와 별개다. 실물 보정·장치 수용·현장 운영은 이 화면 시험의 범위 밖이다.

CE: 해당 없음. 초기화 결함·정적 자산 fixture·공유 controls와 크기 표시는 최종 구현과 직접 실행한 회귀 시험에서 복원할 수 있다. 별도 환경·장치 지식이 없어 해결 교훈을 늘리지 않는다. 이전 중립 ARM 주제의 미해결 G1 timing 원인은 이번 화면 변경으로 해결했다고 주장하지 않는다.
