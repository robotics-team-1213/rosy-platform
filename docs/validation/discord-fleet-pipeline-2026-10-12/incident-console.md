# Discord 사건 Console·설치 경계 검증

2026-10-12. Branch `feat/discord-workflow`. UI source `ed7eba9644`, Fleet 제한 판정 기록 `40707b541`.

기존 사건 조회의 현재 열린 robot/stuck/judgment를 요청 검토 화면으로 전달한다. 현재 원문·review·기명 operator와 같은 판단을 확인창 전후에 검사하며 취소는 POST하지 않는다. 성공한 인수는 token 없는 기존 사건·조치 화면으로 연결한다. 새 polling 서비스나 조치 writer는 없다. 인증 reset/사건 조회 실패는 선택 목록을 비우고 서버의 open/freshness/owner/hash/revision 검증을 보존한다.

## 원격 terminal 증거

로그 root: `X:/DevTemp/projects/rosy-platform/2026-10-12--010335--discord-fleet-pipeline--1dc770/logs/`.

| Source / 로그 | 결과 | 의미 |
|---|---|---|
| `ec65192e8` / workflow-incident-browser-red | NEW2 + 기존8 PASS | 사건 선택 UI 미구현 RED |
| `f18b37458` / workflow-incident-browser-green | NEW2 + 기존8 PASS | 현재 judgment가 있는 기존 native claim 버튼에서 존재하지 않는 scope.listener 호출로 표시 실패 |
| `ed7eba9644` / workflow-incident-browser-fixed | 10 PASS / NEW0 | Model PC 자원 하한 충족, 실제 Chromium 1366/320: 현재 사건 선택→확인 취소→기명 인수→기존 사건 링크 및 기존 Mission/주행 요청 |
| `b01d94101` / workflow-owner-installation | 3 PASS / NEW0 | 실제 wheel/sdist의 새 모듈·canonical DTO re-export, Console71개 hash; Dockerfile COPY 기반 source tree 조립 후 isolated import closure |
| `40707b541` / workflow-final-structure-contracts | 94 PASS / NEW1 | API owner/pin 및 Fleet 크기 판정은 통과, core_common10031 최초 부모 판정 누락은 미해결 |

각 로그를 known_failures.py로 분류했다. 새 실패를 기존 실패로 등록하지 않았다. root 오류는 실제 shared/web/scope.js의 기존 guard로 한 단어 수정했으며 새 helper나 guard bypass를 추가하지 않았다. 설치3은 guard 이름 수정 전 snapshot의 전달 parity이며 실제 Docker image build/서명 배포는 아니다. Chromium은 가짜 API이고 서버/SQLite90 증거와 별개다.

## 독립 책임 검토

safety_structure_review는 UI source `f18b37458`를 승인하고 Fleet 부모54,852 =Fleet35,961 +Decision1,666 +Console16,980 +Discord245로 제한 재판정에 동의했다. 기존 열 개 nested unit을 innermost로 한 번만 제외하며 새 SIZE_UNITS는 없다. +150, 기존 모든 파일 상한/hard tier, app906, TaskStore1035/1060, Console.py1325 zero-growth, proposal_store797의 기존800 초과 seam 재검토, UIconsole1032/1175, schemas1386/1389 및 full-progress/observe/server/UI 추출 의무와 이전 판정 역사를 보존했다. incidents505는360+150 안이며 allowance를 늘리지 않았다.

독립 검토는 ed7eba964의 guard 수정과 최초 core_common10,031 제한 판정에도 동의했다. main9,888 대비 전체 DTO 가족136줄+re-export7줄이며 D-693 이전에도10,012였다. 다음 protocol family 확장 전 실제 계약 subpackage·설치/소비자/방향/단일 facade 및 same-change parent/unit 실측 의무를 계획에 기록했다. package10,000/+150·모든 파일 상한/HARD_TIER·기존 schema 추출 의무를 유지하며 새 SIZE_UNITS는 없다. 현재 committed HEAD 구조 재검증/local FF/CI·서명 배포·실제 Discord 원문→Console→원장→원래 메시지 회신은 아직 미확인이다. provider/로봇 명령 없음. 로봇 오프라인 FIELD는 별도 gate다.
