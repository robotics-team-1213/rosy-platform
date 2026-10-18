## D-793 OMX 학습 정책의 실물 실행 승인 관문: 학습은 실행 권한을 바꾸지 않고, 위험하면 멈춘 뒤 API로 확인받는다

**Status:** Proposed

## Context

2026-10-18 사용자 지시: 학습을 하더라도 그 정책 모드로 바로 넘어가지 않게 하고, 파손 위험을 고려한다.
위험한 경우에는 실행하지 않고 Fleet이나 learning에서 확인을 받거나 API로 처리하는 구조가 필요하다.
같은 날 사용자 답변: learning 승인자와 Fleet 승인자를 같은 사람이 맡아도 된다. 사고 뒤 재승인은 관리자 권한이며
현재 팀원은 모두 관리자다. lease 기본 만료 시간은 기존 구조를 보고 정한다.

D-770은 실물 데이터 수집과 ACT 학습의 완료 기준을 정했지만, 학습된 정책이 언제 실물을 움직여도 되는지는 정하지 않았다.
같은 날 저장소를 조사한 결과는 다음과 같다.

| 항목 | 현재 | 판단 |
|---|---|---|
| owner 허용 목록 | 운영 cell owner `("pilot_sim","rule_based")`, 수집 `('rule_based',)`, D-785 실물 owner `("rule_based",)` | `learned_policy` 명령은 거부된다 |
| 아키텍처 시험 | `test/architecture/test_omx_policy_config.py`가 추적 파일의 `learned_policy` 활성화를 막는다 (D-442) | private overlay는 검사하지 못한다 |
| `deploy/robot/omx/run_hardware_owner.py` | `allowed_owners`를 private JSON에서 읽고 실행 시 `learned_policy`를 거부하지 않는다 | 설정 한 줄로 막힘이 풀리는 빈 곳 |
| `OwnerPolicySession` (`middleware/robot_execution/local/.../omx_policy.py`) | 기본 `enabled=False`, 설치 lease 상한 기본 1초, 매 동작과 `renew`마다 lease·authority·정지 fence를 확인하고 실패하면 cancel+HOLD | 장치 쪽 확인은 있다. lease 발급기와 승인 API는 없다 (D-773 A4) |
| 모델 승격 | `learning/registry/policy/registry.py`와 `validate_promotion`이 L0→L3을 한 단계씩만 올린다 | 승격은 메타데이터이고 owner 실행 권한과 연결되지 않는다 |
| 사람 승인 API | `POST /api/fleet/missions/{id}/admit`(two_person에서 제안자≠승인자), `POST /api/fleet/workcells/{id}/owner/recover`(operator_confirmed) | 정책 승인에 그대로 쓸 패턴 |
| 오프라인 평가 | 실물 학습 `native_cycle.py`는 eval MAE와 별도 프로세스 재적재를 이미 한다. 실시간 추론기 `act_inference.py`는 `environment=='sim'`, 카메라 1대만 받는다 | 오프라인 평가는 있다. 실물 학습 결과의 정책 artifact 등록과 카메라 2대 추론이 없다 |
| 실시간 shadow | 없다 | 실물 관측으로 추론만 하고 명령을 보내지 않는 실행기가 필요하다 |
| 파손 기록 | 저장소·private 기록에서 OMX·Pinky 하드웨어 파손 기록을 찾지 못했다 | 사고 처리 절차를 미리 정한다 |

같은 날 실물 기록(비공개 `problem-analysis-20261018.md`)에서 토크를 켠 그리퍼에 2틱 목표가 송신됐지만
present 위치가 바뀌지 않았는데 Action은 SUCCEEDED였다. 명령 성공 응답은 실제 이동이 아니다.

## Decision

### 1. 학습은 실행 권한을 바꾸지 않는다

학습 산출물은 policy registry의 L0으로만 등록된다. L0은 오프라인 재생만 허용한다.
다음 단계는 사람이 Fleet API로 승인할 때만 열린다. 학습 종료·평가 통과·승격 기록이 자동으로 owner 허용 목록이나
lease를 바꾸지 않는다. 승격 단계는 lease 발급의 필요조건이며 충분조건이 아니다.

| 단계 | 허용 | 열리는 조건 | 승인 |
|---|---|---|---|
| L0 학습됨 | 오프라인 재생 | 학습 receipt, model/processor hash | 자동 등록 (실행 권한 없음) |
| L1 오프라인 통과 | 오프라인 재생 | held-out 오차와 기준선 비교 | 관리자 1인 |
| L2 shadow | 실물 관측으로 추론하고 명령은 보내지 않음 | L1, shadow 기록 (teacher 행동 비교·위험 출력 집계) | 관리자 1인 |
| L3 입회 시험 | 사람 입회, 짧은 승인 창, 제한된 과제·속도 | L2, 정지 readback | 제안자와 다른 관리자 |
| 제한 사용 | 승인된 과제·범위 | D-770 G4 (teacher·learner 각 10회 이상 독립 평가) | 제안자와 다른 관리자, ADR로 범위 고정 |

learning 역할과 Fleet 역할은 한 사람이 겸할 수 있다. 다만 실물 구동을 여는 L3·제한 사용·사고 뒤 재승인은
기존 two_person 규칙대로 제안자와 승인자가 달라야 한다. 팀원이 모두 관리자이므로 역할만으로는 사람을 나누지 못하고,
제안자≠승인자가 남는 유일한 상호 확인이다.

### 2. 승인과 lease는 두 층이다

| 층 | 의미 | 기본값 | 상한 | 근거 |
|---|---|---|---|---|
| 승인 창 | 사람이 "이 정책을 이 workcell·rig·보정 revision에서 이 범위로 실행해도 된다"고 한 기간 | L3 15분, 제한 사용 8시간 | L3 30분, 제한 사용 8시간 | L3은 한 번에 입회자가 집중할 수 있는 시간. G4의 10회(각 1분 이내 실행 + 원위치·확인)는 승인 창 두 번으로 나뉘어 중간 점검이 생긴다. 제한 사용은 한 근무 교대를 넘지 않는다 |
| 실행 lease | 장치가 매 동작과 `renew`에서 확인하는 dead-man 권한 | 1초 | 2초 | 기존 `OwnerPolicySession` 설치 상한 기본 1초를 유지한다. Fleet이 승인 창 안에서 절반 주기로 갱신한다. Fleet·네트워크가 멈추면 1–2초 안에 HOLD가 된다 |

실행 lease는 승인 창을 넘어 발급되지 않는다. 승인 창이 끝나면 갱신이 멈추고 HOLD가 된다. 자동 재승인은 없다.
L2 shadow는 명령을 보내지 않으므로 실행 lease가 없고, 승인 창(8시간)만 둔다.
값은 첫 L3 시험의 실제 갱신 지연 분포로 다시 확인한다. 측정 없이 상한을 늘리지 않는다.

### 3. 위험하면 실행하지 않고 확인 요청을 남긴다

아래 경우 owner는 그 명령을 거부하고 HOLD한다. Fleet에는 확인 요청 항목이 남는다.
항목에는 원인, 시각, 정책 digest, workcell·rig·보정 revision, 원본 증거 경로가 들어간다. 자동 재개는 없다.

| 상황 | 동작 | 확인 |
|---|---|---|
| 처음 쓰는 모델, 모델 digest가 승인과 다름 | 실행 안 함 | 승인 절차 (1절) |
| rig·보정 revision이 승인과 다름 (재조립·재보정·모터 교체) | HOLD, 해당 승인 무효 | 재승인 |
| 환경이 지원 범위 밖 (조명·시야 가림·영상 정체) | HOLD | Fleet |
| 정책 출력이 한 step 변화량 상한 초과, 승인 범위 밖, 유한하지 않음 | 그 명령 거부 + HOLD | learning |
| 명령은 성공했는데 실제 위치가 목표 허용차에 들지 않음, 과전류·PWM 포화 | HOLD | Fleet (기구 점검) |
| 관측·status·명령 시간 예산 초과 | HOLD | Fleet |
| owner fault, 모터 hardware error, 통신 단절 | 기존 정지 경로 + HOLD | Fleet |
| 사고·파손 기록 | 해당 workcell의 모든 승인 무효, 전체 정지 | 원인 기록 뒤 제안자와 다른 관리자의 재승인 |

확인 요청은 API로만 해결한다.

- `resume`: 같은 승인 창 안에서 재개. `owner/recover`와 같이 operator_confirmed·이름·기대 generation이 필요하다.
- `abort`: 승인 창과 실행 lease를 폐기한다.
- `send_to_learning`: 해당 episode를 learning 검토 대기로 보낸다. 검토자는 정책 단계를 강등할 수 있다.

### 4. 물리 한계는 정책과 무관하게 장치에서 강제한다

관절별 허용 범위·속도·가속도, 한 step 변화량 상한은 owner와 장치 레지스터 양쪽에서 강제한다.
그리퍼 current 상한은 끼임·압착 방지용으로 PWM 상한과 별도로 유지한다.
독립 watchdog과 토크 OFF helper는 정책 실행에서도 그대로 쓴다.
하중을 받는 관절은 토크 OFF 때 처짐을 막는 지지 수단을 확인한 뒤에만 정책 대상에 넣는다.

### 5. 이 결정이 요구하는 구현 (순서)

| 순서 | 내용 | 비고 |
|---|---|---|
| A | `run_hardware_owner.py`가 설정에 `learned_policy`가 있으면 기동을 거부한다. 수집 단계 판정에 "실제 위치가 목표 허용차에 들었는가"를 기록하고, 들지 않으면 HOLD한다 | 첫 수집 전. D-430 Safety-Review 필요 |
| B | 첫 수집 (D-770 G1). scripted teacher(`rule_based`)만 움직인다 | D를 기다리지 않는다 |
| C | 학습 결과는 L0 등록만 한다. 실물 학습 결과를 정책 artifact로 등록하고 카메라 2대 추론을 지원한다 (shadow의 전제) | 실행 권한은 그대로 없다 |
| D | 확인 요청 항목과 해결 API, 승인 API(`promote`, 승인 창), 실행 lease 발급기, 실시간 shadow 실행기, `learned_policy` 수집 출처 | 외부 API는 API Reference·schema와 함께 별도 버전으로 정한다 |
| E | L3 입회 시험과 G4 판정 | |

D가 끝나기 전에는 학습된 정책이 실물을 움직일 경로가 없어야 한다. A의 기동 거부를 먼저 넣는 이유다.
이 ADR은 경로·필드 이름을 확정하지 않는다. 3절의 API 이름은 역할을 가리키며, 실제 경로는 D 단계에서
API Reference와 `core_common.protocol.schemas`에 함께 정한다.

## 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-427 | 새 최상위 폴더 없음. 승인·확인 요청은 `operations/fleet`, 승격 기록은 `learning/registry`, 실행 확인은 기존 owner와 `middleware/robot_execution` |
| D-429 | source 위치와 호스트 역할 변경 없음. 외부 API·DTO는 D 단계에서 API Reference와 schema로 정한다 |
| D-430 | owner 허용·lease·HOLD·정지 변경은 safety 경로다. A·D 구현 커밋은 `Safety-Review:` trailer와 독립 리뷰가 필요하다 |
| D-442 | 추적 설정의 `learned_policy` 금지를 유지하고, private overlay에는 실행 시 거부를 더한다 |
| D-516, D-527 | 학습·평가는 모델 PC, 승인·admission은 Fleet, 실행 전 재확인은 장치. 그대로 따른다 |
| D-330, D-332 | Fleet 단일 claim, 사람 확인 시점. 정책 승인은 등록 뒤 범위 밖·사고·재승인에서만 사람을 부른다는 원칙과 같다 |
| D-770 | 수집·학습 완료 기준 유지. G4를 제한 사용의 전제로 쓴다 |
| D-773 | `OwnerPolicySession`의 Fleet lease 요구(A4)를 구체화한다. lease 기본·상한 값을 정한다 |
| D-782 | World 모델 예측은 거절·보류 근거로만 쓴다는 원칙과 같다. 3절의 확인 요청 원인으로 들어갈 수 있다 |
| D-785 | 실물 owner의 `allowed_owners=("rule_based",)`와 no-goal 원칙을 유지한다. 학습 정책 허용은 이 ADR의 L3 이후에만 검토한다 |

## Alternatives

| 접근 | 판단 |
|---|---|
| 학습 평가가 기준을 넘으면 자동 승격·실행 | 기각. 오프라인 오차는 실물 안전을 보장하지 않고, 사용자 지시와 반대 |
| 승인 한 번으로 장시간 lease | 기각. Fleet·네트워크 정지가 장치 정지로 이어지지 않는다 |
| 사람 확인 없이 HOLD 뒤 자동 재시도 | 기각. 원인이 기구 문제면 파손을 반복한다 |
| 역할 분리 (learning 승인자 ≠ Fleet 승인자) 강제 | 보류. 사용자가 겸임을 허용했다. 제안자≠승인자로 상호 확인을 남긴다 |

## Consequences

학습 결과가 나와도 실물 동작은 바뀌지 않는다. 실행까지 가려면 L1–L3 승인과 G4가 필요하고,
매 실행은 1–2초 lease로 Fleet 생존에 묶인다. 위험 상황은 원인과 함께 Fleet에 남아 API로만 풀린다.

비용은 구현량이다. 확인 요청 항목, 승인·lease API, shadow 실행기가 새로 필요하다. 수집(D-770 G1)은 이 구현을 기다리지 않는다.
이 ADR은 구현·실물 수용·Safety review를 뜻하지 않는다. 현재 학습 정책의 실물 실행은 0회이고 경로도 없다.

## References

- [D-770 수집·학습 완료 기준](D-770-fleet-omx-autonomous-imitation-pipeline.md)
- [D-773 OMX AI 확장 구조](D-773-omx-ai-extension-platform-structure.md)
- [D-785 실물 no-goal owner](D-785-omx-hardware-no-goal-owner-and-fleet-binding.md)
