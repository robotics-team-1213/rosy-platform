# 실측 카메라 교정 운영 연결의 구현과 검증

2026-10-16~17. 구현 브랜치 `feat/measured-camera-calibration`, worktree
`.worktrees/camera-calibration-ready`. 개발 과정의 RED 커밋은
`docs/camera-calibration-lifecycle`에 보존했다. main 착지·push·배포는 하지 않았다.

## 구현 범위

D-775/API v1.256은 D-636의 실제 수치 출력에서 versioned bundle을 내보내고,
기존 Fleet 교정 DB의 preview 목적에 승인·선택·철회·감사를 원자적으로 보존한다.
Vision은 source 설정, 활성 지도, 현재 연결 session, 촬영 geometry, 운영자의 signed 확인을
맞춘 뒤 기존 plane renderer로 영상을 만든다. 설정 lease는 최대 5초이며 변경·철회·만료나
조건 불일치에서 결과를 폐기한다. Console은 import→오차 한도→승인→촬영 확인→영상→철회를
연결하고 늦은 응답을 source/화면 생애에 결속한다.

Tracking/sighting 허용 revision, World MapPose, 주행 admission과 CORE 최종 명령을
변경하지 않았다. 높은 로봇 마커를 새 바닥 plane으로 sighting 처리하지 않는다.
기존 책임의 Fleet tracking holder와 Console calibration 단위 분리는 import·자산 URL을 유지한다.

## 커밋과 시험 증거

개발 `6fb713993`과 구현 커밋 `16bba4a00`의 전체 tree는
tree digest `dc4ccd5479e6e675542d0fff6cf6e88923bb4154`로 같다. 중간 커밋의 크기 위반을
전달 이력에 넣지 않도록 새 브랜치에서 최종 diff를 한 커밋으로 구성했다.
기존 브랜치를 다시 쓰거나 지우지 않았다. `d0a2929e1`은 새 자산 91개와 tracking holder의
wheel byte 일치를 정확한 설치 목록에 반영한다.

외부 증거는 `C:/DevTemp/camera-calibration/`에 둔다. 각 최종 실행의 `runner.txt`는
runner가 보고한 커밋·시험 명령·시험 PC 선택·종료 코드를 담는다. `run-N.txt`는 pytest
원문이고 `known.txt`는 기존 실패 비교다. 과거 초기 실행의 메타데이터는
`historical-observations.md`에 **세션 tool transcript에서 재구성한 관측**으로 구분했다.
원시 pytest 요약만으로 커밋이나 실행 호스트를 입증하지 않는다.

| 실행 | 커밋 | 관측 결과 |
|---|---|---|
| `vision-regression` | `d09a51b4dc` | 공유 계약+Vision 전체 1,603 passed, NEW 0 |
| `structure-browser` | `d09a51b4dc` | 298 passed, 설치 자산 수 88→91 미반영 2 failed; 완료 증거로 사용하지 않음 |
| `delivery-installed` | `d0a2929e10` | wheel/sdist 포함 4 passed, NEW 0 |
| `delivery-affected` | `d0a2929e10` | run-1: 9 failed/9,828 passed/680 skipped; run-2: 2 failed/4,944 passed/164 skipped. 아래 수정으로 분류; 초기 결과를 GREEN으로 보지 않음 |
| `delivery-browser` | `d0a2929e10` | opt-in Chromium 166 passed, skipped 없음 |
| `delivery-vision` | `d4744b1758` | grant 보완 뒤 공유 계약·Vision 전체와 실제 API→render 통합 1,610 passed |
| `delivery-controls` | `1a9efa0baa` | 변경 session의 확인란·UI 계약·API changelog·wheel/sdist 79 passed |
| `provenance-green-2` | `b367260187` | 공개 provenance의 exact binding/변조 거절·비밀 guard·실제 통합 128 passed, NEW 0 |
| `fleet-isolated-green` | `a49062a0ef` | Fleet 단독 수집에서 실제 API→render 통합과 정확한 stylesheet 목록 4 passed |
| `release-check/run-1` | `a0a864b6ea` | 9,872 passed, 656 skipped, NEW 0 |
| `release-check/run-2` | `a0a864b6ea` | 4,999 passed, 188 skipped, NEW 0 |
| `release-check/run-3` | `a0a864b6ea` | Fleet 전체 5,372 passed, 315 skipped, NEW 0 |

최종 관련 원격 회귀는 **20,243 passed / 1,159 skipped**, 세 invocation과 runner 모두 exit 0다.
skipped는 통과 수에 넣지 않았다. 앞의 opt-in Chromium 166 passed와 새 촬영 session의
확인란 회귀(79개 묶음에 포함된 2개 화면 폭)는 별도 커밋의 추가 증거이며 합산하지 않는다.
`release-check/receipt.json`은 실제 실행 커밋, selection/runner/원문 로그 digest와 각 기존 실패
비교를 결속한다. 최종 코드는 이 검증 뒤 바꾸지 않았고 완료 범위·결과 문서만 정리했다.

최초 합친 광범위 명령은 Fleet/Vision의 동명 `test_led_identity.py` 수집 충돌로 실행되지
않았다. 이후에는 저장소 affected grouping과 분리된 명령을 사용한다. 수집 실패는 통과로
세지 않는다. 이전 실행 수치를 최종 커밋의 시험 수에 합산하지 않는다.

`delivery-affected.json`은 기준 `89d3ba4d1` 대비 **FULL**이다. 공유 foundation, 폴더 이동,
source layout이 승격 사유다. remote runner의 `local_invocations`는 프로젝트 정책에 따른
관련 범위이며 전체 CI를 대신하지 않는다. 전체 GitHub CI 요구는 남아 있다.
`delivery-installed`는 같은 커밋에서 별도로 실행해 affected 중복 실행에서만 제외했다.

## 독립 검토와 수정

읽기 전용 독립 계약 검토는 `723716aea..fb2422fed`를 확인했다. 세 P2 지적과 연속 스트림
검증 공백을 `27e388ad5`에서 실제 RED로 재현했다(6 failed, 22 passed).
`4f24f5b39`는 해당 경우들을 통과했지만 새 통합 fixture의 지도 ID가 달라 1 failed였으므로
그 실행을 전체 GREEN이라 부르지 않는다. `d09a51b4dc`에서 실제 map ID를 연결했다.

- ingest가 모든 수신 frame의 geometry를 관찰한다. 읽기 사이 A→B→A 변화도 확인과 진행 중
  ticket을 무효화하고 소비한 옛 확인 grant를 재사용하지 않는다.
- Console의 화면 이탈은 source 읽기 생애를 abort하고 generation을 바꾼다. 후보와 입력
  한도는 보존하면서 옛 렌더가 image/applied를 복원하지 못하게 한다.
- JSON lens model이 list/dict이면 검증 오류로 거절한다. uncaught TypeError가 되지 않는다.
- 최신 frame이 계속 도착해도 그리는 frame 자체가 신선하고 동일 session/geometry/config이면
  완료할 수 있다. 최신 객체와 같은지 비교해 영상을 영원히 거절하던 경로를 제거했다.

추가 author 점검에서 이미 확인된 동안 새로 받은 grant와 아직 Vision에 도착하지 않은 grant도
조건 변경 뒤 재사용될 수 있음을 `cbd516692`/`3ce31d96f`의 RED로 확인했다.
`d4744b1758`은 수신 geometry 변화마다 촬영 epoch를 session에 포함하고, 받아들인 추가 grant도
소비한다. 변경 전의 미사용 grant까지 거절하며 새 확인으로 복구할 수 있다.
브라우저에서도 session이 바뀌면 확인란을 비우도록 `d1f901307`의 실제 RED(2 failed) 뒤
`1a9efa0baa`로 고쳤다. 첫 `session-ui-red`는 mock state/reason 불일치로 timeout이었으므로
기능 RED로 사용하지 않았다.

독립 증거 검토는 실행 귀속, 브라우저 선택, 계획의 누락 시험과 미완성 기록을 지적했다.
durable runner receipt, 두 렌즈 모델 export, remap 중 교체·만료, 승인/철회 동시 CAS,
SQLite 재시작→실제 source client/worker→render→상태 report→철회 통합 시험을 추가했다.
새 브라우저 시험은 이후 Console 변경에서도 `browser_scope`가 선택한다.

광범위 회귀의 canvas 경로 목록·입력 class·비활성 이유·API 변경 이력 행 누락은
`1a9efa0baa`에서 고쳤다. renderer 성공 경로 시험은 과부하 runner에서 1초 freshness가
만료되어 한 번 실패했다. runtime 기본값은 바꾸지 않고 통합 fixture에 5초를 주었으며,
정확한 lease 만료는 주입한 clock의 독립 경계 시험으로 확인한다.
공개 합성 digest에 대한 스캐너 판정은 예외 범위를 넓혀 처리하지 않았다. 독립 검토자가
`a4b4baf309`의 10개 자리표시자를 확인한 뒤 `b36726018`에 경로·행 SHA-256·정확한 값만
기존 provenance 원장에 등록했다. scanner 코드는 그대로이며 다른 값/행/경로는 해당하지 않는다.
Fleet 단독 전체 invocation은 새 통합 fixture에 games 경로가 없어 실패했다. Vision 시험과
함께 돌릴 때만 이 의존 경로가 들어왔던 문제이므로 fixture가 실제 homography 소유자의
경로를 명시하게 고쳤다. stylesheet의 정확한 목록에도 새 교정 CSS를 추가했다.

## 실행 중 판단과 비용

1. 스크래치/ledger는 저장소 밖에 둔다. 저장소 규칙을 따른 것이며 제품 동작 비용은 없다.
2. 최초 RED는 새 모듈 import를 시험 안에서 한다. 수집 실패와 기능 부재를 구분하는 선택이며
   fixture/import 오류를 놓치면 원격 결과를 재분류해야 한다.
3. 확인 grant는 무효화 후 한 번만 소비한다. 잘못 구현하면 새 운영자 확인이 막힐 수 있어
   replay·재확인 시험으로 제한한다.
4. 기존 plane 응답을 전용 adapter로 옮기고 DTO를 별도 protocol 모듈에 둔다. 원본 hook과
   API를 유지하며 기존 preview/설치 회귀로 경로 변경 위험을 확인한다.
5. remap 중 새 frame은 허용하되 출력 frame의 신선도와 geometry·session·generation·lease를
   다시 검사한다. 잘못 허용하면 낡은 미리보기가 보일 수 있어 무효화/신선도 경계를 유지한다.
6. 크기 규칙 때문에 tracking/calibration 책임을 하위 단위로 분리한다. 잘못 나누면 import나
   wheel/자산 경로가 깨지므로 실제 wheel/sdist와 소비자 회귀로 검증한다.
7. RED 이력은 원래 브랜치에 보존하고 전달 브랜치를 새로 구성한다. 추가 worktree가 비용이며
   같은 전체 tree digest로 결과 일치를 확인한다.
8. 동명 pytest 모듈이 있는 Fleet/Vision은 별도 invocation으로 실행한다. 잘못 묶으면 수집만
   실패하고 검증을 못 하므로 수집 실패를 통과 수에 포함하지 않는다.
9. 촬영 geometry가 원래대로 돌아와도 epoch를 바꿔 새 session 확인을 요구한다. 잘못 구현하면
   운영자의 재확인이 추가로 필요할 수 있으나 변경 전 grant로 묵시 재확인되는 일을 막는다.
10. 성공 경로 통합 fixture의 frame freshness는 5초로 둔다. production 1초 기본값을 검증한
    성능 증거는 아니며, 물리 stream 지연·처리율은 현장 측정 과제로 남는다.
11. 합성 무계보 vector에는 순번 digest를 쓰고 독립 검토된 10개 행만 provenance에 결속한다.
    실제 이미지 hash로 오해하면 증거가 틀리므로 fixture와 본문에 합성임을 명시한다.

별도로 보류한 minor 지적은 없다. 출력 bounds가 renderer의 2..1920 px 범위를 만들지 못하면
영상은 409로 거절되며 저장만으로 적용 성공이 되지 않는다.

## 남은 현장·CI 관문

[입력 점검](evidence-inventory.md) 이후 2026-10-16 같은 제한된 로컬 범위를 재확인했다.
제품 data의 관련 파일 5개에서 완전한 training/validation/source manifest 후보는 0개,
private의 해당 파일은 0개였고 현재 `C:/Dev/Robot/artifacts/device-evidence` 경로는 없었다.
다른 PC와 필터 밖 자료를 조사했다는 뜻은 아니다.

합성 fixture의 `measured` 값은 시험용 운영자 주장이다.
training/validation digest는 순번을 64자리 hex로 적은 명시적 합성 자리표시자다.
실제 원본 hash라고 주장하지 않으며, 실제 workshop exporter 시험은 SHA-256 원본 계보를 사용한다.
실제 AprilGrid 촬영·독립 바닥/마커
측량, ARM64 산출물·설치·장치 readback, 현장 정확도나 주행 수용은 입증하지 않았다.
DEVICE/FIELD gate를 올리지 않는다. 전체 GitHub CI도 아직 실행하지 않았다.

D-598 후속 입력과 World/Fleet 소유·CARRIED/BRIDGED/admission/traffic 소비 기준은
[후속 설계](../../plans/2026-10-16-marker-gap-prerequisites.md)에 기록했다. P0의 현재
D-587·D-593·D-596 readback과 실제 로봇별 오차 계수가 없어 운영 위치·신원 연속성 및
오차 기반 감속 구현은 아직 열지 않았다. 미리보기 SOURCE 통과를 전체 목표 완료로
바꾸지 않는다.

## 사용자가 확정한 이번 완료 범위

2026-10-17 사용자는 실제 촬영·측량·odom 오차 자료가 아직 없음을 확인하고,
그 자료가 필요한 작업을 제외해 마무리하도록 지시했다. 따라서 이번 완료는 D-775의
구현·원격 SOURCE/합성/브라우저 검증, D-598의 현행 소유 경계와 선행 입력·소비 계약 준비다.
구현 계획 Task 1~5와 Task 6의 독립 검토·증거 정리는 이 범위에서 끝났다.

실제 촬영·측량, 장치 설치·현장 검증, 그 P0에 의존하는 D-598 운영 위치/신원 연결·감속
활성화는 별도 후속으로 제외했다. 이를 통과·구현 완료로 표시하지 않는다. 전체 GitHub CI와
main 착지·push는 후속 통합 관문으로 유지하며 이번 작업에서 실행하지 않았다.

## 사용자 승인 후 병합 검증

사용자가 커밋·병합을 요청해 2026-10-17부터 `tools/land.py --tests auto`를 실행했다.
main `c9258138e8`과 통합한 `ea71743778`의 전체 lab tier에서 기존 등록 브라우저 실패
4건과 새 실패 `test_camera_rectification_direct_manipulation` 1건이 확인돼 착지하지 않았다.
새 패널로 화면 길이가 늘어난 설치 화면에서 기존 모서리 손잡이가 고정 상단 바 뒤로
스크롤되는 문제였다. `8c6692128`이 공용 토큰 기반 스크롤 여백을 적용했으며,
같은 드래그와 실측 교정 두 폭의 원격 브라우저 검사는 3 passed, NEW 0이다.
첫 착지 로그는 저장소 밖 `C:/DevTemp/camera-calibration/land/`에,
수정 검증은 `C:/DevTemp/camera-calibration/landing-handle-fix/`에 보관한다.
수정본·최신 main의 최종 착지 결과는 별도 landing receipt로 확인한다. push·배포는 승인받지 않았다.
