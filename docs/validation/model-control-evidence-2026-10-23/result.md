# 모델 제어 근거 일관성 검증

2026-10-23. 코드 수정과 원격 호스트 회귀 완료. 실제 모델 성능·실물 수용은 별도다.

목표는 모델의 제안이 원본 관측과 특정 실행 시도에 결속되고, 기존 Fleet 입장·정지 검사와 장치 owner를 통과한 결과를 독립 목표 근거와 구분하는 것이다. 새 실행 권한이나 범용 World 서버를 추가하지 않았다.

## 수정과 완료 기준

| 항목 | 수정한 경로 | 완료 기준 |
|---|---|---|
| LLM 현재 상태 | `MissionFeedbackToolDispatcher` → `MissionProgressService` → `MissionStore.progress_snapshot_data` | 단일 SQLite 읽기의 Mission 행으로 principal/workcell/action/attempt/dispatch generation을 검사하고, 같은 읽기의 이벤트·정지·목표 근거로 모델 문맥을 만든다. 조회 사이에 교체된 시도를 이전 scope에 붙이지 않는다. |
| 수치 정책 결과 | `ACTInference` → `InferenceResult` → 기존 candidate/owner 경로 | 출력 벡터를 복사해 고정하고 원본 관절 수·유한 값·관측 이후 생성/반환 순서·정수 chunk·명시적 bool을 검사한다. 큐 결과는 원래 관측과 생성 시각을 유지한다. |
| 지원 범위 기록 | 이 검증 문서와 아래 기존 소유 기록 | 코드·시험 SHA, 가짜 모델, 실제 모델, SIM, 설치·실물·현장 수용을 각각 구분한다. 기록이 없는 게이트를 통과로 바꾸지 않는다. |

Fleet은 기존 읽기 트랜잭션을 재사용한다. 재계획 전후의 최신 scope·정지·워터마크 검사와 durable tool journal은 그대로 소비한다. 상태 조회는 스냅샷 시점의 상태이며 조회 후 실행 허가를 발급하지 않는다. 공개 wire 형식과 CORE Base/OMX joint 최종 권한은 바뀌지 않는다.

추론 결과 검증은 구조와 시간의 일관성을 보장한다. 임의 client가 실제 모델을 실행했는지 독립적으로 증명하거나 `inference_consumption_verified`를 참으로 바꾸지 않는다. 모델 revision의 artifact 해시 검사와 설치 검사는 기존 producer가 담당한다.

## 대표 시나리오와 남은 수용

| 경로 | 현재 근거와 책임 | 남은 완료 조건 |
|---|---|---|
| LLM 물체 이동 후보 → Fleet Mission | Decision은 후보를 생성한다. Fleet이 인증·후보·시도·정지와 결과를 결속한다. `test_er2_candidate_fence.py`, `test_er2_tool_dispatch.py`, `test_mission_progress.py`, `test_cell_goal_evidence_service.py`가 해당 경계의 호스트 회귀다. | 실제 provider와 보정된 관측 producer를 설치하고 독립 물체 결과로 한 대표 과제를 수용해야 한다. 호스트 가짜 provider 성공은 이 조건의 증거가 아니다. |
| ACT 원본 RGB/관절 → 수치 행동 | [ACTInference](../../../learning/training/omx/act_inference.py)는 고정한 config/weight/normalization bytes와 원본 관측으로 추론하고 큐 출처를 유지한다. [결과 계약](../../../contracts/learning/src/rosy/contracts/learning/inference.py)이 출력의 불변성과 시간 순서를 검사한다. | 실제 모델 성능과 설치 후 소비 증명은 별도다. 다른 세션의 실제 학습·SIM 캠페인을 이번 시험 결과로 합산하지 않는다. |
| owner 수락 → 명령 결과 → 작업 결과 | [정책 parent](../../../middleware/robot_execution/local/src/rosy/execution/local/policy_parent.py)와 [episode](../../../middleware/robot_execution/local/src/rosy/execution/local/policy_episode.py)는 journal/source/receipt를 대조한다. 파일 출처가 맞아도 추론 소비와 작업 성공은 별도로 남긴다. | 승인된 설치에서 cancel·정지·연결 유실·재시작과 실제 목표를 관측해야 한다. API 수락이나 Action 성공만으로 완료하지 않는다. |
| 현재 World → 완료 판정 | [ArmState](../../../operations/world/src/rosy/world/state/projections/arm_state.py)의 물체 상태는 `unobserved`다. 현재 자세·이미지·행동 결과·목표 근거를 각각의 소유 경로에서 소비한다. | live 물체 관측 producer와 보정을 수용하기 전에는 보유/배치 완료를 추정하지 않는다. `bridged` 자세와 prediction `NO_OBJECTION`도 완료 근거가 아니다. |

실제 모델 출처 조회와 학습 입력·SIM teacher의 별도 기록은 독립 작업 브랜치의 `pipeline-model-lineage-2026-10-21/result.md`, `learning-execution-2026-10-23/result.md`에 보존되어 있다. 해당 구현·기록을 이번 공개 변경에 포함하지 않으며 그 실행을 이번 통합 커밋의 검증으로 세지 않는다. 모듈 progress의 과거 `last_verified`를 이번 회귀만으로 전체 live 지원 검증 날짜로 갱신하지 않는다.

## 브랜치와 원격 검증

두 변경은 공통 base `118425b1b56f`에서 독립적으로 만들어졌다. 한 commit에 두 변경을 합쳐 검증했다는 뜻은 아니다. 기존 공정 제출 분리는 `refactor/process-submission-ownership`의 `ae2d8d729a36`에 별도로 보존되어 있다. main 착지·push는 수행하지 않았다.

| 브랜치 / 코드 SHA | 시험 | 결과 |
|---|---|---|
| `fix/model-evidence-consistency` / `4bc716115d` | Fleet RED | 중복 읽기 1건, snapshot 이전 scope 교체 3건의 실패 재현 |
| `fix/model-evidence-consistency` / `0c91e53d25` | 중간 회귀 | 교체 scope를 거절했으나 회귀 시험의 예상 코드가 기존 `TURN_SCOPE_FORBIDDEN`과 달라 3건 실패. 시험을 기존 계약에 맞게 수정했다. |
| `fix/model-evidence-consistency` / `5c74a6e25b` | affected 관련 소비자 | 4,555 passed, 187 skipped, 39 warnings, 5 subtests passed, 813.08초. known_failures NEW/known/flaky 모두 0. |
| `fix/model-evidence-consistency` / `5c74a6e25b` | affected Fleet 전체 | 6,137 passed, 326 skipped, 2 warnings, 889.46초. known_failures NEW/known/flaky 모두 0. |
| `fix/inference-result-validation` / `c98b481319` | 추론 계약 RED | 출력 변경 1건과 잘못된 출력/출처 19건의 실패 재현 |
| `fix/inference-result-validation` / `62e1978202` | ACT·owner capture·공통 계약 회귀 | exit 0. `-q` 중복으로 합계가 생략되어 개수는 기재하지 않는다. 출력에 skip 1건이 있으며 실제 ROS 실행 근거가 아니다. |
| `fix/inference-result-validation` / `62e1978202` | affected 43개 경로 | 955 passed, 36 skipped, 39 warnings, 104.61초. known_failures NEW/known/flaky 모두 0. |

실행 전 승인 시험 호스트 3곳의 가용 공간은 각각 약 86/124/58 GiB, 사용률은 81/72/74%로 운영 기준을 충족했다. 시험은 committed HEAD 원격 runner로만 실행했다. 로컬 pytest는 수행하지 않았다.

기본 재현 명령은 저장소 루트에서 아래와 같다. 원격 로그는 저장소 밖 `$ROSY_SCRATCH` 또는 시스템 임시 폴더에 둔다.

```powershell
python tools/harness/rosy_harness.py affected --base 118425b1b56f --head 5c74a6e25b --json | python tools/remote/remote_pytest.py --sha 5c74a6e25b --affected-json - --log-dir <scratch>/fleet-affected
python tools/remote/remote_pytest.py --sha 62e1978202 --log-dir <scratch>/inference-green -- test/test_inference_result_contract.py learning/training/omx/test/test_act_inference.py learning/training/omx/test/test_act_owner_capture.py test/test_learning_artifact_contracts.py -q
python tools/harness/rosy_harness.py affected --base 118425b1b56f --head 62e1978202 --json | python tools/remote/remote_pytest.py --sha 62e1978202 --affected-json - --log-dir <scratch>/inference-affected
```

각 원시 로그는 `python test/known_failures.py <log>`로 비교한다. RED의 NEW는 의도한 재현 실패이며 알려진 실패 목록에 넣지 않았다.

추론 affected 환경의 `torch`, `lerobot`, `rclpy` 모듈 부재도 읽기 전용으로 확인했다. 실제 weight 소비 native 시험과 ROS 실행은 건너뛴 범위다. 가짜 모델과 host fixture만으로 모델 성능·실물 결과를 주장하지 않는다. 최종 코드 두 브랜치에 대한 별도 fresh-context 검토는 producer/consumer, SQLite snapshot, 재계획 fence, ACT 큐 출처를 확인했으며 actionable finding이 없었다. 검토자가 원격 시험이나 모델·장치를 실행한 것은 아니다.

Fleet affected는 합계 10,692 passed/513 skipped이며, 추론 affected와의 중복 시험은 합산하지 않는다. 두 selector는 모두 `affected`였고 FULL 승격은 없었다. 설치 패키지 소비는 기존 `test_remaining_platform_installed.py` 등 선택된 회귀에 포함된다. 브라우저·ROS·모델 의존 검사의 skip은 해당 게이트 통과가 아니다. 새 Chromium 실행, Gazebo/Isaac 캠페인, ARM64 이미지, 실물 동작·배포·현장 수용·원격 CI는 이번 작업에서 수행하지 않았다.

원시 로그 7개는 우산 작업 공간 `Rosy/docs/workspace-records/2026-10-23/model-control-evidence/evidence/`에 보존했다. 임시 원본과 보존본의 바이트 일치를 확인했다. 사설 호스트 정보가 포함될 수 있는 원시 로그 자체는 공개 제품 저장소에 넣지 않는다.

| 로그 | SHA-256 |
|---|---|
| `fleet-affected-run-1.txt` | sha256: `c7aa4eb73fd598ca9392fab2b1153acb4fc4f29368fbd67f5a76688183d16abd` |
| `fleet-affected-run-2.txt` | sha256: `381d44b729c8e39362cfbd4b82f7f5457a5fde56fa94e58025e87c0afe501ec3` |
| `fleet-green-run-1.txt` | sha256: `3c6c0daef2056bbaa667eb08c0f7a5accfe878a2b6d685cba62d1914a9ef428e` |
| `fleet-red-run-1.txt` | sha256: `ea2fa6b4830cf58dc4f321872d878196fc516472c1790766e0a36682d7c90e77` |
| `inference-affected-run-1.txt` | sha256: `c744c7333b37f5daa44e8fd11a2f338a4af2d6aa7490f849caa33d03f89dff33` |
| `inference-green-run-1.txt` | sha256: `45549d42d17b50aba1b44b50d888e84fc081a92a1f22725269ccc9d301a475a4` |
| `inference-red-run-1.txt` | sha256: `f3675025f8f6447078c3ef36625fb228f43d77e0d260e5a6ff8373052a44989b` |

CE: 해당 없음. 발견한 원인과 방지는 코드·회귀 시험 및 이 검증 문서에서 확인할 수 있어 별도 교훈 문서를 추가하지 않는다.
