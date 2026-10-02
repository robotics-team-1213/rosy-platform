# Task 1: API 소유 선언과 실제 거절·쓰기 계약

기준: `403ea98d0`, 실행: `refactor/ui-ownership`, Windows Python 3.14.5/Node v24.15.0 (2026-10-03). 변경은 SOURCE/LOCAL 계약 검사와 기존 등록부의 `api_owners` 명시다. wire·권한 정책·프로세스·writer는 변경하지 않았다.

## 무엇을 검사했는가

- Robot/Pilot은 CORE, Console 두 문서는 Fleet, Cam은 Fleet pairing/Vision ingest를 소비한다. Face와 공통 UI 자체에는 운용 API 소유가 없다. 선언과 실제 source caller의 대표 fetch 경로를 Node에서 함께 검사한다.
- 실제 FastAPI router와 CORE authenticator를 사용한다. 인증 dependency를 override하지 않는다. 설정 저장·긴급 정지·해제의 side-effect owner와 설정 저장 매체만 로컬 fake로 분리한다. 거절된 요청은 owner를 호출하지 않고 기존 값도 바꾸지 않는다.
- viewer의 CORE 긴급 정지는 기존 정책대로 허용된다. viewer/operator의 영구 설정 저장과 viewer의 긴급 정지 해제는 거절한다. administrator의 저장·해제는 기존 owner를 통해 처리한다.
- Fleet은 실제 create_app/site principal/audit store/역할 guard를 사용한다. camera/CORE 자격은 401, viewer/policy-admin의 사이트 stop은 403이고 Fleet stop owner 호출은 0건이다. operator의 요청은 1번 dispatch한다.
- `/console`·`/console/install`은 같은 Fleet API/CSP/session owner를 사용한다. 실제 브라우저의 문서 간 로그인 이동은 Task 3/11에서 따로 수용한다.
- 공통 transport/UI가 literal 운용 API를 직접 발행하는 가드를 추가했다. CORE/Fleet 계약 adapter는 별도 책임이므로 명시적으로 구분한다. 기존 `evidence.js`의 작업 이름표는 요청 발행이 아니며 거절하지 않는다.

Node 대표 caller 시험은 실제 source의 request 함수 본문을 실행하며 DOM/session hook만 주입한다. 전체 앱 렌더링이나 storage 수명을 증명하지 않는다. 서버 시험은 실제 권한 검사를 사용하지만 최종 하드웨어 출력은 fake이며 DEVICE/FIELD 증거가 아니다.

## Red/green과 변이 증명

신규 등록부 시험: 변경 전 6 failed/15 passed (없는 api_owners), 명시 후 통과. API/role/caller 시험: 33 passed. 복원 후 등록부/manifest 회귀와 전체 quick을 포함한 최종 실행: 144 passed/25 기존 freshness warnings. 기존 Fleet authorization Node suite: 3 passed.

| 변이 | 실제 실패 | 복원 |
|---|---|---|
| Robot api_owners CORE → Fleet, 실제 구현 유지 | owner 선언 검사 1 failed/5 passed | 원본 byte/digest 일치 |
| CORE limits admin guard → viewer guard | viewer/operator 거절 시험 2 failed/3 passed | 원본 byte/digest 일치 |
| Fleet operator guard 제거 | viewer/policy-admin 거절 시험 2 failed/3 passed | 원본 byte/digest 일치 |
| 공통 ui.js에서 literal teleop 요청 발행 | 공통 호출 경계 검사 1 failed | 원본 byte/digest 일치 |

변이 결과와 pytest 임시 폴더는 `X:/DevTemp/rosy-ui-ownership/task1-mutations/`에 있다. 각각 변경 bytes를 읽어 변이가 실제 적용됐음을 확인했고 `finally`에서 byte-for-byte 복원했다. 복원 후 green을 다시 확인한다.

Pilot DEVICE 전 Robot 이행용 teleop은 유지했다. Cam의 stop/drive 자격은 추가하지 않았다. 폴더 이전은 아직 하지 않았고 다음은 Task 2의 공통 request/scope 추출이다.
