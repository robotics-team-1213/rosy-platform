# Fleet 대화 요청 목록의 키보드 초점

2026-10-29 · `fix/fleet-request-focus` · base `62db787222` · runtime `bd8f9de627` · 최종 코드/시험 `b90b4569bc`.

## 변경

작업 화면의 대화 요청 목록은 주기적으로 DOM을 교체해 `요청 검토` 버튼의 초점을 잃었다. 기존 작업 목록과 같이 요청 ID로 현재 초점을 복원한다. 현재 초점은 GET 완료·수명 확인 뒤 DOM 교체 직전에 읽으므로 기다리는 동안 다른 곳으로 이동한 초점을 빼앗지 않는다. 요청이 없어지거나 조회가 실패하면 tabindex=-1인 기존 상태 문구로 이동한다. 상위 작업 조회 실패의 reset도 같은 목록 정리 함수를 사용한다.

공용 ui-button·색/배치와 Fleet API·권한·검토/승인·원장·명령 경로는 유지했다. 초점 복원은 검토 선택이나 추가 쓰기를 실행하지 않는다. 새 의존성·일반화된 초점 프레임워크는 없다.

## 원격 검증

모든 pytest는 커밋된 SHA를 승인된 시험 PC에서 실행했다. 로그/캡처 manifest 경로는 외부 scratch `C:/DevTemp/rosy-ui-standardization/` 기준이다.

| SHA / 로그 | 결과 | 범위 |
|---|---|---|
| `0f2275b765`, fleet-focus-red/run-1.txt | 18 failed, 4 passed, 36 deselected | 수정 전 같은 목록/재정렬/삭제/빈 목록/오류/다른 행으로 이동 후 초점 유실. NEW18/known0/flaky0 |
| `b90b4569bc`, fleet-focus-green/run-1.txt | 80 passed, 0 skipped | 기존 파일 전체36과 강화한44조합, NEW0/known0/flaky0 |
| `b90b4569bc`, fleet-focus-affected/run-1.txt | 8004 passed, 631 skipped, 64 warnings | 공식 affected 전체 invocation exit0, NEW0/known0/flaky0 |

44조합은320×568/1440×900 × dark/light × 같은 목록·재정렬·행 삭제·빈 목록·request GET404/403/503·상위 work GET503·대기 중 다른 행/목록 밖 이동·처음부터 목록 밖 초점의11결과다. 실제 DOM 교체가 끝난 뒤 ID에 맞는 초점·상태 fallback을 검사한다. 기존 오류 처리와 입력/목록 밖 초점은 유지하며 새 POST가 없음을 확인한다. 44를80에 다시 더하지 않는다. 631 skip을 브라우저 실행이나 native 기기 검증으로 세지 않는다. 이 affected 결과는 전체 CI/FULL 수용이 아니다.

## 독립 검토와 화면

A가 runtime diff의 GET 이후 초점 획득·ID 복원·삭제/오류/상위 reset·scope guard를 검토했고 추가 P1/P2는 없다. B는 최종 `fleet-focus-captures-final/`의16장을 모두 직접 확인했다. 재정렬 시 request-a 버튼, 삭제 시 상태 문구, 목록 밖 이동 시 작업 새로고침, 요청503 시 오류 문구의 초점 테두리를 두 폭/테마에서 확인했다. 320에서도 문구·테두리 겹침/잘림이 없고 상단 비상 정지가 보인다. Root도320 light 삭제,1440 dark 재정렬 두 장을 직접 확인했다.

캡처16장은 위 네 결과×두 폭×두 테마다. 모바일은 초점 대상을 따라 스크롤된 viewport이며 초기 화면·아래 개입 패널 전체를 판정하지 않는다. 이미지에 없는 GET403/404·work503 등은 브라우저 assertion 근거와 구분한다. 실제 정지 전달이나 장치 동작은 검증하지 않았다. 캡처는 JOB TEMP 밖의 전용 scratch에 보존하고 실행 종료 뒤16장을 복사했다.

## 게이트와 CE

소스 UI 근거만 추가했으며 ARTIFACT/DEVICE/FIELD gate는 바꾸지 않았다. 로봇·실제 HF·라벨·기하·native 빌드·배포·착지·공개 push/merge는 수행하지 않았다. 다른 UI와 통합 후보 수용은 진행 중이다.

CE: 해당 없음 — 기존 key 복원 패턴을 재사용했고 await 경계·상태 fallback의 이유는 코드와 회귀로 복원된다. 실패와 검증 범위는 이 기록에 보존했다.
