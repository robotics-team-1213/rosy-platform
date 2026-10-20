# Pinky 성공 주행 구현의 보존·통합·검증

2026-10-19 KST. 사용자 요청: 다른 워크트리에서 성공한 구현을 기준으로 삼고, 현재 통합본과 차이를 확인한 뒤 같은 조건으로 반복 검증한다.

## 현재 상태

코너 후속 작업: [정체 수정과 반복 검증](../pinky-corner-completion-2026-10-19/result.md). 관측 정렬·반대 pivot·상태 수명·곡선 거리 판정을 수정했고 최종 원격 영향 회귀 6,832건을 통과했다. 같은 최종 소스 SIM은 1 PASS/1 FAIL이며, 실패는 정렬 후 관측 목표와 현 차로의 불일치로 realign HOLD/LOST가 발생했다. 기존 trip 계약에는 자동 REALIGN 수용 경로가 없어 반복 수용은 계속 HOLD다. 아래 수치는 이전 통합 단계의 기록이다.

- 원본 성공 소스의 새 초기화 재실행: **PASS**.
- 현재 main 기준으로 필요한 성공 구현 이식: **4개 단계 커밋 완료**.
- 최종 후보 독립 소스 검토: **중대한 발견 없음**.
- 통합 후보 반복 SIM: **1회 PASS / 1회 FAIL**. 전방 정지 덮어쓰기 수정 후에도 다른 코너에서 **FAIL**했다. **반복 주행 수용은 HOLD**다.
- 수정 후보 `bafb32dc10`: 관련 원격 회귀 **132 passed, NEW 0**. FULL 모듈 22호출은 **28,257 passed / 문서 1 failed(NEW) / 1,942 skipped**였다.
- 최종 문서 head `4d92cc1a8`: 문서·배포 경계 원격 회귀 **93 passed, NEW 0**. runtime은 `bafb32dc10`과 같다.
- 같은 최종 head의 수정 범위 브라우저 4호출: **45 passed, NEW 0**, skip 0.
- main 착지·push·실물 설치/운동: 수행하지 않았다.

## 성공 기준과 원본 재실행

원본 source commit `91f14c997fcd1c509b2ee6bb9f72b2fdc8548090`, model revision
`lane-seg-20261010-451f0f85`, ONNX SHA256
commit `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`를 기준으로 삼았다.
기존 소스 archive와 모델 보존본을 다시 hash했다.

원래 성공한 모델 PC에서 같은 인자(GPU render, drivable, lap, stall 60s, record,
lane_return 검사 생략)로 실행했다. run ID `sim-91f14c997f-4b1237`, runner exit 0이다.

| 항목 | 이번 원본 재실행 |
|---|---|
| 최종 시험 판정 | PASS |
| Fleet 상태 | started → running → arrived |
| 정착 후 목표 거리 / 기존 기준 | 0.105 / 0.15m |
| 반대편 경유점 최근접 거리 | 0.031m |
| 첫 비영 명령부터 마지막 비영 명령까지 | 약 269.209초 |
| 위 구간 keep_debug 표본 | learned_drivable 1,539건 / fallback 0건 |
| 마지막 cmd_vel 선·각속도 | 0 / 0 |
| 마지막 odom 선·각속도 | 0 / 0 |
| lease / 종료 잔존 프로세스 | released / 없음 |

이는 이번에 새로 실행한 원본 기준이다. 기존 r51b FAIL과 후속 별도 워크트리의 stall
FAIL은 지우지 않는다. 표본 인식 수를 모든 물리 tick의 측정값으로 확대하지 않는다.

원시 증거: `C:/DevTemp/pinky-success-baseline-20261019/r51a-repeat-1/`.
result.json SHA256 `5db72b8af1a4dc017ef7bc67beabf6d906ac2553f3d3e7c03a17db66f614c708`.

## 현재 main에 없던 것과 이식 범위

조사 base commit `a27b980c7cb780b042ba6a85b5e541d9e533d823`에는 성공 구현이
포함되지 않았다. 단순히 한 실패 실행을 다시 고치는 대신 아래 기존 구현을 재사용했다.

1. 선택 지도 벽 필드와 source 기반 안내 수명 계약.
2. CORE/Drive의 안내 소비·거절한 짧은 연장의 안내 갱신·횡단보도 re-anchor/벽 처리.
3. 인식의 조기 선회 억제와 차로 중앙 복귀.
4. Fleet의 선택 경로·지도 벽 생산과 격리 SIM 지도/설정.

운영 Fleet 안내 기본 1초와 wall band null을 유지한다. 명시적 SIM만 안내 3초,
band 0.01m를 사용한다. 자원 예약을 절반만 세는 변경, run_scenarios 도구와 그
도구에만 필요한 시험은 가져오지 않았다. 모델 가중치를 바꾸거나 새 제어 알고리즘을
추가하지 않았다.

## 분리한 커밋과 작업 위치

새 워크트리를 늘리지 않고 기존의 깨끗한 주행 검증 워크트리
`D:/Dev/Robot/Rosy/rosy-platform/.worktrees/pinky-rl-binding/`를 재사용했다.
기존 `fix/pinky-drivable-v2-verification` 브랜치와 원본 성공 브랜치는 보존했다.

| 순서 | 브랜치 | 커밋 | 내용 |
|---|---|---|---|
| 1 | fix/pinky-route-guide-prerequisite | 3e56f3668c | 공통 schema/config, API v1.287과 버전 핀·호환성 문서 |
| 2 | fix/pinky-drivable-consumers | a473c8f0e | CORE/Drive 소비 구현과 회귀 |
| 3 | fix/pinky-drivable-recentre | d93591ba0 | 기존 인식 중앙 복귀와 회귀 |
| 4 | fix/pinky-v2-fleet-integration | d9b706e204 | Fleet 생산·SIM 설정과 원본 성공 증거 |

첫 source candidate commit `d9b706e204a08f87d078fc67e1149f9b893a8854`.
FULL 회귀에서 API 변경 이력 표 행의 누락을 찾아 선행 브랜치의 commit `681c31d67`에서
보완하고 후속 브랜치에 병합했다. 이 시점의 candidate commit은
commit `13f44844af68b94621c0897b28d9259f20d4dab1`이다. 첫 후보와의 차이는 API 변경 이력
행·기록·생성 index 세 파일이며 runtime·테스트는 동일하다.
그 뒤 commit `ca49303cd0a51e2f640fb30c7b574c459b19af95`에서 당시 main
commit `4b2cb988cc649681cae2ebd4d8451cc670b6edf8`를 병합했다. 이 병합에는 별도 OMX 학습·
카메라 수집/UI 변경이 포함되며 앞의 첫 두 SIM과 같은 전체 소스라고 표기하지 않는다.
최종 수정 브랜치는 `fix/pinky-crosswalk-front-stop`, 소스 후보는
commit `bafb32dc1085b7112427f5209642330154570676`다. 원본 네 단계 브랜치도 보존한다.
최종 보존 head `4d92cc1a8146f9074f73bf36464168dae442c571`에는 이후 검증 문서·
기록·생성 index 변경만 있다. 원격 FULL은 runtime 후보 `bafb32dc10`을 지정하며,
이 문서 delta는 최종 head의 별도 원격 guard로 검증했다.
네 단계는 같은 계열의 선행 커밋을 포함하는 stacked branch다. foundation은 제품보다
먼저 착지해야 한다. 첫 커밋의 16파일은 공통 계약과 API 버전 핀·필수 기록을 함께 맞추기
위한 단위이며, 나머지는 12/5/11파일로 나눴다.

## 계약 검토에서 해결한 사항

독립 검토자 `/root/drive_success_review`가 각 단계와 최종 base/head를 읽기 전용으로
검토했다. 발견한 API 문서의 1초/3초 차이와 수락 후 binding 예외를 보완하고, D-769에
누락된 개정 근거를 덧붙였다. 이식하면서 제외한 scenario 도구에 의존하던 시험도 제외했다.

schema만 올려도 기존 활성 Fleet의 `model_dump()`가 새 wall 필드를 null로 전송한다.
구형 CORE는 nested validation에서 authority 요청 전체를 거절할 수 있다. 따라서
**CORE와 camera receiver를 먼저 업데이트한 뒤 Fleet schema/생산자를 업데이트한다.**
이 배포 순서를 API에 명시했다. 이번 작업에서 실제 배포는 하지 않았다.

이식 완료 시점 `13f44844…`의 검토에서는 핵심 runtime·설정·지도·회귀 20개 파일이 기존 검토 구현과 같음을 확인했고
남은 중대한 소스 발견은 없었다. CORE 최종 명령과 Fleet admission/원장, OMX owner를
유지한다. 소스 검토를 실물 안전 수용이나 실행 통과로 계산하지 않는다.

## 검증 기록

| 대상 | 결과 | 로그 |
|---|---|---|
| 원본 검증 브랜치 19ac6490, 관련 6파일 | 159 passed, NEW 0 | C:/DevTemp/pinky-success-baseline-20261019/v2-regression/run-1.txt |
| 선행 후보 3e56f3668c, 계약·문서·API 핀 | 1,209 passed, NEW 0 | C:/DevTemp/pinky-success-baseline-20261019/prerequisite/run-1.txt |
| 최종 후보까지 size_range | exit 0, 31 commits checked | native command output |
| 수정 후보 harness lint | 0 errors, 기존 상태 노후화 등 33 warnings | native command output |
| 첫 후보 d9b706e204 FULL 26호출 | 28,229 passed, 2 failed(NEW), 1,940 skipped; 두 문서 실패를 보완 | C:/DevTemp/pinky-success-baseline-20261019/full/ |
| 보완된 선행 후보 681c31d67 버전 정합성 | 3 passed | C:/DevTemp/pinky-success-baseline-20261019/prerequisite-changelog/run-1.txt |
| 첫 후보 d9b706e204 동일 모델 PC SIM | PASS, runner exit 0 | C:/DevTemp/pinky-success-baseline-20261019/integrated-repeat-1/ |
| 통합 후보 13f44844af 두 번째 동일 모델 PC SIM | FAIL, stall, runner exit 1 | C:/DevTemp/pinky-success-baseline-20261019/integrated-repeat-2/ |
| front-stop 회귀 b601f27cc | 예상한 RED: 직진 유지가 pivot을 덮어씀 | C:/DevTemp/pinky-success-baseline-20261019/crosswalk-red/run-1.txt |
| 수정 후보 bafb32dc10 인식·CORE 횡단보도 회귀 | 132 passed, NEW 0 | C:/DevTemp/pinky-success-baseline-20261019/crosswalk-green/run-1.txt |
| 수정 후보 bafb32dc10 FULL 모듈 22호출 | 28,257 passed, 1 failed(NEW, 아래 문서 수정), 1,942 skipped | C:/DevTemp/pinky-success-baseline-20261019/full-final/run-1.txt … run-22.txt |
| 넓게 선택한 추가 브라우저 2호출 | 243 + 345 passed; 후속 1호출 취소, 마지막 미실행 | C:/DevTemp/pinky-success-baseline-20261019/full-final/run-23.txt … run-25.txt |
| 최종 head 4d92cc1a8 수정 범위 브라우저 4호출 | 14 / 14 / 13 / 4 passed, NEW 0, skip 0; exit codes 모두 0 | C:/DevTemp/pinky-success-baseline-20261019/full-scoped-browser/ |
| 수정 후보 bafb32dc10 동일 모델 PC SIM | FAIL, ring_n stall, runner exit 1 | C:/DevTemp/pinky-success-baseline-20261019/front-stop-repeat-1/ |
| 최종 문서 head 4d92cc1a8 release·문서·배치·버전 guard | 93 passed, NEW 0 | C:/DevTemp/pinky-success-baseline-20261019/final-doc-guards-v2/run-1.txt |

FULL은 공통 foundation 변경으로 선택됐으며 mapped affected 검사로 대체하지 않았다.
기존 `land.select()`의 전체 모듈 선택을 `remote_pytest.run()`으로 AI PC에서 실행했고,
실제 착지 함수는 호출하지 않았다. 모델 PC는 원본과 같은 조건의 SIM을 맡았다.
현재 main의 기존 `aff1.log` 등 타 작업 파일은 건드리지 않았다.

최종 후보의 첫 선택은 병합 전 base `a27b980c…`를 사용해 상속한 main의 학습·카메라 UI까지
브라우저 범위를 넓혔다. 이를 당시 병합 main `4b2cb988…` 기준으로 정정했다. 새 선택도
FULL 26호출이며, 모듈 22호출 중 21개는 기존 호출과 같고 나머지 호출의 모든 경로도 기존
호출의 시험 경로에 포함됨을 명령 인자 비교로 확인했다. 모듈 검사를 다시 돌리지 않고
최종 head의 수정 범위 브라우저 4호출을 별도로 실행했다.

잘못 넓힌 범위에서 완료한 추가 브라우저 588 passed는 이 네 호출의 통과로 대체하지
않는다. 진행 중이던 세 번째 추가 호출은 자체 native job의 process group에 TERM을 보내
exit 143·alive false를 확인한 뒤 해당 job만 정리했다. 부분 로그는 성공으로 세지 않으며
마지막 추가 호출은 실행하지 않았다. GitHub CI와 실물 수용은 이번 검증에 포함하지 않는다.

최종 증거는 runtime 후보 `bafb32dc10`의 모듈 22호출, 문서만 바뀐 head `4d92cc1a8`의
브라우저 4호출과 문서 guard로 나뉜다. 두 source 사이의 변경은 검증 문서·기록·생성 index
세 파일이다. 모듈 호출의 92 subtests passed는 일반 passed 합계와 별도로 보존한다.
모든 완료 로그를 known-failures와 비교했고 모듈의 문서 실패 1건은 NEW였다. 그 실패는
최종 head의 release guard를 포함한 93 passed로 재검증했다. 취소 호출과 수집 0건 호출은
통과 합계에 넣지 않았다.

첫 FULL의 release guard는 재현 명령의 공개 source SHA를 high-entropy token으로
분류해 NEW로 실패했다. 명령은 상단의 고정 source를 참조하게 바꾸고 각 결과 digest도
SHA256로 명시했다. 검사 예외는 추가하지 않았다. 마지막 문서 guard는 93 passed였다.
그 전 잘못 지정한 존재하지 않는 시험 경로로 수집 0건인 호출과, 문서 guard 92 passed/
1 failed 후 콘솔 인코딩 오류가 난 호출도 로그에 보존하며 성공으로 세지 않는다.
첫 FULL의 모든 로그를 `test/known_failures.py`로 비교했다. 두 실패는 기존 실패가 아닌
NEW였으며 변경 이력 행과 공개 SHA 명령 표기였다. 92 subtests passed는 위 passed와
별도다. 명시적 브라우저 4호출은 각각 14/14/13/4 passed로 skip이 아니었다. 위 총수는
호출별 합계이며 여러 호출에서 중복한 시험을 제거한 고유 개수는 아니다.

### 첫 통합 주행 결과

run ID `sim-d9b706e204-2b8d7b`, 동일 모델 PC·모델 pointer·인자에서 PASS했다.
목표 거리 0.113m, 경유점 최근접 0.049m, 비영 명령 시간 구간 약 279.180초였다.
그 구간 keep_debug는 learned_drivable 1,575건/fallback 0건이고 model revision도
기준과 같았다. 마지막 cmd_vel·odom 선/각속도는 모두 0, lease released,
잔존 소유 프로세스는 없었다. 실행 중 원격 ONNX도 기준 SHA256과 같음을 확인했다.

| 첫 통합 실행 파일 | 무결성 |
|---|---|
| run.txt | SHA256 `b1a71bd6c8acf1fe13dc3d59014ff2301a32e6a5bbc82e4ececd882cab321d39` |
| out/trips/result.json | SHA256 `dea67341436f3c0301ab89e742946097c8f57f912b8facd344909e9efe9d4f62` |
| out/trips/observations.jsonl | SHA256 `bb09de62c07758db408fdeaa87a0d2c951514948add0282bf1e975160e281e40` |
| out/trips/launch.log | SHA256 `8eb70ffc2844f2f97ffd3f11fad598358986b351a520fbe69d8fe2448a6a922e` |

### 두 번째 통합 실행의 실패와 수정

run ID `sim-13f44844af-9223d8`는 west 구간에서 stall로 실패했다. 첫 성공과 runtime은
같으며 이 실패를 반복 수용의 분모에서 제외하지 않는다. 정지 위치는 약 (-1.305, 0.154),
누적 경로 진행은 4.698m, 경유점 최근접은 0.033m였다. 1.954m는 시작점에서 정지점까지
직선 거리이며 실제 주행 거리로 쓰지 않는다.

인식 로그에서 LiDAR 전방 0.114m가 기존 front-stop 임계값 0.149m보다 가까웠지만,
뒤의 crosswalk-straight 분기가 기존 pivot 선택을 지우고 있었다. 회귀 시험으로 이
우선순위 오류를 먼저 재현했고, commit `bafb32dc1085b7112427f5209642330154570676`에서
전방 막힘이 없는 경우에만 직진 유지를 적용하도록 조건 한 줄을 바꿨다. 모델·임계값·
CORE 권한은 바꾸지 않았다. 전방이 열리면 기존 직진 유지로 복귀하는 회귀와 CORE의
관찰·사람·관측 불명 대기에서 양 축 정지하는 회귀도 포함한다.

독립 검토자는 이 수정과 강화된 회귀에서 중대한 소스 발견이 없다고 확인했다.
원격 관련 회귀 132개는 통과했으나, 이것만으로 SIM stall 전체가 해결됐다고 판단하지
않는다. 당시 CORE가 실제 CROSSING 상태였다는 증거도 확보하지 않았다.

| 두 번째 통합 실행 파일 | SHA256 |
|---|---|
| run.txt | commit `26ebff6ae1ad40495d97f5946f2a52633e88f1ad61478c1c0e8941f9599c4c71` |
| out/trips/result.json | commit `d6a9630623793ffbee13ba233872c197cae92b069f86c4f6ef6d86912bb35fcf` |
| out/trips/observations.jsonl | commit `82fbd6188b24cafc404156c8d109e16d59b4cfd3507c90d0578b57a156d6a569` |
| out/trips/launch.log | commit `58231dc53e2399c76373dc9b5d68ac7b67ae4d80b889d0d2d9b1c4c7a4314802` |

### 수정본의 코너 정체와 다음 작업

`sim-bafb32dc10-0cfcfb`도 FAIL했다. 위치 (-0.486, 0.171), yaw -3.057rad에서
LOCALIZED를 유지했고 ring_n 진행 3.420m에서 stall했다. 경유점 최근접은 0.825m로
미도착이다. 마지막 cmd_vel·odom 선/각속도는 모두 0이고 lease는 released였다.
`moved_m=1.225`는 시작점과 끝점의 직선 거리이며 누적 주행 거리가 아니다.

정체 프레임은 `target_m=(0.111, 0.104)`, `ahead_m=0`, `near_centre_m=(0.159, 0.101)`,
안내 방향 -68.8°, `recentre_first=true`, `reason=drivable_closed`였다. 선택한 출구의
반대편에 있는 관측 중심 때문에 선회를 취소한 뒤, 실제 pursuit 목표의 전방 길이가
기존 0.18m 조건에 못 미쳐 진행을 거절한 경로다. 앞서 수정한 횡단보도 덮어쓰기와는
다른 지점이며, 이번 결과로 그 수정의 종단 효과를 검증할 수 없다.

독립 검토에서 가까운 행 중심 중앙값을 주행 목표로 바꾸거나 recentre 보호를 건너뛰는
수정을 뒷받침할 관측이 부족하다고 판단했다. 따라서 임계값을 낮추지 않고 후보를 보류했다.
다음 작업은 이 실행의 같은 시각 카메라·drivable mask·보인 경계·centre path·odom으로
변환한 기억 출구를 겹쳐 비교하고, 실제로 열린 경로가 있었는지 판정하는 것이다.
정지 영상은 [보존 프레임](C:/DevTemp/pinky-success-baseline-20261019/front-stop-repeat-1/out/trips/frames/rosy_01/001170.png)에 있다.
프레임 시각의 정밀 결속과 mask 재추론은 이번 기록에서 수행하지 않았다.

| 수정본 실행 파일 | SHA256 |
|---|---|
| run.txt | commit `ac469df98c41fa79a9bbb44a699c4a70b609b53fef813d34f45671216c3eba4c` |
| out/trips/result.json | commit `b96670601bc439ee0f4dffe0d4ad0912bd72a96c3c12676fa0c5497ab4bd10df` |
| out/trips/observations.jsonl | commit `56bac4a99a67a7ffd42580532fb31a22faf75f10a0864c3eecac1c6a7fd367df` |
| out/trips/launch.log | commit `d8fc5be5b6a29381f3b9d741b219823ede629651010dc830d5d3d1acbd08e1ec` |

## 아직 별도인 것

lane_return을 켠 전체 기능 수용, 다른 시작 조건의 반복·다중 로봇·실물 지도 위치 오차,
실물 보정/정지와 장치 과제 수용은 이 SIM 성공만으로 완료되지 않는다. 이 보고서는
주행 성공 구현의 보존·현재 main 기반 이식·검증에 한정하며 나머지 암/Decision/배포 축
전체가 완료됐다고 선언하지 않는다.

현재 차단 조건은 **ring_n 코너의 관측 경계·추종 목표·기억 출구·경로 안내 정합성**이다.
후보는 커밋과 잠근 워크트리로 보존했으며 반복 주행 수용은 HOLD다. 최종 작업 트리는
clean이고 main 착지·push·실물 배포는 수행하지 않았다.
