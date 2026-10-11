# 공통 개입 필요성 평가: D-652 내부 shadow 검증

착수: `2891e1006`, branch `feat/intervention-assessment`. D-647/D-648의 전체 구조 수용이나 현장 정책 승격 기록이 아니다.

| 책임 | 실제 입력/소비/검증 경로 |
|---|---|
| 도메인 사실 | CORE `StateSnapshot.seq/timestamp`, `line_follow.mode/stuck`; Fleet `state_age_s`, online, pending 사건 ID |
| 공통 필요성 | Situation `assessment.py`: 불변 근거·owner·revision·case, `INTERVENE/DO_NOT_INTERVENE/ABSTAIN`, 이유/정책 revision/유효기간 |
| 현재 상태 변환 | Situation `snapshot_assessment.py`: UTC와 HTTP 수집 지연, CORE/pending ID 충돌 검사; `line-follow-shadow-v1`, age/TTL 3초, 이미 확인된 CORE stuck의 confirm 0초 |
| Fleet 소비 | `LineStuckBoard.observe`의 roster 크기 입력 cache, `intervention_assessment`는 원 관측 시각으로 재평가; resolver·장치 호출은 기존 경로 |
| Situation 소비 | `Situation.step`은 같은 평가를 기존 7일 JSONL에 전이/60초 표본으로 기록; 기존 input log에 정상 분모 포함. facts/proposals로 새 평가를 보내지 않음 |
| 현재 사건 근거 | `ContextDraft.due`와 `_read`는 열린 사건을 기존 3초 TTL 후 재관측; 종료 사건 제거, 다른 CORE 사건·끊김·오래된 state 배제. 0.45/0.35/0.2는 가설 초안 점수 |
| 설치 | Fleet 기존 wheel/sdist holder에 `rosy_situation/__init__.py`, `assessment.py`, `snapshot_assessment.py`만 포함; AI 서비스·analyzers·vision·credential 제외 |

검증 시나리오는 신선 정상/진척, 유효 안전 대기/owner 처리, 확인 전 일시 장애, 지속 장애, 만료/예산/위험/owner 상실, unknown·stale·상충·잘못된 사건/owner/revision·늦은 결과를 포함한다. Fleet 로봇 adapter는 active motion을 진척으로 추측하지 않는다. CORE 복구 단계에 관측 가능한 처리 기한이 없으면 보류하며, ASKING/WAITING_CONSOLE을 정상 대기로 분류하지 않는다. OFF 판정은 line-follow 감시 범위의 비개입이며 Mission 성공이나 전체 장치 안전 판정이 아니다.

문·Arm·다중 로봇·Mission 없는 대상은 같은 순수 계약 시험을 재사용한다. 실제 door/Arm/traffic producer predicate·목표 증거와 domain adapter 구현/독립 수용은 별도 단계다. 기존 3초는 내부 근거 TTL이며 새로운 장치 안전 임계값이 아니다. 모든 권고 재사용에는 현재 입력 전체와 유효기간 대조가 필요하다.

원격 TDD: `a957e74df1`에서 새 계약 36개가 missing assessment로 실패, `0f8475a8c3`에서 소비자/설치 14개가 실패했다. `0926fc4fa5`의 관련 Situation/Fleet API/근거/no-motion 및 wheel/sdist 시험은 AI PC에서 **178 passed**, known_failures **NEW 0**. 이후 추가한 transport 지연/cleared context와 설치 순수성 검사는 최종 착지 시험에 포함한다. 원격 로그는 관리 세션 `2026-10-11--182901--intervention-assessment--417d82`의 `logs/red`, `red-consumers`, `green`에 있다.

후속 증거: 최종 착지 SHA와 원격 terminal receipt. Push/CI, AI PC·현장 PC 설치, 실제 로봇/Arm/문 상황 정확도, 화면 당시/현재 표시, 외부 알림과 모델 토론/학습 승격은 이 변경의 완료 증거에 포함하지 않는다.
