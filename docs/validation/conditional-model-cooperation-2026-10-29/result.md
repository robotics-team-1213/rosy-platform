# 조건부 모델 협력 소스 검증 (2026-10-29)

## 범위

D-913의 후보 전용 `conditional-cooperation-v1`을 구현했다. 기존 canonical `run_line_judgment` → `DeliberationJournal` 경로에 명시적으로 주입할 수 있다. v2 Judgment/IncidentCaseWorker, 장치 명령, 실행 승인과 운영 모델 배포는 변경하지 않았다.

- 역할별 동일 context·독립 의견, `auto`/`sequential`/`parallel` 선택과 재사용.
- 승인된 profile/model/prompt와 host/device/workload 측정의 결속, 현재성 재검사.
- 호출별 비용 상한 예약, 원장 기록 후 dispatch, 중단·재시작 후 자동 재호출 금지.
- 실제 dispatch call ID와 transport에 결속된 취소, 유한한 자원 반환 대기, 최초/최종 모드 선택 감사 입력.
- 같은 사건 세트의 규칙·단일 모델·기존 숙고·독립 순차·독립 병렬·auto 오프라인 비교.

## 확인된 증거

| 확인 | 커밋 | 결과 |
|---|---|---|
| 기존 기준선 4 suite | `fd6fecfb82` | 원격 AI PC 통과, NEW0 |
| 역할·selector와 기존 provider/judgment 회귀 | `40ed830baf` | 원격 88개 통과, NEW0 |
| 요청/실행·후보 원장·정책 fence 회귀 | `a6de9ee095` | 원격 99개 통과, NEW0 |
| 여섯 정책 비교와 기존 replay | `8e4962ea5c` | 원격 모델 PC 15개 통과, NEW0 |
| 최종 핵심 회귀와 설치 wheel/sdist | `587c0b4c8c` | 원격 모델 PC 121개 통과, NEW0; 아래 명령 |
| 독립 소스 검토 | `fd6fecfb82..587c0b4c8c` | 별도 읽기 전용 계약 검토자: 남은 material finding 없음 |

영향 선택(`affected --base fd6fecfb82`)은 FULL이 아닌 affected 3개 invocation이다. `a6f107d79d`에서 12,694개 통과, 615개 skip, 3개 실패였다(별도 subtest 5개 통과). Fleet/설치 묶음은 7,477개 통과·418개 skip, Gazebo 계약 묶음은 328개 통과·4개 skip이다. skip에는 opt-in browser/모델/환경 검사가 포함되며 실제 브라우저·모델 검증으로 세지 않는다.

나머지 묶음의 실패는 아래 3개다. 이 invocation은 4,889개 통과·193개 skip이었다. 시작 기준 커밋 `fd6fecfb82`와 최종 소스 `587c0b4c8c`에서 같은 node ID 3개를 각각 원격 단독 재실행하면 모두 통과했다(양쪽 NEW0). 원래 affected 실행을 전체 통과로 바꾸어 보고하지 않는다. 시간 제한이나 known-failure 기준은 수정하지 않았다.

- `middleware/core/gateway/test/test_station_redeployment_http.py::test_native_completion_between_status_and_renewal_keeps_exact_departure[lost_response]`
- `test/test_platform_g1_timing.py::test_coordinated_pairs_pass_both_barriers_within_the_proposed_bounds`
- `middleware/core/gateway/test/test_station_camera_pipeline_continuous.py::test_station_camera_http_pipeline_aligns_then_requires_contact_and_measured_stop[continuous]`

전체 영향 로그는 저장소 밖 세션의 `model-cooperation/affected/run-{1,2,3}.txt`, 기준 비교는 `base-failures/run-1.txt`, 소스 재검사는 `head-failures/run-1.txt`다. known_failures 비교 결과 run-1/run-3과 분리 재검사는 NEW0, 원래 run-2는 NEW3이다. 증상은 광역 동시 실행의 타이밍 실패이며, 부하/시험 간 간섭은 가설이다. 원인을 확정하려면 같은 호스트·같은 동시 부하를 통제해 재현해야 한다.

문서·생성 기록 head `c50d21ffc1`도 원격 `test_harness_contracts.py`, `test_document_placement.py`, `test_module_structure.py`를 통과했다(NEW0; `final-records/run-1.txt`). 최종 소스 이후 변경은 이 검증 기록과 모듈 기록뿐이다. 로컬 harness lint는 0 errors/40 warnings, size-range는 당시 16개 커밋 통과였다. 경고는 기존 모듈의 오래된 검증 상태와 worktree 슬롯 등에 관한 것이며 이번 정책의 모델·현장 수용 근거로 세지 않는다.

원격 runner의 환경 ID는 `28156067a848c865`, freeze ID는 `279c2df20eca6924`다. 실제 주소·계정·원시 서비스 자료는 기록하지 않았다. 최종 소스 시험 로그는 저장소 밖 세션의 `model-cooperation/final-focused/run-1.txt`다.

```text
python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/fleet/test/test_model_cooperation.py operations/fleet/test/test_cooperation_schedule.py operations/fleet/test/test_deliberation_replay.py operations/fleet/test/test_deliberation_journal.py operations/fleet/test/test_conditional_review.py operations/fleet/test/test_incident_deliberation.py test/test_remaining_platform_installed.py test/test_decision_replay.py -q
python test/known_failures.py <external-log-dir>/run-1.txt
```

신규 검사는 기능이 없을 때, 만료/admission·재사용·취소 결속이 잘못될 때 각각 원격에서 실패하는 것을 먼저 확인했다. runtime-first subprocess import도 순환 import로 실패한 뒤 수정했다. 예약 중 transport 교체는 reserve와 CALL_RESERVED 기록 양쪽에서 재현해 고쳤다. red 로그는 실패 재현 증거이며 수용 통과가 아니다.

## 별도 미완료 관문

실제 승인 provider와 GPU 자원 예약 adapter를 사용한 실행, 독립 사람 정답 세트의 품질 비교, GPU 포화/cold load/VLA 공존의 지연·비용 측정, 운영 shadow, ARM64·실물·현장 수용은 수행하지 않았다. fake provider/admission과 fixture 비교는 이 관문들을 대신하지 않는다. 운영 활성화는 HOLD다.

기존 시험 호스트 배치와 SIM 자원 상한은 운영 추론 admission으로 재사용하지 않는다. 실제 adapter·측정이 승인되기 전 auto/parallel을 켜지 않고 고정 순차 → 고정 병렬 → auto 순서로 별도 수용한다.

CE: 해당 없음 — 기존 「await 뒤 재검사와 신선도 감쇠」 교훈을 적용해 회귀를 보강했다. 구현·시험·기존 교훈에 없는 새 장치 성질이나 운영 복구 절차를 검증한 작업은 아니다.
