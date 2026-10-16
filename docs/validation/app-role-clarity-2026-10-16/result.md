# 앱 책임 정리 실행 기록

## 범위

최종 작업 브랜치는 `feat/app-role-clarity`, 기준은 `436d52a55`다. 계획·TDD 체크포인트는 `docs/app-role-clarity` 브랜치에 보존한다. [설계](../../plans/2026-10-16-app-role-clarity-design.md)와 [실행 계획](../../plans/2026-10-16-app-role-clarity.md)을 수행했다. main 착지·push·배포·새 DEVICE/FIELD 시험은 이번 실행에 포함하지 않았다.

## 변경과 이행

| 작업 | 결과 |
|---|---|
| 업무 소유표 | [앱별 작업과 책임](../../reference/app-responsibilities.md)에 화면/API/정본/실행/완료 확인과 전체 표면 분류를 연결 |
| Fleet → Robot/Pilot | 로봇 카드에서 승인 directory의 대상별 앱으로 일반 페이지 이동. 포트 추정·토큰 URL 전달·조종 자동 시작 없음 |
| Robot → Pilot → Robot | Robot 상태 패널에서 same-origin `/pilot` 링크 추가. 기존 Pilot `/console` 복귀의 정지/readback 경로 유지 |
| 중복 조종 | 아래의 대상별 실기 증거 예외를 유지. 신규 직접 운전 진입은 Pilot으로 안내 |
| Learning 이름 | 기존 Learning 앱 바와 D-339 개발 표면의 탭 제목 규칙을 구분해 유지. 별도 런처로 등록하지 않음 |
| 기존 완료 표시 | Fleet 공통 정지는 이미 요청 응답/물리 정지 미확인을 구별. Cam/Face/Vision 권한과 검수 export owner는 유지 |
| 설치 | 장치 읽기·앱 이동 adapter를 기존 allowlist·wheel/sdist에 포함. 기존 설치 시험의 모든 자산 byte/hash와 HTTP GET 검사로 확인 |

기존 Pilot DEVICE GO는 [2026-10-05 사용자 확인](../pilot-device-user-confirmed-2026-10-05/README.md) 그대로다. 이 자료는 현재 릴리스별 대상과 연결 단절 측정을 모두 연결하지 않으므로 Robot `console.teleop`을 전체 대상에서 제거하지 않았다. 실기 수용을 새로 낮춘 것이 아니라 이번 변경의 적용 범위를 제한한 것이다. OMX SIM이나 Android 연결 증거를 다른 장치의 수용으로 확대하지 않는다.

## 확인한 시험

pytest와 Chromium은 원격 시험 PC에서 committed SHA로 실행했다. 노트북에서 pytest를 실행하지 않았다. 이 환경에 `X:/DevTemp`가 없어 원시 로그는 실행자의 Windows TEMP 아래 `rosy-app-role-clarity/`에 보관한다. 공개 기록에 장치 주소·계정·토큰은 포함하지 않는다.

| 소스 SHA | 로그 묶음 | 시험·판정 |
|---|---|---|
| `d19abd20b` | `baseline` | 기존 app roles/실제 API owner/Robot 패널/Fleet 문서 import 51 passed, exit 0 |
| `d6f5ce977` | `task2-red` | Fleet 앱 링크 부재로 신규 브라우저 시험 실패 확인. Windows 출력 인코딩 오류와 별개로 원격 원시 로그에서 assertion 확인 |
| `3640336e1` | `task2-green` | 최초 대상·주소 거절 8 passed |
| `90b6d4902` | `task2-robot-red-fixed` | Robot Pilot 링크 부재와 malformed directory 예외 재현 |
| `d93f1ef72` | `task2-all-green` | 신규 이동·주소·연결 장애·Robot 진입 13 passed |
| `e4ad8556c` | `browser-regression` | Fleet workflow + Robot panel 전체 45 passed |
| `e596dc451` | `contracts-installed-green` | 기존 계약 + checkout 밖 wheel/sdist 실제 설치·자산·HTTP 55 passed |
| `64dd224a0` | `pilot-handoff` | Pilot 정지 확인 뒤 Robot 복귀/거절/withheld 7 passed |
| `64dd224a0` | `learning-regression` | 네 검수 문서 탐색과 평가 자료 export 차단 5 passed |
| `90ae3becb` | `review-red-ready-host` | 승인 신원의 mDNS 광고가 transport/port를 바꾸는 링크 생성 재현. negative case 실패 확인 |
| `6af9df53e` | `review-lifetime-red` | BFCache 복귀 후 세션 검증을 보류하고 대상을 다시 선택하면 이전 링크 2개가 살아나는 실패 확인 |
| `18941a87b` | `review-fixes-green` | 리뷰 두 건 수정 뒤 Fleet workflow + Robot panel 50 passed, exit 0. 390/1200/1366px 이동·정지 가시성 포함 |
| `18941a87b` | `installed-final` | 리뷰 수정 소스의 기존 계약 + standalone wheel/sdist 설치 55 passed |
| `674e2d274` | `split-guards-green` | 분리 후 제목/전체 구조/Fleet 문서 import/실제 wheel·sdist 설치 46 passed, exit 0 |
| `ee963467e` | `device-js-green` | 연결·주소 이동·dialog/API 41 passed, exit 0. Node 하위 회귀는 전체 console web specs를 실행 |
| `bdce6a9e4` | `final-validation` | 최종 제출 트리에서 Chromium/실제 API owner/연결·Node/제목/전체 구조/standalone wheel·sdist/문서·harness **305 passed, exit 0**. 진행 결과 305개 전부 pass, skip 없음 |

추가 계정 전환 시험의 초기 실패는 링크 잔존이 아니라 계정 재접속 때 기존 선택 카드가 해제되는 것을 시험이 반영하지 않은 문제였다. 새 세션에서 대상을 다시 선택하도록 시험을 정리했다. 정지/읽기 동작 자체를 바꿔 이 시험을 맞추지 않았다.

## 독립 리뷰와 최종 확인

한 명의 독립 리뷰어가 `436d52a55..e47df436f`를 읽기 전용으로 확인했다. Important 두 건은 (1) 승인 신원에 결합된 mDNS 광고의 transport/port를 이동 권한으로 오인할 수 있음, (2) BFCache 복귀 때 이전 peer cache가 세션 검증보다 먼저 보일 수 있음이다. 두 시나리오의 실패를 확인한 뒤 한 회차에 수정했다. directory만 허용하고 페이지 수명·principal/role 변경 시 revision/cache/렌더된 링크를 폐기한다. `18941a87b`의 원격 브라우저 회귀 50개가 통과했다. 리뷰는 실제 장치 시험이 아니다. Minor 지적이나 판단 유보 항목은 없었다.

첫 affected 회차의 네 실패와 해당 수정·재검증은 아래에 기록한다. 브라우저 opt-in 없는 affected 회차에서 건너뛴 시험은 통과로 집계하지 않았으며 별도 Chromium 회귀를 실행했다.

## 크기 제한에 따른 선행 분리

첫 affected 회차(`e47df436f`)는 8,407 passed / 926 skipped / 4 failed, 두 번째 invocation은 58 passed였다. 네 실패는 (1) Learning을 독립 앱으로 등록하지 않은 개발 표면의 제목 규칙, (2) D-766 기존 root와 console.js 증가 금지, (3–4) docs 생성 기록 노후와 그것을 포함한 lint였다. 새 사용자 동작 실패로 덮지 않고 각각 처리했다.

- Learning 제목은 기존 개발 범위 규칙으로 복원했다. 화면의 Learning 브랜드와 업무 소유는 유지한다.
- `devices/`에 기존 enrollment/camera-pairing 구현을 그대로 옮기고, 발견·주소 안내와 승인 앱 이동을 읽기 adapter에 모았다. public asset URL과 등록 API·권한은 유지한다.
- 독립 분리 검토는 C2의 별도 실패/수명 관리 경계를 확인했다. 기존 두 파일과 추출 함수 본문은 줄바꿈·들여쓰기를 제외하면 동일했다. 새 파일 최소 150줄 지적은 관련 앱 링크 함수를 같은 읽기 adapter에 합쳐 154줄로 해결했다. 줄 채우기나 새 작은 단위 예외는 추가하지 않았다.
- 새 `devices` 크기 단위는 약 1,200줄로 바닥 1,000줄과 천장 10,000줄 사이이다. 기존 Console root는 13,327 → 12,204줄, console.js는 1,069 → 981줄로 줄였으며 기존 초과의 down-only 기록도 낮췄다. 남은 기존 초과를 한도 아래로 완전히 나눴다고 주장하지 않는다.
- 생성 문서와 작업 로그를 정리하고 회귀·설치·구조 검사를 다시 실행한다.

최종 제출 브랜치는 D-766의 커밋별 검사에 맞게 최종 트리를 하나의 변경으로 구성한다. 실패를 확인한 TDD 체크포인트의 브랜치와 SHA는 보존하며, main 또는 다른 세션의 브랜치는 다시 쓰지 않는다. 최종 SHA·생성 문서·커밋 범위 검사는 마지막 확인 후 추가한다.

## 최종 판정

- 최종 제품 코드 SHA: `bdce6a9e4` (`feat/app-role-clarity`). 후속 receipt 커밋은 문서만 갱신한다. TDD 체크포인트는 `docs/app-role-clarity`의 `3fa99097d`까지 그대로 남겼다. 두 최종 트리는 제품 코드가 같다.
- 최종 원격 invocation: `ROSY_RUN_BROWSER_TESTS=1`을 켜고 Fleet workflow/Robot panel, 실제 API owner, Node·연결·주소·dialog, 제목·모듈 구조, 설치, 문서·harness의 16개 시험 모듈을 실행했다. 305 passed / 0 failed / 0 skipped, exit 0이다.
- `known_failures.py final-validation/run-1.txt`: `0 new, 0 known, 0 flaky`.
- `rosy_harness.py generate` 후 `lint`: 오류 0, 기존 검증 기록 노후 경고 30개. 이 경고를 해결했다고 주장하지 않는다.
- `size_range.py 436d52a55 HEAD`: 최종 제품 변경 1개 커밋 통과. 처음부터 증가 제한을 지키는 제출 이력을 만들었으며 다른 세션의 history/branch는 수정하지 않았다.
- 독립 행동 리뷰 Important 2건과 분리 경계 리뷰의 최소 파일 크기 지적을 해결했다. 미룬 Minor 항목은 없다.
- 기존 큰 단위의 감소와 승인된 경우의 앱 이동까지 완료했다. 대상별 실기 이행 예외, directory origin이 없는 경우의 안내, CI/배포/새 DEVICE/FIELD 미실행 범위는 그대로다.

## 실행 중 선택한 사항

1. 이 환경에 X 드라이브가 없어 원시 로그·진행 원장은 Windows TEMP에 뒀다. 실험실 기본 경로와 다르며 공유할 때 원시 파일을 별도로 옮겨야 한다.
2. Robot의 기존 저속 조종은 대상별 실기 증거가 채워질 때까지 유지했다. 일시적인 두 조작 경로가 남지만 기존 Pilot DEVICE GO를 전체 대상의 수용으로 확대하지 않았다.
3. Git 작성자 설정이 없어 커밋은 명령별 `Codex <codex@openai.com>`으로 만들었다. 사용자 전역 설정은 바꾸지 않았고 사용자 명의의 커밋으로 가장하지 않았다.
4. 링크는 approved directory origin에만 허용했다. 광고가 directory 행을 대체하면 일부 로봇은 앱 링크 대신 안내를 보며, 이 범위를 넓히는 API 계약은 별도 작업이다.
5. Learning 제목은 독립 앱 이름으로 바꾸지 않고 기존 개발 범위 규칙을 보존했다. 탭에는 개발 범위가 남고 화면 안에는 기존 Learning 브랜드를 유지한다.
6. TDD 이력은 원래 브랜치에 보존하고 최종 트리를 새 feature 브랜치의 하나의 커밋으로 구성했다. 로컬 브랜치가 두 개 남지만 크기 검사의 제출 범위에 실패 체크포인트를 포함하지 않는다.

## 운영 수용의 경계

- SOURCE/브라우저/설치는 위에서 실제 확인한 범위만 주장한다.
- 기존 PeerCatalogue가 mDNS 관측으로 등록 directory 행을 대체하면 승인 origin을 이 응답에서 확인할 수 없다. 이 경우 앱 링크를 만들지 않고 연결 안내를 표시한다. 광고를 신뢰하거나 새로운 API를 임의로 추가하지 않는다.
- 새 DEVICE/FIELD·서명 릴리스 설치·실제 사용자 계정 전환은 NOT RUN이다.
- 작업 브랜치를 main에 반영하거나 장치에 배포하지 않았다.

## main 착지 추가 검증

- `land.py --tests auto`가 파일 이동을 감지하여 원격 FULL 및 브라우저 검증을 선택했다. 선행 구조·harness 247개 통과.
- 최초 FULL Fleet: 5357 passed, 315 skipped, 2 failed. 두 실패는 discovery 모듈 분리 후 기존 console.js에서 코드를 찾던 계약 시험이다. 새 HTTP 자산·import 연결을 확인하도록 시험을 수정했다.
- 최초 FULL 공통: 7945 passed, 1055 skipped, 1 failed. 문서의 전체 commit SHA를 secret scanner가 high-entropy token으로 판정했다. 같은 커밋의 짧은 SHA로 표기했고 scanner 규칙은 변경하지 않았다.
- 제품 동작 변경 없이 시험·증거 표기를 보정했다. 최종 착지 성공 여부는 `land.py` 실행 결과로 확인한다.
- 공통 UI 검사에서도 이동 전 enrollment/camera-pairing 경로 3건을 수정했고 원격 40개 검사가 통과했다. 앞선 Fleet·release guard 보정의 원격 재검증은 107개 통과했다.
- Fleet 경로 보기 브라우저 실패는 패널 중앙 클릭이 배치에 따라 대형 관리 버튼을 누르던 시험 문제였다. 폼을 떠나는 동작을 상태 탭 클릭으로 명시했다.
- Learning 첫 화면 배치 실패는 변경 전 main `436d52a55`의 동일 시험에서도 재현됐다(`/pixels` canvas y=692, 1280×720). `main-browser-baseline/run-1.txt`를 근거로 기존 실패 목록에 기록했다. 같은 실행에서 Fleet 단일 시험은 통과했으나, 작업 브랜치의 파일 전체 실행에서 패널 중앙 클릭 문제는 재현됐다.
- Fleet 경로 보기 파일 전체 23개는 탭 클릭 수정 후 원격 통과했다(`card-trip-fix/run-1.txt`).
- 추가 브라우저 실패 4건도 변경 전 main `436d52a55`에서 재현했다. Learning 작은 화면 배치, Robot 만료 토큰 시험의 account/session 요청 순서, shell estop 시험의 CSP string predicate, calibration 시험의 core_api_web import 누락이다. 각각 `main-browser-baseline-2/run-1.txt`, `main-browser-baseline-3/run-1.txt` 근거로 기존 실패 목록에 기록했다. 보안·인증·정지 제품 계약이나 해당 테스트는 완화하지 않았다.
- 최신 main 통합에서 D-766 개정 2의 크기 기준을 보존했다. 앱·지도 기록 링크 생성은 기존 devices 모듈로 옮겨 roster.js 709줄, console 단위 12,188줄로 낮췄다. 커밋별 크기 검사와 린트 통과 후 최종 원격 FULL을 실행했다.
- 최종 FULL의 Learning 검색 시험에서 이미지 로딩 표시가 사라져도 좌표 입력이 잠시 disabled인 상태를 관찰했다. 검색 실행 전에 실제 대상 입력이 enabled가 되는 것을 기다리도록 시험을 보정했다. 제품·인간 라벨 데이터는 변경하지 않았다.
