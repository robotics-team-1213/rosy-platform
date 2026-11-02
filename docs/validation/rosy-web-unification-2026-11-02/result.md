# ROSY web product unification: source verification (2026-11-02)

Frozen source/UI execution record. Public hashes and results: [receipts](evidence/receipts.json); all126 registered test modules: [coverage](evidence/browser-coverage.json).

## 결과와 범위

[D-961](../../adr/D-961-shared-task-links-and-page-compositions.md)에 따라 공통 네이티브 이동 조작, 작업/인증 화면 폭, 제목·탐색·초점·테마 구조를 기존 공용 자산에 모았다. Learning·Account·Fleet·Robot/CORE 패널·Pilot·Games·Monitoring 및 native Wi-Fi 복구에 적용했다. 로그인 화면은 익명 상태의 불필요한 탐색·중복 설명·항상 보이는 재시도를 정리하고, 권한 거부와 서비스 연결 실패를 분리한다. 로그인 후 계정 관리와 기존 작업 복귀를 보존한다.

제품·시험 소스 기준 SHA는 9ffb4a49447fc485c0ed68b1d98fd8d5280a56f1이며, 작업 로그 형식을 수정한 b1eafb186f는 소스 자산과 실행 코드를 바꾸지 않았다. 공통 기준은 cbfb144767f424f9e082c038fad54f94874ed9a3이다. 모듈 SOURCE/DEVICE/FIELD 등의 과거 gate를 이번 시험으로 일괄 올리지 않았다.

31 tracked HTML, CORE 런타임 패널 20개와 generated Recovery PAGE를 함께 조사했다. Account는 Fleet 제공자의 인증 맥락이며 새 서비스를 만들지 않았다. 보조·parked·네이티브/Harbor 구분은 인벤토리에 남겼다. 모든 역할·상태·화면 조합을 빠짐없이 검증했다고 주장하지 않는다.

## 회귀 증거

모든 pytest는 공식 remote_pytest.py로 고정 커밋을 전달해 실행했다. 브라우저는 ROSY_RUN_BROWSER_TESTS=1을 전달하고 land_browser.vacuous와 known_failures를 확인한다. 노트북에서는 pytest를 실행하지 않았다.

| 실행 | 관측 | 한계/후속 |
|---|---|---|
| FULL source 4c41156633 | 27묶음 중 CORE zero·Fleet 소유 계약 세 실패 | 원본 실패 유지, 각각 수정·재실행 |
| CORE/API source c4f15610cc | 4479 passed/164 skipped/실제 rc0 | 후속 source 델타이며 원본 FULL을 대신하지 않음 |
| FULL source 6d7e296033 | 26/27 exit0; run25 seat fixture 1실패 | CORE 묶음7856 passed/99 skipped, root14325 passed/1474 skipped 포함 |
| FULL run25 재실행 9ffb4a4944 | 2066 passed/432 skipped/exit0 | 합성 fixture만 수정; 운영 신선도 한계 유지 |
| FULL browser c4f15610cc | 113파일·13묶음·1911 passed/skip0/exit0 | 13개 누락 파일을 추가로 발견, 등록 누락 가드 도입 |
| 추가13 browser 6d7e296033 | 통과160건, video fixture3실패 | 실제 runtime.js 누락 fixture 수정; 최종82파일 재실행이 대체 증거 |
| Recovery/registry/native assets 6d7e296033 | 39건 통과 | 복구6건은 두 테마×320/390/1366px, 무선 장치에 접속하지 않음 |
| 인증 복귀 c1af0160f4 | 네 파일64건 통과 | 익명 상태에서 복귀 불가능한 링크 두 건 숨김 |
| 영상/seat fixture a7f36cb999 | 25건 통과 | 실제 영상·장치 수용 아님 |
| 최종 source 9ffb4a4944 | 1 failed/10543 passed/1155 skipped | 로그 형식 검사 실패, b1eafb186f 수정 후 해당 검사 포함 전체 델타 통과 |
| 최종 source b1eafb186f | 10544 passed/1155 skipped/exit0 | known_failures NEW0/known0/flaky0; complete selected source delta |
| 최종 browser 9ffb4a4944 | 82 files/13 chunks/1316 passed/0 skipped/exit0 | known_failures NEW0; no vacuous run; no later UI asset change |

NEW를 known_failures/quarantine에 추가해 숨기지 않았다. 종료한 대기·중복 실행은 통과로 세지 않는다. 소스 skip은 ROS·시뮬레이터·GPU·명시적 브라우저 opt-in 등 실제 미실행으로 남긴다. 브라우저 skip은 수용하지 않는다.

## 렌더링·접근성

배포본 before 15장은 실제로 보호된 다섯 URL이 모두 /accounts로 이동한 관측이며, 인증된 다섯 화면의 캡처로 세지 않는다. 운영 자산이 현재 소스와 달랐으므로 새 화면은 소스와 시험 backend를 분리해 캡처했다.

Monitoring80/Robot72/Games18 및 Fleet/Pilot36의 대표 상태 캡처, 최신 인증8장(a7f36cb999), Recovery6장(5bde1f6d5b)을 보존했다. 대표 모바일·데스크톱 dark/light 이미지를 직접 검토했다. 최신 인증 axe-core4.14.0 검사는 두 화면×두 폭×두 테마 8회로 위반0/판단보류0이다. 320px에서100/200/400% 글자 크기, 긴 글자, 본문 포커스, landmark/접근성 트리, forced colors/reduced motion을 기록했다. 브랜드 핑크는 유지하며 과잉 중립화하지 않았다.

실제 스크린리더 조작, 전체 제품 WCAG 적합성, Lighthouse 점수, 모든 화면의 모든 상태 조합을 확인했다고 주장하지 않는다. 단일 인증 h1 예외, 공용48px/Fleet 기존56px 조작 크기, Robot 소형 viewport의 chrome 예산, canvas/운전/경기 전용 구성을 보존했다.

## 종료 정지 수정과 독립 검토

FULL에서 발견한 WS 명시적 zero 누락은 정상 close 관측과 취소 RED로 분리했다. 누락 zero mutation이 실패함을 확인한 뒤 c69894c0ce에서 AnyIO scope와 반복 asyncio 취소 중에도 진행 중 적용을 마치고 같은 admission/CommandManager로 zero를 보낸다. 대체 스트림 소유와 취소 전달을 유지한다. 12건 GREEN 및 독립 CORE 계약 검토에서 새 writer·권한 우회 발견 없음. zero 관측은 실제 apply 수용이며 물리 bridge receipt나 stop latency가 아니다.

read-only 전체 소스 검토와 후속 검토 9ffb4a4944에서 남은 발견0. 두 익명 복귀 UX 발견은 수정·검증했다. 메타데이터 형식 보완과 최종 동결 기록은 최종 delta 검토 대상이다.

별도 main cbfb144767의 같은 CORE 묶음 비교는 nav-_lock contention 1실패/7850 passed/91 skipped였다. WS 파일 단독은7건 통과했다. 이를 WS 취소 결함의 baseline/flaky 근거로 사용하지 않았다. main 관측의 별도 시간 경합은 미해결로 남고 본 변경의 최종 CORE 묶음은 통과했다.

## 경계와 재확인

운영 SSO 완료, 계정 제공자 개발 모드 전환, 실물 무선/AP, native ARM64 이미지·서명 payload, 물리 로봇·팔·주행·stop latency, 운영 웹 배포는 실행하지 않았다. 라벨·모델 평가·현장 운전 수용 증거가 아니다. 임시 워크트리 한 개에서 작업했고 main·공개 저장소·운영 서비스를 변경하지 않았다.

CE: 해당 없음 — 원인·보존 조건·fixture 범위가 최종 코드·시험·D-961·검증 기록으로 복원돼 별도 교훈을 늘리지 않는다. 운영·물리 수용은 별도다.

원본 로그·선택·해시·이미지 위치 정본은 workspace-records/2026-11-02/rosy-ui-unification 아래 manifest와 verification receipts다. 배포 시에는 사용자 승인 후 착지·PR·릴리스 절차를 따르고, 그때의 main과 활성 자산 해시 및 실제 SSO를 다시 확인해야 한다.
