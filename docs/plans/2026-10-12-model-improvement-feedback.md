# 모델 주도 관제의 실패 피드백·개선 실행 계획

## 목표와 현재 경계

전체 source 감사에서 판정 모델의 영속 승격·복귀와 production 보정 gate 연결이 아직 없음을 확인했다. 기존 ACT/Pinky registry는 직접 대체물이 아니다. 다음 구현은 [판정 프로파일 lifecycle 계획](2026-10-12-reasoning-profile-lifecycle.md)의 reasoning 계약 → registry 전환 → 기존 Fleet 승인 hash/프로파일 포트 → 사건별 revision 보존 → 복귀 순서다. 실제 source와 필요한 회귀를 계획에 명시했으며 이 작업은 아직 구현되지 않았다.

D-681의 Phase 6을 수행한다. 자동 처리의 성공·실패·결과 불명을 원래 사건에 연결하고, 모델·관측·지도·현장 연결·장치 오류를 구분하여 개선 후보를 독립 평가한다. 사람은 최종 미해결 사건과 평가 정답을 검토한다. 운영 중 학습 결과를 곧바로 활성화하지 않는다.

이 문서는 실행 계획과 source 실행 기록이다. worker·최종 알림 연결과 사건 1건의 읽기 전용 피드백 export·녹화 사건 연결은 로컬 main에 착지했다. 서비스 활성화·후보 비교·승격은 아직 수행하지 않았다. 실제 데이터 없이 합성 사례를 현장 정답으로 기록하지 않는다.

## 기존 경로와 책임

| 단계 | 소유자와 재사용 경로 | 입력·완료 증거 |
|---|---|---|
| 사건 결과 확정 | Fleet `incidents/automation` 원장과 CORE 사건 기록 | 동일 subject/case/profile/policy, 시도·예약 비용, 원래 사건 종료와 새 CORE 관측 |
| 실패 근거 export | Fleet 기존 사건 export 경로 | 종료 또는 HOLD 원장, 결과 불명 포함, bounded 요약과 근거 hash |
| 정답·데이터 준비 | `learning/curation/perception/incident_feedback.py` | 정확한 사건·recording 식별자, 원인 검토, 미검수·충돌은 정답으로 사용하지 않음 |
| 독립 비교 | Model PC, `tools/decision_calibration.py` 및 Decision evaluation | 고정된 독립 평가 세트·모델 전체 profile SHA·calibration revision |
| 후보 기록·승격·복귀 | 기존 `learning/registry` 소유자 | 후보·현재 revision, 평가 산출물 hash, 승인·복귀 receipt; 운영 권한은 별도 admission |

현재 policy registry의 ACT/Pinky 평가 형식을 범용 판정 모델 형식으로 가장하지 않는다. 판정 모델 후보를 기록할 실제 계약과 기존 registry 확장 지점을 먼저 확인한다. 새 운영 writer나 별도 학습 서비스를 만들지 않는다.

## Task 1: 결과·시도 근거를 고정하여 export

worker의 확정된 API와 원장을 기준으로 종료/HOLD 사건, 전체 시도 수, 관측 수, 역할별 model revision, 알려진 비용과 남은 예약 비용을 export한다. 모델 원문·키·토큰·사람의 자유 입력은 내보내지 않는다. UNKNOWN은 실패 분석 대상이며 성공률 분모에서 빼지 않는다.

같은 SQLite snapshot에서 사건과 시도를 읽어 서로 다른 시점의 결과가 섞이지 않게 한다. 출력은 새 파일에만 생성하고 manifest/hash를 함께 고정한다. export 자체는 새로운 모델 호출·robot 관측·알림을 만들지 않는다.

RED: 다른 사건 결합, 진행 중 사건의 성공 표시, UNKNOWN 비용 0 추정, profile 교체로 과거 원장 덮어쓰기, 중복 export의 결과 변경, 입력 파일 덮어쓰기. GREEN: 동일 사건의 시도·종결·hash 재검증과 미확인 결과 보존.

## Task 2: 원인·정답을 구분하여 데이터 준비

D-695의 선택적 `--failure-analysis <analysis.json>`은 기존 `--model-feedback`과 함께 같은 사건·export digest에 묶인 최대 8개 분류 제안을 연결한다. `rosy.incident.failure_analysis/1`은 schema/subject_id/case_id/model_feedback_digest/reviews를 갖고 각 review는 category/source/author_id/at(timezone 포함 시각)를 갖는다. category별 책임은 judgment→Decision, observation→Perception, map→SiteMap, field_connection→Fleet, device→CORE/device, unknown→unassigned다. 모델 제안은 unreviewed, 사람도 최종 수용 전 review_candidate이며 사람 의견 충돌은 disputed다. 기존 recording 원인과 정답 상태를 바꾸지 않는다. schema /1·/2는 기존 동작을 유지하고 분석을 붙일 때만 /3을 출력한다. 자동 분류 모델 연결과 실제 팀 검수·훈련 데이터 수용은 별도 작업이다.

기존 `incident_feedback.bind`의 사건 ID/recording 결합과 미검수·검수 후보·충돌 상태를 유지한다. 범용 판정 오류의 분류는 `judgment`, `observation`, `map`, `field_connection`, `device`, `unknown`으로 소유자에게 연결하되, 모델이 제안한 분류를 정답으로 승격하지 않는다. 실제 분류 계약은 기존 incident schema와 검수 기록을 읽은 후 확정한다.

train·calibration-fit·독립 evaluation은 session/recording 식별자와 원본 hash 모두 분리한다. 훈련 데이터에 섞인 사례는 독립 평가에서 제외하고 새로운 held-out 사례를 확보한다. 정상 미개입·근거 부족·위험·다른 사건·재시작·모델 교체 사례를 평가 세트에 포함한다.

RED: 미검수/의견 충돌을 정답으로 변환, 사건 ID 추정, recording/hash 중복, 모델 답을 자기 정답으로 사용, 개인 정보 노출. 기존 feedback 시험을 함께 실행한다.

## Task 3: 동일 독립 사건 세트에서 후보 비교

현재 Fleet 규칙, 현재 기본 모델, 기본+검토 모델, 개선 후보를 같은 고정된 evaluation manifest로 비교한다. 정확한 모델·프롬프트·adapter·schema·지원 입력·한도·calibration을 전체 profile SHA로 고정한다. 실제 비용과 지연은 실제 호출 receipt로만 채우고 합성 시험 수치를 운영 성능으로 쓰지 않는다.

비교 항목은 실제 종결률·결과 불명률·재발률·정상 불필요 개입·위험 누락·다른 사건 결합·사람 인수율·지연·비용이다. 사람 인수율 감소만으로 개선을 승인하지 않는다. 금지 오류는 0건이어야 하며, 검수된 정확도·보정·지연 한계가 없으면 HOLD다. `.95` 보정 신뢰도와 `.20` 대안 확률 차이는 기존 초기 기준을 유지하고 현장 성능으로 해석하지 않는다.

RED: 서로 다른 evaluation 세트 비교, 현재 후보만 분모에서 UNKNOWN 제외, 금지 오류를 평균 점수로 상쇄, 보정 artifact/profile 불일치, 비용 불명 상태에서 비용 개선 승인. GREEN: 같은 manifest의 비교와 회귀 시 거절.

독립 보정 비교의 실행 경로는 `python tools/decision_calibration.py --compare <bundles.json>`이다. Model PC의 고정 입력 파일은 기존 `fit/evaluation/training/reviewed_profile` bundle 2~4개의 배열이며 첫 bundle이 현재 기준이다. 같은 held-out 사건 ID·session/recording ID와 hash·정답·검수자·domain·선택지·평가 한계를 요구하고, 각 후보의 기존 데이터 hash·훈련/보정/평가 분리를 다시 검증한다. 전체 프로파일 SHA 중복과 서로 다른 정답 세트는 거절한다.

출력 `rosy.calibration.comparison/1`은 공통 정답 manifest hash, 기준 프로파일 SHA, 후보별 보정 artifact SHA·상태·측정값·회귀 항목을 고정한다. 정확도 하한·보정 coverage 감소, Brier/ECE·보정 오차·p95 지연 증가를 거절하고 금지 오류는 FAIL, 미검수 한계는 HOLD다. 모두 통과해도 상태는 `PASS_COMPARISON_OFFLINE_ONLY`, 운영 승격은 항상 `HOLD`, 현장 수용은 false다. 이 출력은 실제 종결·결과 불명·재발·인수·비용을 missing evidence로 명시한다. 따라서 Task 3의 전체 운영 성과 비교나 Task 4 승격 완료를 뜻하지 않는다.

## Task 4: 제한된 후보 승격과 복귀

독립 평가와 기존 실행 admission을 통과한 후보만 새 profile revision으로 다음 사건부터 적용한다. 진행 중 사건은 원래 profile·예산·원장·정책을 유지한다. 승격 전 현재 revision과 artifact hash를 복귀 대상으로 기록하고 후보의 수용 근거를 재검증한다.

위험 회귀·예산 초과·결과 불명 증가 시 새 사건에 대한 후보 admission을 중단하고 이전 승인 profile로 복귀한다. 진행 중 UNKNOWN 시도를 다시 제출하거나 안전 정지를 해제하지 않는다. registry의 메타데이터 변경, 운영 설정 readback, 실제 새 사건의 활성 profile 확인을 각각 별도 receipt로 남긴다.

RED: 평가 통과만으로 운영 활성화, 진행 중 사건 profile 교체, 과거 예산 초기화, 결과 불명 재제출, 복귀 revision 불명. 실제 현장 수용이 없으면 FIELD는 HOLD다.

## 검증과 완료

각 Task는 필요한 계약을 읽고 작은 RED/GREEN 시험을 먼저 만든다. 커밋 HEAD를 시험 PC에 전달하여 원격 pytest를 실행하고 `test/known_failures.py`로 비교한다. 원격 source 시험, 실제 제공자, 독립 품질, 설치·활성화 readback, 현장 수용을 각각 기록한다. Discord 서버·웹훅 설정은 담당 세션의 범위로 유지한다.

## 2026-10-12 source 실행 기록

- `tools/incident_model_feedback.py`는 정확한 subject/case와 고정된 primary/reviewer 프로파일 파일을 받아 SQLite `mode=ro`·query-only 단일 snapshot에서 원장과 시도를 읽는다. 프로파일 전체 SHA, 합계 비용·시도 수, 불가능한 시도 비용, scope/time에 맞는 종결 receipt를 검증하고 새 출력 파일만 만든다. 원문·worker ID·개인 검수 문구를 export하지 않는다.
- 기존 `learning/curation/perception/incident_feedback.py`의 기본 `bind`와 schema `/1`은 유지한다. 선택적 `--model-feedback`은 content hash와 정확한 robot/case를 대조해 schema `/2`로 제한된 모델 근거를 붙인다. 검수 상태와 사람의 정답은 유지하며 모델 자료는 `UNREVIEWED`다. content hash 자체는 정답이나 승인 증거가 아니다.
- 모델 연결·실제 호출·녹화 수집·훈련·후보 승격 없이 기존 사건 결과와 녹화 표식만 처리한다. 결과 불명 비용은 null과 남은 예약 비용으로 보존한다. 미개입은 `DO_NOT_INTERVENE`, 진행 중은 `IN_PROGRESS`, 결과 미확인은 `UNRESOLVED`로 구분한다.
- 최초 RED 7 NEW 뒤 기본 export/store 23 GREEN, 독립 검토의 원장 무결성 RED 3 NEW 뒤 26 GREEN을 확인했다. 녹화 연결 RED 5 NEW 뒤 실제 export→binder·CLI를 포함한 37 GREEN을 확인했다. 이어 한글 프로파일 해시와 미개입 의미 RED 2 NEW를 고쳐 `c7afe628ca`의 관련 5개 파일 87 passed, exit 0, known-failures NEW 0을 확인했다. 모두 여유 호스트의 source/합성 검증이며 같은 시험의 반복·중복 수를 합산하지 않는다.
- 로그: `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/feedback-*`. 최종 87개는 `feedback-final-green/run-1.txt`, 현장 PC의 8.9GB 자원 하한을 충족했다.
- 독립 review의 비용·종결 상태·Unicode 직렬화 지적을 반영했다. 실제 현장 export·팀 검수 정답·품질 개선·최신 worker schema 통합·로컬 착지는 별도 검증하며 이 기록에 포함하지 않는다. Task 3·4와 범용 오류 소유자 분류는 미완료다.

## 판정 근거 연결 checkpoint

후속 source는 검증된 판정 JSON·원래 문제·고정된 두 역할의 전체 프로파일을 시도별 receipt로 보존한다. 사건·입력 hash·관측 revision·역할·종결 상태를 원장의 실제 비용과 같은 transaction에서 검증한다. receipt 변조나 깊은 JSON·범위 밖 숫자는 판정을 거절하되 이미 알려진 호출 비용은 기록한다. worker는 원장 기록이 거절된 판정을 후속 관측 선택에 사용하지 않는다.

export는 같은 읽기 전용 snapshot에서 시도와 receipt를 결합하고 각각 재검증한다. 고아 receipt·다른 입력·원문 필드는 거절한다. 과거 DB의 receipt 누락은 null로 표시한다. 개별 요청의 16KiB 한도를 사건 전체에 적용하지 않으며 전체 export는 1MiB 미만으로 제한한다. 이 자료는 계속 `UNREVIEWED`이고 검수 정답을 만들지 않는다.

이전 export 구현에 새 시험을 실행하여 예상한 6 NEW를 실제로 확인했다. 관련 로그는 `logs/trace-export-valid-red/run-1.txt`이며 적격 AI PC 9GB에서 실행했다. GLM v2 bridge를 포함한 `e0666b3e3f`의 9개 파일 통합 시험은 적격 Model PC 9GB에서 204 passed, exit 0이다. 로그는 `logs/trace-glm-integrated-green/run-1.txt`다. 두 경로의 기준 폴더는 위 source 실행 기록과 같다. 독립 source 검토의 중요 지적은 반영했다. 실제 provider 호출·런타임 admission·팀 검수·훈련·후보 비교·승격은 아직 미완료다.

## D-694·D-695 source checkpoint

호출별 비용 근거의 원자 기록과 export 연결은 `bc7ba9106fb83e3810237ceb2afa30c8deba1cc3`으로 로컬 main에 착지했다. 관련 9개 파일 원격 162 passed, known-failures 신규 실패 0건, lint 0 errors다. 고정 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--051704--incident-model-trace--416dac/logs/cost-land-bc7ba9106f/run-1.txt`이며 SHA256 `3832618a324300590ea3560b20d77c9120dec77b69a53abf7fd107d532cc5730`이다. 실제 청구 null과 정책 한계 비용을 구분하고 근거 오류에서도 이미 확인한 비용을 보존한다.

실패 분류의 원래 사건·모델 근거 결속, 모델 제안과 최종 검토 후보의 분리, 기존 recording 원인·정답 상태 보존은 `1eab62769c0b57f260c48f938e78311bcdd88689`로 로컬 main에 착지했다. 시험 추가의 17 NEW를 확인한 뒤 최종 관련 5개 파일은 적격 AI PC 9GB에서 89 passed, exit 0, known-failures 신규 실패 0건과 lint를 통과했다. 독립 source 검토에 중요 미해결 지적은 없다. 고정 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/failure-analysis-land-1eab62769c/run-1.txt`이며 SHA256 `9d2ae3ded04360ffc106f93a140d744e62f14c45a8fcac7ca31e5df9aa8ef6a9`이다.

자동 분류 모델 연결, 실제 팀 정답·훈련 데이터 수용, Task 3의 전체 운영 성과 비교와 Task 4의 승격·복귀는 아직 완료하지 않았다. 소스·합성/offline 시험만으로 실제 모델 품질·운영 활성화·현장 성공을 승인하지 않는다.
