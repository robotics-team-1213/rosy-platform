# 공정 컴파일의 앱·Fleet 경계 검증

2026-10-29. D-413·D-849의 공정 소유권과 D-822의 앱 조립 경계 안에서
중복 계산을 정리했다. 공개 API·원장·admission·장치 권한은 바꾸지 않았다.

## 소스와 변경

- 기준: `f05af505153522ceaaa81b6a89146c8078bfaec7`.
- RED: `c8b708861d085f6448817d1dbd93ff17114b9562`.
- 구현: `0e808cd6be82e3d8f4b0b2448a108edf9bbdc1f7`.
  이후 `171d88d7fa88d924194b875ce5087986743e5350`은 설치 시험만 추가했다.
- 브랜치: `refactor/cell-compile-boundary`.

`rosy.processes.palletizing.compilation`이 recipe/cell 로딩, Job 계산,
carry_z 재검사, PlanBundle과 marker·operator checkpoint 조립, 단일 recipe의
item geometry를 소유한다. 앱과 Fleet 어댑터는 같은 계산을 호출한다.
Fleet의 설치 소스 digest와 recipe/3 경로, gateway의 고정 digest와 입력 검증,
기존 compile_submission 진입점은 유지한다.

공정 소스 변경에 따라 기록 샘플의 artifact digest를
`c4aa396a8daf1e3ecde68891f2f2dea26cf64274f88d1a1b4de4f2956725be58`로 갱신했다.
Job 형식·resource claim·승인·하달 계약은 바꾸지 않았다.

## RED와 원격 실행

동일한 recipe/cell/digest/tolerance를 양쪽에 넣는 두 parameter case 중,
일반 간지 case는 통과하고 수동 간지 case는 gateway의
`operator_checkpoints == ()`와 Fleet의 두 checkpoint 차이로 실패했다.
유효한 수동 작업 경계를 양쪽에서 같은 내용으로 보존하는 회귀다.

```text
python tools/remote/remote_pytest.py --log-dir <RED 로그> -- test/test_platform_cell_compiler.py -k test_gateway_and_fleet_preserve_the_same_complete_compilation -q
python tools/harness/rosy_harness.py affected --base f05af505153522ceaaa81b6a89146c8078bfaec7 --json | python tools/remote/remote_pytest.py --affected-json - --log-dir <GREEN 로그>
python tools/remote/remote_pytest.py --log-dir <설치 로그> -- test/test_process_submission_installed.py -q
python test/known_failures.py <각 GREEN/설치 로그>
```

RED는 model-role 시험 PC에서 확인했다. 그 전에 AI PC에 제출했던 동일 RED는
admission 대기가 이어져, model 결과 확보 뒤 native job 취소 절차로 중단했다(exit 143).
취소된 실행은 성공·실패 근거에 포함하지 않는다.

구현의 세 affected 묶음은 native runner가 model/AI 시험 PC에 배치했다.
추가 설치 시험은 다른 호스트의 예약 예산 때문에 마지막 후보인 site-role 시험 PC의
light 환경에 배치됐다. 그 시험은 임시 wheel/sdist 설치와 격리 Python subprocess만
사용했고 운영 서비스·실물 장치에 연결하지 않았다.

| 실행 | 결과 |
|---|---|
| affected run-1: 공정·CORE·역의존·설치·경계 | 4,924 passed, 224 skipped, 5 subtests passed |
| affected run-2: Gazebo 패키지의 pytest | 328 passed, 4 skipped |
| affected run-3: Fleet와 현장 소비자 | 7,346 passed, 413 skipped |
| `171d88d7fa` 설치 후속: wheel·sdist | 2 parameter case 통과, exit 0, skip 없음 |

전체 affected 선택은 12,598 passed/641 skipped다. 선택을 축소하지 않았다.
네 GREEN/설치 로그 각각의 known_failures 비교는 0 NEW, 0 known, 0 flaky다.
기존 theme-browser 항목 하나가 listed-but-not-failing으로 출력되어 목록을 바꾸지 않았다.
설치 로그는 quiet 출력의 두 성공 case와 exit 0으로 확인했다.

설치 probe는 wheel과 sdist 각각을 checkout 밖에 설치하고 import 순서 두 가지로
실행한다. 수동 간지 station 없이 checkpoint 2개, 저장 문서의 전체 checkpoint,
16 motion step을 확인하며 기존 변조 Job 거절 검사도 유지한다.

## 로그 무결성과 리뷰

원본 로그는 개발 PC의 저장소 밖 시스템 임시 폴더에 보존한다.

| 로그 | SHA-256 |
|---|---|
| `rosy-cell-compile-red-model-20261029/run-1.txt` | `76a030fe4f8d1dcef78c14e5243a8dc91f10cf20a5009c6434742225a64d671b` |
| `rosy-cell-compile-green-20261029/run-1.txt` | `be04218d28ec3afd4873ecf4c74a38532b44b392a9fe357c74c9ccbcdd318396` |
| `rosy-cell-compile-green-20261029/run-2.txt` | `e68fa8ccb0d9e588df4169249cf39139514e69f4f3c872200653c56d8f96bd57` |
| `rosy-cell-compile-green-20261029/run-3.txt` | `9c3e7cd6dba388721c690890418c4d921dc980e5c21a66a66ea578241325ce92` |
| `rosy-cell-compile-installed-20261029/run-1.txt` | `a2a9917ee0b567ebf82fc67c8a5fad3d3972c8c36bc7e3bb6c3bb19b7c28283b` |

코드와 설치 시험 후속을 별도 읽기 전용 reviewer가 검토해 지적 사항이 없었다.
현재 manifest에서 해당 root는 other/decision이고, 변경 파일은 safety_modules와
safety_anchors에 없으므로 이 변경의 Safety-Review trailer 의무는 없다고 확인했다.
이 기록은 장치 안전 수용 attestation이 아니다.

## 한계와 작업 공간

일부 원격 poll이 일시 실패했지만 재연결 뒤 전체 로그와 exit 0을 회수했다.
skip 641개는 실행한 것으로 세지 않는다. 브라우저 opt-in·ROS 환경 등 별도 조건이
필요한 검증과 실제 Gazebo bench·ARM64 payload·장치·현장 수용은 이 결과로 승격하지 않는다.
native runner의 공유 `/tmp` 경고는 다른 세션의 파일을 포함할 수 있어 임의 삭제하지 않았다.

이번 작업만 한시 슬롯 예외를 사용했다. 검증 후 미머지 브랜치·HEAD·로그와
복구 bundle을 보존하고 해당 clean 작업 공간만 반환한다. 다른 세션의 작업과
미커밋 파일, 공용 시험 환경은 정리하지 않는다. main 착지·push는 별도다.

CE: 해당 없음 — 누락 checkpoint와 공유 계산의 판단은 코드·RED/GREEN 회귀·설치 시험에
드러난다. 새 실물 성질이나 별도 운영 복구 순서를 검증한 작업은 아니다.
