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

## 운영 수용의 경계

- SOURCE/브라우저/설치는 위에서 실제 확인한 범위만 주장한다.
- 기존 PeerCatalogue가 mDNS 관측으로 등록 directory 행을 대체하면 승인 origin을 이 응답에서 확인할 수 없다. 이 경우 앱 링크를 만들지 않고 연결 안내를 표시한다. 광고를 신뢰하거나 새로운 API를 임의로 추가하지 않는다.
- 새 DEVICE/FIELD·서명 릴리스 설치·실제 사용자 계정 전환은 NOT RUN이다.
- 작업 브랜치를 main에 반영하거나 장치에 배포하지 않았다.
