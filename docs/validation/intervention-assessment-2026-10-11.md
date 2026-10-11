# 공통 개입 필요성 평가: D-652 내부 shadow 검증

원래 폴더 개편 세션은 `5de8e9b2a` 구현을 읽고 D-649 책임·설치 경계 정합성을 ACK했다. 책임표의 Situation/설치 설명을 실제 구현에 맞췄으며 빌드 도구를 manifest root로 등록했다. CORE revision·시각이 없는 legacy `ContextDraft`는 검토용 가설만 유지한다. 공통 평가가 해당 초안의 수집 시각을 CORE의 신선한 동일 사건 근거로 승격하지 않고 `ABSTAIN`하는 조건을 회귀 시험으로 고정한다. ACK는 코드 검토이며 독립 실행·장치 수용 증거가 아니다.

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
| 빌드 책임 | `tools/packaging/fleet_sources.py`가 소스 구성/빌드 명령을 소유하고 Fleet `setup.py`는 메타데이터/entrypoint를 선언. sdist의 `_build` 복사본으로 repository 없이 재빌드; wheel에는 빌드 helper 없음 |
| 현장 source image | Docker COPY/allowlist에 동일한 순수 평가 세 파일만 포함. source-layout fixture에서 실제 `LineStuckBoard` import/보류 호출까지 확인; 실제 Docker build/배포 receipt는 별도 |

검증 시나리오는 신선 정상/진척, 유효 안전 대기/owner 처리, 확인 전 일시 장애, 지속 장애, 만료/예산/위험/owner 상실, unknown·stale·상충·잘못된 사건/owner/revision·늦은 결과를 포함한다. Fleet 로봇 adapter는 active motion을 진척으로 추측하지 않는다. CORE 복구 단계에 관측 가능한 처리 기한이 없으면 보류하며, ASKING/WAITING_CONSOLE을 정상 대기로 분류하지 않는다. OFF 판정은 line-follow 감시 범위의 비개입이며 Mission 성공이나 전체 장치 안전 판정이 아니다.

문·Arm·다중 로봇·Mission 없는 대상은 같은 순수 계약 시험을 재사용한다. 실제 door/Arm/traffic producer predicate·목표 증거와 domain adapter 구현/독립 수용은 별도 단계다. 기존 3초는 내부 근거 TTL이며 새로운 장치 안전 임계값이 아니다. 모든 권고 재사용에는 현재 입력 전체와 유효기간 대조가 필요하다.

원격 TDD: `a957e74df1`에서 새 계약 36개가 missing assessment로 실패, `0f8475a8c3`에서 소비자/설치 14개가 실패했다. `0926fc4fa5`의 관련 Situation/Fleet API/근거/no-motion 및 wheel/sdist 시험은 AI PC에서 **178 passed**, known_failures **NEW 0**. 이후 추가한 transport 지연/cleared context와 설치 순수성 검사는 최종 착지 시험에 포함한다. 원격 로그는 관리 세션 `2026-10-11--182901--intervention-assessment--417d82`의 `logs/red`, `red-consumers`, `green`에 있다.

후속 증거: 최종 착지 SHA와 원격 terminal receipt. Push/CI, AI PC·현장 PC 설치, 실제 로봇/Arm/문 상황 정확도, 화면 당시/현재 표시, 외부 알림과 모델 토론/학습 승격은 이 변경의 완료 증거에 포함하지 않는다.

보완 기록: `2acbc25c4d`의 공통 평가/소비/설치 시험 **51 passed, NEW 0**. `3d771602fb` 통합 검사 **5,094 passed, 217 skipped**이나 Fleet 전체 크기 한 건이 5줄 초과해 착지하지 않았다. 사용자 책임 분리 선택에 따라 설치 코드를 빌드 holder로 분리했으며 임계값/예외/known_failures는 변경하지 않았다. 빌드 holder와 source image 누락은 원격 RED로 각각 2건/1건 확인했고, `027e604fed`의 설치·source image·구조·site candidate 시험은 **57 passed, NEW 0**다. 모두 source/설치 구성 검증이며 물리 판단 정확도나 실제 이미지 빌드의 대체 증거가 아니다.
