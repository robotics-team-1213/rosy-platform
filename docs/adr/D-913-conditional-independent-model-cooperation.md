## D-913 판단 난항의 독립 모델 협력과 환경별 순차·병렬 선택

**Status:** Accepted (2026-10-29). 사용자가 후보 전용 소스 구현을 지시했다. 실제 provider·GPU admission·독립 품질·현장 수용은 별도이며 운영 활성화는 승인하지 않는다.

### Context

사용자는 정상 처리보다 판단이 어려운 사건에서 모델이 협력하고, 환경에 따라 순차/병렬을 선택하기를 원한다. 기존 D-679는 선행 의견을 검토하는 조건부 재평가다. 독립 의견의 실행 순서를 변경하는 새 정책을 그 경로와 구분한다.

### Decision

- 정책 ID는 `conditional-cooperation-v1`, 실행 mode는 `auto`, `sequential`, `parallel`이다. 기본 운영 연결은 비활성이다. 기존 D-679 동작과 v2 Judgment/복구 worker는 변경하지 않는다.
- 첫 범위는 기존 `run_line_judgment`의 blocked `line_follow`와 `reobserve`/`human` 후보다. 정상은 0회 호출한다. 위험 반론은 협력으로 해제하지 않는다. 근거 부족/충돌은 독립 재투표로 없애지 않고 재관측·기존 의존 검토·사람 경로에 남긴다.
- 원래 근거에 결속된 Fleet 기준과 유효한 1차 의견이 다른 경우, `proposal`/`critique` 두 역할을 같은 immutable Problem으로 독립 검토한다. 순차에서도 앞 답변을 뒤 모델에 주지 않는다. 제공하지 않은 영상·센서 사실을 추측하지 않도록 입력과 출력을 제한한다.
- 역할 요청은 고정 model/profile/adapter/prompt revision, request hash, 안정적인 call ID에 결속한다. 재사용은 같은 입력·역할·revision·내용·확인된 비용일 때만 허용한다.
- auto는 승인된 profile 쌍·호스트/device/workload의 실제 순차/동시 부하 측정과 신선한 trusted admission을 사용한다. 동시 예약 가능 여부만으로 병렬을 선호하지 않는다. 동률·미미한 이득은 순차이고, 어느 방식도 기한·비용에 맞지 않으면 HOLD다. 명시 parallel도 자원 관문을 우회하지 않는다.
- 새 일반 스케줄러나 모델 PC의 운영 fallback을 만들지 않는다. 호스트 자원 예약은 trusted 주입 port이며 실제 adapter가 입증되기 전 배포하지 않는다. 시험 배치 여유나 SIM 상한을 운영 추론 admission으로 전용하지 않는다.
- Fleet의 기존 후보 원장은 사건당 하나의 실행을 claim하고 정책/설정 변경 재사용을 거부한다. 먼저 비용 상한과 호출 식별자를 기록하고 dispatch한다. 중단된 행은 UNKNOWN/HOLD이며 자동 재호출하지 않는다. 같은 사건의 새 generation으로 예산을 다시 만들지 않는 기존 fence를 유지한다.
- 취소·자원 반환에도 유한한 대기 시간을 적용한다. 종료 불명은 자원을 반환했다고 주장하지 않고 비용 불명은 미사용 예산으로 환급하지 않는다. 미dispatch 상태에서만 auto의 병렬 예약 거부 후 순차 재평가를 한 번 허용한다.
- 후보는 두 유효 의견이 반론 없이 일치할 때만 생성하며 `action_admissible=False`다. Fleet admission/원장과 CORE·OMX 최종 writer 경계는 D-656을 따른다.
- 평가 도구는 규칙·단일 모델·기존 의존 검토·독립 순차·독립 병렬·auto를 같은 독립 사건 세트로 비교한다. source 계약, 모델 품질, 호스트 공존, 실물 수용을 따로 보고한다.

### Consequences

후보 전용 소스와 fake provider/admission 회귀를 먼저 검증한다. 실제 호스트 admission과 환경별 측정이 없으면 auto/parallel을 활성화하지 않는다. 고정 순차 → 고정 병렬 → auto 순서로 독립 평가·shadow 수용을 진행한다. 지연·비용·위험 누락·불필요 개입과 실제 readback을 함께 확인한다. 모델 일치는 정답이나 실제 성공이 아니다.
