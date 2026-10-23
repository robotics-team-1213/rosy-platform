# 공정 소유 제출 검증 분리 — 구현·검증 기록

상태: 이번 책임 분리의 코드·대상 회귀·설치·최종 FULL 원격 검증 완료. main 반영·배포·장치 수용 기록이 아니다.

## 최종 목표와 이번 완료 단위

최종 목표는 새 공정을 추가할 때 공통 실행부를 수정하지 않아도 되고, 모델의 제안부터 승인·실행·독립 완료 근거까지 추적할 수 있는 ROSY 플랫폼이다. 공정별 입력·기하·절차 검증은 공정이 소유하고 Fleet·CORE·장치 owner의 실행 권한은 유지한다.

이번 단계는 그중 기존 팔레타이징 제출 검증을 올바른 소유로 옮기는 변경이다. 임의 공정 API·새 Skill·모델·실물 실행을 추가하지 않았다. 두 번째 실제 공정과 모델-장치 폐루프까지 완성했다고 주장하지 않는다.

## 변경

- `rosy.execution.site.cell_submission`의 기존 타입·검증·직렬화를 `rosy.processes.palletizing.submission`으로 이동했다. 옛 모듈은 제거했고 사본·역방향 import를 남기지 않았다.
- `plan_bundle`의 checkpoint identity 계산도 같은 공정의 제출 모듈을 사용한다.
- Fleet/gateway의 설치된 compiler가 `compile_submission(candidate, *, workcell_id, instance_id)`로 기존 저장 문서를 반환한다. Fleet resolver는 이 신뢰된 내부 조립 경계를 소비하고 메서드가 없으면 구성 시 거절한다.
- 직접 Python 소비자·시험 fixture를 같은 타입 정본으로 갱신했다. 외부 wire·Job ID·자원/marker/checkpoint·승인·정지·최종 writer는 유지한다.
- 이동 전후 AST 비교에서 모듈 docstring을 제외한 모든 정의·검증 로직이 동일하다. 공통 execution 소스에서 pallet/slip_sheet/layer_index/CELL_TRANSFER 참조는 발견되지 않았다.

결정: [D-849](../../adr/D-849-process-owned-palletizing-submission.md). 기존 D-427·D-429·D-430·D-657·D-827·D-836과의 관계를 해당 ADR에 기록했다.

## 소스와 시험 증거

기준 commit: `24856e823e2f`.
브랜치: `refactor/process-submission-ownership`.
원격 host 역할: 모델/AI 시험 PC. 모든 제품 pytest는 저장소 원격 runner로 실행했으며 노트북 pytest는 실행하지 않았다.
로그 원본은 저장소 밖 시스템 임시 폴더의 `rosy-process-submit/`에 생성했다. 보존본은 ROSY 작업 공간의 `docs/workspace-records/2026-10-23/process-submission/evidence/`에 복사하고 모든 파일의 SHA-256이 원본과 같은지 확인했다. 아래 run 경로는 각 보관 폴더 기준이다.

| 단계 | 시험 commit | 결과 | 로그 |
|---|---|---|---|
| 새 소비 경계 RED | `24002a33cb` | 새 3개 실패, 기존 13개 통과. 미구현 메서드·구성 시 거절 부재를 확인 | `red/run-1.txt` |
| 대상 회귀 GREEN | `48b843e0ab` | 347 passed, skip 없음, 의존 패키지 deprecation warning 2. known_failures: NEW/known/flaky 모두 0 | `green/run-1.txt` |
| 설치 Fleet 증거 RED | `46e730cf51` | wheel/sdist 2개 실패. 제출 모듈이 격리된 설치 경로가 아닌 전역 venv에서 로드되는 것을 검출 | `install-red/run-1.txt` |
| 설치 Fleet/Gateway GREEN | `97d225c050` | 22 passed, skip 없음. known_failures: NEW/known/flaky 모두 0 | `install-green/run-1.txt` |
| 첫 FULL | `30fcd49db4` | 총 11116 passed/513 skipped/2 failed. 아래 두 회귀를 확인 | `full/run-*.txt` |
| 샘플 fixture 보완 | `cf62de71af` | 65 passed/32 browser opt-in skipped. known_failures: NEW/known/flaky 모두 0 | `sample-green/run-1.txt` |
| 최종 FULL — 공통·통합 | `a5ab652723` | 4943 passed/219 skipped/39 warnings, 5 subtests passed. NEW/known/flaky 모두 0 | `full-final/run-1.txt` |
| 최종 FULL — Fleet | `a5ab652723` | 6227 passed/326 skipped/2 warnings. NEW/known/flaky 모두 0 | `full-final/run-2.txt` |

`30fcd49db4` 이후 `97d225c050`까지 제품 Python 코드는 바뀌지 않았고 설치 시험만 보강했다. 첫 FULL에서 확인한 샘플 digest와 크기 단위를 보완한 뒤 `a5ab652723`에서 전체 선택을 다시 실행해 통과했다. FULL은 폴더 이동으로 자동 선택된 범위를 줄이지 않았다. 합계 11170 passed/545 skipped이며 skip을 실행 통과로 집계하지 않았다. 이후 변경은 이 증거와 모듈 기록·생성 색인을 남기는 문서 변경뿐이다.

첫 FULL의 두 실패는 다음과 같다. 기존 실패 목록에 추가하지 않았다.

- `operations/fleet/test/test_app_sample_cell_contract.py::test_sample_cell_preview_matches_the_existing_compiler`: 공정 소스 이동으로 digest가 바뀌었는데 앱 샘플 fixture에 이전 값이 남았다. 독립적으로 source hash를 계산해 fixture의 process digest 한 값만 갱신했다. 기존 정확 비교·public provenance 검사는 유지했다.
- `test/architecture/test_module_structure.py::test_size_units_are_real_and_meet_the_floor`: 공정 검증 제거 후 `site_execution`은 814줄로 별도 단위의 1000줄 기준을 밑돌았다. 별도 size unit 등록을 제거해 같은 소스를 기존 Fleet 부모에 합산했다. 부모는 9223줄로 10000줄 이내이며 상한·측정 대상·small 예외는 바꾸지 않았다.

대상 회귀는 실제 Fleet/gateway compiler, Cell API·승인·단일/다중 팔·manual sheet, 기존 palletizing/Cell 공정, 변조 후보 거절을 포함한다. 설치 시험은 wheel과 sdist를 checkout 밖에 설치하고 두 import 순서, 공통 execution의 공정 없는 import, 설치된 Fleet resolver/compiler 및 gateway의 정상·변조 제출을 확인한다.

대표 재현 명령은 아래와 같다. `<scratch>`는 저장소 밖 로그 경로다. FULL 선택은 기준부터 검증할 소스까지의 변경으로 계산한다.

```text
python tools/remote/remote_pytest.py --sha 24002a33cb --log-dir <scratch>/red -- operations/fleet/test/test_cell_compiler.py
python tools/remote/remote_pytest.py --sha 97d225c050 --log-dir <scratch>/install-green -- test/test_remaining_platform_installed.py test/test_process_submission_installed.py operations/fleet/test/test_cell_compiler.py
python tools/harness/rosy_harness.py affected --base 24856e823e2f --json | python tools/remote/remote_pytest.py --sha a5ab652723 --affected-json - --log-dir <scratch>/full-final
python test/known_failures.py <scratch>/full-final/run-1.txt
python test/known_failures.py <scratch>/full-final/run-2.txt
```

원본 로그의 SHA-256은 다음과 같다.

| 로그 | SHA-256 |
|---|---|
| `red/run-1.txt` | a2de29c9f8b3c39d6ffea7ae0a7fb112e5e22ba3dfc599bbe194dae4eb21743f |
| `green/run-1.txt` | 6578bfac6da46ffe93f5fb62d6c5e8e686a97126134bd76f76a2c8b45304eb71 |
| `install-red/run-1.txt` | 8d755514d64b04e6c3cdac23be65ed90461088e94018b36f337c469a59446b71 |
| `install-green/run-1.txt` | f59858ee2e63a48d2d5f104aee63df977375ef6f80faf0391ddc044f059df295 |
| `full/run-1.txt` | 42e3c8f81c85ac435797e9015b416d22655b01a0db24cde81521e84f6f0bce5a |
| `full/run-2.txt` | 03f1799d7b51a5431ec9f506d923e2418754fc4b1afea7afff855fd00fc6ef15 |
| `sample-green/run-1.txt` | feb59cfcc2418e8041e4665b3aa04b930c0ca151f518943e37a0d52deb018d81 |
| `full-final/run-1.txt` | b4f9e39a7424119339a81e3ba388e6ff037786ef9a5c4f89d676f363f0e3033c |
| `full-final/run-2.txt` | 1e60cfbcbf4b0aefde7b616fe98fe8353e2247a1ad50d8f1c9f9a540f67f29a3 |

## 독립 리뷰와 보완

별도 읽기 전용 reviewer가 기준부터 `30fcd49db4`까지와 연결된 승인·저장·설치 경로를 검토했다. 코드 회귀는 발견하지 못했고, 설치된 실제 Fleet Cell adapter의 실행 증거가 빠졌다는 P2 검증 공백을 지적했다.

기존 Fleet delivery 시험을 확장해 이 공백을 RED로 확인한 뒤 시험 설치에 기존 palletizing/gateway 패키지를 포함해 GREEN으로 만들었다. 전역 venv의 같은 패키지가 누락된 시험 설치를 가리지 못하도록 제출 모듈의 실제 경로가 격리된 설치 아래인지 검사한다. runtime dependency나 검증 조건을 약하게 하지 않았다.

리뷰에서 확인한 `process_artifact_digest`는 기존 Mission resolve/admit 재검사에 남아 있다. 소스 이동으로 digest가 달라진 예전 제안을 새 revision에 맞는 것으로 자동 승인하지 않는다.

## 범위 판단

- 기존 gateway의 recipe/2 checkpoint 지원 부족은 이번 변경 이전에도 거절되던 기능이다. 이번 소유권 이동에서 새 지원을 추가하지 않았다.
- 주입된 compiler는 신뢰된 설치 코드다. 외부 HTTP 입력이 이를 교체할 수 없으며, 내부 custom compiler는 완전한 검증 계약을 구현해야 한다.
- 필수 소비자와 타입 이동은 함께 변경했다. 별도 범용 registry·새 서비스·추가 dependency를 도입하지 않았다.
- 신규 ADR D-849 앞의 D-846~848은 동료 세션이 예약했고 이 브랜치에는 문서가 없어 기존 gap 형식으로 명시했다. 해당 ADR이 들어오면 제거할 항목이며 runtime 허용 목록 변경이 아니다.
- `site_execution`의 부모 합산은 크기 측정만의 변경이다. 공통 execution의 코드·계약 소유권을 Fleet으로 옮기는 변경이 아니다.

## 확인 한계와 다음 수용 조건

실제 모델 추론, ROS/Gazebo 동작, 물리 정지·작업 성공, ARM64 artifact·이미지·배포·현장 수용은 실행하지 않았다. host 설치 시험으로 이를 대체하지 않는다. main 착지·push도 하지 않았다.

최종 source commit의 크기 검사와 `git diff --check`는 통과했다. harness lint는 오류 0개이며 기존 모듈 상태·검증 시점 관련 warning 33개는 그대로 보고했다. FULL의 browser opt-in·ROS 환경 등 skip은 실제 브라우저·시뮬레이션 동작 검증으로 보지 않는다. 현재 Vault·Harbor Python 소스에서 제거한 submission API를 참조하는 소비자는 검색되지 않았다.

다음 완료 단위는 두 번째 실제 공정이 공통 execution을 수정하지 않고 계산·검증을 연결할 수 있는지 확인하고, 대표 작업의 요청·후보·시도·장치 결과·독립 목표 근거를 같은 revision으로 추적하는 것이다. 수치 정책의 실물 활성화는 별도 허가·설치·정지·독립 수용 증거가 필요하다.

CE: 해당 없음. 이번 책임 분리의 판단은 D-849와 최종 코드·회귀/설치 시험에 남겼다. 별도 교훈이 없으면 잃게 되는 새로운 장치 성질이나 운영 복구 순서를 해결한 작업은 아니다.
