# AI PC 질의 규약

**상태:** [D-523](../adr/D-523-ai-pc-ask-returns-facts-or-candidates.md) Accepted의 내부 파서. 배포, 현장 활성화, 공개 wire 기록이 아니다. 호스트 경계는 [파이프라인 설계](2026-10-08-decision-model-pipeline-design.md)에 있다.

## 구조

```text
모델 PC                     AI PC                      현장 Fleet                    CORE
학습·평가·고정 프로파일 →  승인된 revision 추론  ←  질의 둘
                            사실 또는 후보      →  검증 후 규칙·admission·사람
                                                                         → 재검사 후 /cmd_vel
```

끝난 에피소드만 모델 PC로 돌아간다. AI PC는 학습하거나 Fleet 원장을 쓰지 않는다.

| 상황 | 누가 푸나 | 이 파서를 부르나 |
| --- | --- | --- |
| 동료 로봇, meet 주문, 막힘 R1 | `fleet.meet`, `stuck_resolver` | 아니오 |
| `obstacle_ahead`이고 동료가 아님 | 지금은 R1–R3과 사람. 정체 사실은 D-492 허용 후 | 호출은 그때. 파서만 지금 있다 |
| `lane_lost`, 앞 거리 없음, 양보 자리 없음 | 기존 규칙 또는 사람 | 아니오. `lane_lost`는 오류 |
| 규칙 표 밖의 과제 제안 | Fleet admission. 자동 dispatch는 꺼짐 | 후보 파서. 아직 현장 클라이언트 없음 |

## 공통

1. 작업 계약이 교체 단위다.
2. 형식, 프로파일, 사건 세대, 시각, 허용 목록 중 하나라도 실패하면 그 응답은 없다.
3. 모델 출력에서 `WAIT` `YIELD` `RESUME` `ABORT` `MANUAL`을 읽지 않는다.
4. 늦은 응답, 다른 세대, CORE 거절은 후보를 무효로 한다. 이 모듈은 그 연결을 아직 하지 않는다.
5. AI PC가 없거나 시간이 지나거나 프로파일이 다르면 기존 규칙과 사람으로 간다.

## 정체

`parse_identity`는 `cause="obstacle_ahead"`만 받는다. 페이로드 키는 `thing`과 `confidence`뿐이다. 신뢰도 0.7 이상, 프레임이 막힘 이후이고 지금보다 미래가 아니며 나이가 8초 이내, 프로파일 ID가 같을 때 `wall` `object` `robot` `person`은 `state=OK`다. 그 밖의 모델 응답은 `thing=unknown`, `state=UNKNOWN`이다. 낮은 신뢰도와 모델이 말한 `unknown`은 측정값만 남기고 이름은 남기지 않는다.

## 후보

`parse_choice`는 `answers.decision.choice`만 읽는다. `criteria`는 Fleet가 만든 2개 이상의 설명 있는 키이고 명령 단어를 포함하지 않는다. 프로파일, 세대, timeout이 맞고 선택이 그 목록 안에 있을 때만 `choice`가 채워진다. 아니면 `choice=None`이다.

## 이번 구현이 아닌 것

공개 REST, `operations/decision` 이동, Laya enable, Qwen 설치, 로봇 동작, `stuck_resolver` 연결, 그림자 원장. 활성화 순서는 파이프라인 설계의 0부터 4까지다.
