# 사건 worker 런타임 연결과 실제 Fleet 비교 기준 수용

- 날짜: 2026-10-12
- 상태: 후속 구현 계획. 실제 모델·운영 활성화 `HOLD`.
- 확인 기준: `9a96f88a5`의 소스와 D-672/D-674/D-681/D-684. 이 문서는 새 판단 규칙이나 실행 권한을 승인하지 않는다.
- 상위 계획: [모델 중심 사건 처리](2026-10-12-model-led-incident-closure.md), [사건 worker](2026-10-12-incident-case-worker.md).

## 확인한 현재 경계

`StuckResolverLoop`는 기존 gather의 결과를 전달하는 `feed()`를 갖는다. [app.py](../../operations/fleet/fleet/server/app.py)의 `incident_model_config`와 [runtime.py](../../operations/fleet/fleet/incidents/automation/runtime.py)는 같은 Fleet journal의 원장·사람 인수·읽기 관측·최종 outbox를 구성한다. 설정 없음은 worker 없음이며 명시적 설정도 `enabled=False`가 기본이다. 실제 운영 프로파일·제공자·호스트 admission·기준 판단을 주입하는 배포 구성은 아직 없다. 원격 소스 시험은 실제 제공자 수용을 대신하지 않는다.

[loop.py](../../operations/fleet/fleet/stuck/loop.py)의 `run_once()`는 gather → worker feed → 사람 claim 반영 → heading/closed-loop 확인 → `resolver.step()` 1회 → 기존 전송 순서다. [resolver.py](../../operations/fleet/fleet/stuck/resolver.py)의 `step()`는 chain·plan·escalation 상태를 변경한다. 비교용으로 두 번째 호출하면 동일 입력의 독립 읽기가 아니다.

[FleetBaseline](../../operations/fleet/fleet/server/incident_deliberation.py)은 완전한 `AssessmentInput`, 정책 revision과 `reobserve` 또는 `human`을 보존한다. [worker.py](../../operations/fleet/fleet/incidents/automation/worker.py)는 이를 현재 request/policy와 비교하고 `Problem.fleet_choice`에 넣는다. 현재 실제 producer는 없으며 `baseline=None`은 비교 기준 없음이다. 테스트의 주입 lambda를 실제 Fleet 판단 증거로 부르지 않는다.

## 기존 해결기 조치와 사건 검사 방향

| 실제 결과 | 보존할 의미 | 기존 계약으로 가능한 비교 |
|---|---|---|
| `Escalate` | 이유가 있는 인수 의도 | `human` 의도만 비교 후보. 이름 있는 담당자의 claim·수신·처리 완료 증거는 아님 |
| `Answer.escalate`가 있음 | 선택된 조치와 조건부 인수 의도 | 조치와 인수 조건을 각각 기록. 아직 완료된 인수로 해석하지 않음 |
| `WAIT` | CORE에 보내는 정지/대기 답 | `reobserve`로 바꾸지 않음. R1 대기와 R5 인수 대기 구분 |
| `BACK_AND_RETRY`, `YIELD`, `RESUME` | 기존 CORE admission을 거치는 물리 후보 | 읽기 재관측이나 모델의 `human`과 직접 동등 비교하지 않음 |
| 결과 없음 | offline·claim·진행 중 답·AI 대기·로컬 상태 변화 등 여러 가능성 | 정상·재관측·동의로 추정하지 않음 |

`reobserve`의 실제 Fleet producer는 별도 사건 검사 정책이 명시적으로 선택해야 한다. 현재 `INTERVENE/blocked` Assessment나 `WAIT`만으로 그 선택을 만들 수 없다. 처리 방향을 선택할 입력·한계·정책 revision은 후속 ADR로 고정한 뒤 구현한다. 그 전에는 물리 조치를 원형 그대로 기록하고 비교 불가능으로 표시한다. 기준 없음과 Fleet/모델 동의는 다르다.

## 한 번 계산한 결과를 같은 관측에 묶는 단계

`line-follow-shadow-v1`은 필요성/관측 freshness 정책이며 해결기 전체 규칙 버전이 아니다. 실제 선택에는 `ResolverConfig`, chain/진행 상태, trip·crosswalk·map pose·활성 map, AI proposal/설정도 영향을 준다. 선택 receipt는 사용한 설정/지도 revision과 추가 입력의 범위·hash를 보존해야 한다. 현재 같은 CORE request라는 이유만으로 이 입력들의 불변을 추정하지 않는다. 이 정보가 없는 기존 resolver note는 비교 기준으로 수용하지 않는다.

1. 기존 poll의 snapshot과 현재 Assessment를 고정한다. subject/case/CORE owner, 전체 request, evidence 시각·ID, revision과 정책을 함께 보존한다.
2. 기존 `resolver.step()`를 1회 실행한다. 결과 목록과 선택에 사용한 행을 기록하되 규칙을 다시 실행하거나 CORE를 호출하지 않는다.
3. 실제 생성 지점에서 조치 종류·rule·조건부 인수 이유와 원래 Assessment를 묶는 불변 receipt를 만든다. 다른 로봇·다른 사건·중복 결과·다른 revision은 비교 기준을 만들지 못한다.
4. `human` 의도 또는 후속 ADR의 명시적 검사 방향만 `FleetBaseline`으로 발행한다. 선택되지 않은 조치나 빈 목록을 `reobserve`로 채우지 않는다.
5. worker feed와 baseline 발행 순서를 함께 연결한다. 현재의 step 이전 feed에 나중 결과를 소급 결합하지 않는다. await 이후에도 현재 request/policy와 baseline 전체가 같아야 하며, 바뀌면 호출을 중단한다.

이 receipt는 선택 증거다. `_answer()`의 이후 재관측, law/AI admission, CORE 수락, 결과 불명, 실제 정상 종결을 대체하지 않는다. 기존 physical dispatch를 비교 기록 때문에 지연하거나 바꾸지 않는다.

## 사람·규칙·모델 소유권과 scheduling

현재 `_escalated()`와 `claim()`은 기존 해결기를 사람 처리 상태로 옮긴다. 사건 worker는 사람 소유를 거절한다. 따라서 `human` baseline을 수집했다고 그 사건의 모델 재평가가 실제 실행된다고 주장할 수 없다. 같은 pass에서 인수가 먼저 완료되면 모델 호출은 0회여야 한다.

실제 구성은 이름 있는 durable claim, resolver의 claim/escalation과 진행 중 전송을 구분해야 한다. 모델 처리 중 기존 규칙이 같은 사건을 전송할 때도 원래 request가 바뀌면 결과를 사용하지 않는다. 기존 E-stop·calibration·trip·offline 제한과 사람 인수는 모델 대기 때문에 늦추지 않는다.

자동 검사를 기존 인수보다 앞세울 범위는 아직 운영 정책이 아니다. 그 범위를 정할 때 안전상 즉시 인수, 이미 제출된 조치/UNKNOWN, 기존 규칙의 진행 상태, 제한된 읽기 검사, 최종 인수를 구분하는 ADR이 필요하다. 기존 claim을 해제하거나 전송을 재발행하여 모델 호출을 성립시키지 않는다.

## 명시적인 운영 factory와 수용 receipt

source factory는 기존 Fleet board와 동일 DB에만 worker를 구성한다. `incident_model_config`의 필수 입력은 고정 `profiles`, 일치하는 `providers`, `admission`, `current_profiles`, `budget`이며 선택 입력은 `enabled`, `baseline`, `clock`이다. 모델별 분기는 없다. 사람 소유는 영속 handoff와 현재 resolver claim을 함께 확인하고, 관측 port는 기존 poll만 읽는다. `set_automation(worker.prepare_receipt)`는 기존 판단 저장 transaction을 사용하고 caller의 commit/rollback을 유지한다. 최종 실패는 동일 outbox에 저장하며 resolver loop 종료는 기존 worker `aclose()`로 UNKNOWN 보존을 끝까지 처리한다.

포함 플랜의 상세 billing receipt는 D-694의 호출별 불변 CostEvidence를 통해 generic worker의 같은 completion transaction과 model receipt /2, 읽기 전용 export에 연결됐다. 입력·job·단일 프로파일·판정 hash와 한계 비용을 재검증하며 기존 tuple2·receipt /1을 유지한다. 확인된 비용은 근거 오류로 거절해도 보존하고 후속 선택을 막는다. 실제 관측 청구 null을 0 청구로 바꾸지 않는다. 이 source는 `bc7ba9106f`로 로컬 main에 착지했으며 관련 9개 파일 원격 162 passed, known-failures 신규 실패 0건, lint 0 errors다. 실제 정책·제공자·보정·scope-bound Fleet 기준 수용은 여전히 남아 있으므로 source factory만으로 운영을 승인하지 않는다.

프로파일 수용은 다음 증거를 별도로 고정한다.

- 모델 ID와 실제 revision, 프로파일 쌍 SHA, 제공자/어댑터, schema 2, domain·modality 및 개별/누적 호출·관측·시간·비용 한계.
- 실제 실행 계정·격리 경계·허용 endpoint, 제공자 연결, 출력/취소/timeout 경계와 증거가 관측된 호스트/시각. 소스의 정적 capability 표식은 receipt가 아님.
- 독립 평가와 calibration revision의 해당 프로파일 전체 SHA 일치. 합의·모델 자체 confidence는 독립 수용이 아님.
- 모델·설정·정책·소유자 변경에 따른 admission 폐기. 다른 사건·프로파일·장치에 receipt를 재사용하지 않음.

[OllamaTransport](../../deploy/ai_pc/deliberation_ollama.py)는 고정 local endpoint/backend를 사용하지만 기본 `ready/isolated/cost_verified`가 false다. 실제 호스트 수용 descriptor와 schema 2의 요청/응답 검증이 있어야 `VersionedLocalProvider`에 연결할 수 있다. Fleet에서 AI PC의 loopback broker까지의 전달 경로는 현재 운영 구성에 없으며, 임의 URL 인자를 추가해서 해결하지 않는다.

[GLM gateway](../../deploy/ai_pc/deliberation_glm_gateway.py)는 기존 legacy opinion 경로를 유지하며 별도 v2 codec으로 공통 판정 요청·검증된 prior·응답을 연결한다. [GlmOpenCodeLauncher](../../deploy/ai_pc/deliberation_opencode.py)의 기본 `ready/isolated/cost_verified`는 false다. v2 호출에는 정확한 전체 ModelProfile, 외부 runtime admission, 유효한 included-plan 정책 증거가 모두 필요하다. 동일 revision이라도 calibration·역할·한도가 바뀌면 거절한다.

[GLM receipt](../../deploy/ai_pc/deliberation_glm_receipt.py)는 host gateway의 요청·프로파일·판정 hash, 실제 제공자 response/request ID와 사용량을 재검증한다. 정책의 credential fingerprint는 실제 gateway 키와 READY·영속 호출 표식·upstream 전에 대조한다. SDK의 cost 값은 비용 증거로 사용하지 않는다. 승인된 포함 플랜의 한계 현금 비용 정책으로 0을 기록하더라도 실제 관측 청구는 null, 원래 host 비용 상태는 UNKNOWN으로 보존한다. 포함 플랜 정책은 월 구독료·quota 소비가 없다는 뜻도, 격리·정확도·현장 수용 증거도 아니다.

`7bccf0a6a0`의 관련 5개 파일 source 시험은 적격 AI PC 10.3GB에서 90 passed, exit 0, known-failures NEW 0이다. 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/glm-launcher-final-green/run-1.txt`다. 키·프로파일 drift 관련 독립 검토 지적을 반영했다. 실제 정책·admission 증거 생성과 제공자 호출은 수행하지 않았다. 기존 v1-only admin staging에는 v2의 Decision/Foundation 및 pinned Python 의존성이 없으므로 새 설치 closure를 확인해야 한다.

D-679의 최초 GLM 시험 한 번·30초·1,024 토큰·무재시도 표식은 유지한다. 반복 worker를 구성하며 이 표식을 지우거나 첫 시험 허용을 반복 호출 허용으로 바꾸지 않는다. 사용량과 실제 과금 증거를 구분하고, 미확인 비용은 UNKNOWN과 예약 예산으로 남긴다.

## 후속 검증과 완료 판정

1. producer의 무효 scope·중복/빈 결과·WAIT/물리 조치·다른 revision을 시험한다. `step()` 호출 수는 항상 1회이고 기존 dispatch와 결과가 동일해야 한다.
2. 실제 factory를 기본 비활성 및 명시적 수용 descriptor로 구성한다. 미수용 제공자, 사람 인수, 정책/프로파일 교체는 호출 0회로 검증한다.
3. schema 2의 실제 local Qwen 요청→검증된 판정→같은 사건의 다음 poll을 확인한다. 답이 도착하기 전 인수/사건 변화는 결과를 폐기한다.
4. 의미가 확정된 Fleet 기준과 Qwen의 불일치에 한해서 수용된 reviewer prior를 전달한다. 실제 GLM 연결과 허용 한도는 별도 증거와 승인 범위 안에서 검증한다.
5. 모델 추가 호출 없이 최종 outbox의 영속 대기·새 관측·재시작·중복 방지·사람 인수를 검증한다. config 없음, 큐 저장, 제공자 수락, 팀원 수신, 이름 있는 claim과 현장 해소를 각각 기록한다.

소스·원격 mock 시험·독립 리뷰는 현재 개발 증거다. 이 계획만으로 factory 구성, 모델 실행 수용, 운영 활성화, 배포 또는 Pinky 현장 수용을 완료로 표시하지 않는다.
