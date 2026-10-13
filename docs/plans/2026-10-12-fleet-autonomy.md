# Fleet 최소 사람 개입 자율 운영 완성

**Goal:** 승인된 운영 범위 안에서 관측 → law → rule/AI 판단 → 최종 승인 → owner 실행 → 결과 확인 → 재관측·재계획·복구 → 완료를 사람의 반복 승인 없이 연결하고, 원격 검증·독립 리뷰·로컬 main 머지까지 완료한다.

사람 개입은 물리 수리, 명시적 안전 해제, 승인 범위 밖 예외에 제한한다. 자동 해결 불가능은 허위 완료가 아니라 이유와 소유권을 보존한 관측 대기다.

## 범위와 완료 기준

- 자동 stuck: 접수 WAIT/R5는 조건 회복 시 같은 사건을 재평가. 시간·관측 나이 변화만으로 재전송 금지.
- 재시도: 예산·시작 시각·retired/AI cap 유지. UNKNOWN 이동은 관측 전용, 재발행 금지. 실제 사람 점유는 자동 경로 중단.
- 교통/trip: 결정적 검증된 재계획은 최초 site 승인 범위 안에서 자동 적용. await 중 정지/live/hold/route/map/승인 범위 변화는 적용하지 않음. 불명 점유 유지.
- Task/Mission/Cell: 기존 admission·실행 원장·UNKNOWN/no replay 유지. 이번 변경으로 자동 policy gate를 켜지 않음.
- 기타 문제와 advisory: 기존 허용 후보와 근거 검사 유지; human class는 승인 범위 밖 예외. 관측이 복구되면 기존 주기에서 재평가하며 임의 motion 도구를 만들지 않음.
- 관측 데이터: Fleet이 기기 상태/센서값·원본/수신 시간·출처/신선도·사건·명령·결과를 보존. 재조회·내보내기·분석·재생 및 AI 학습 데이터 준비에 활용. 추정·불명·시계 오차는 정상/정답으로 승격하지 않음. 기존 CORE event audit, device recording, 학습 curation/registry 경로를 재사용.
- UI/원장: 자동 대기는 사람 인계·물리 완료로 표시하지 않음.
- 원격 회귀와 known_failures NEW 0, 독립 리뷰, 최신 main 통합과 ff-only 착지.

## 실행 순서

1. 기존 경로·호출자·계약 조사와 RED 회귀: 자동 대기 회복, 소진 유지, UNKNOWN/no replay, 교착 자동 확인/await 경합.
2. 기존 resolver/loop/closed_loop와 trip/traffic owner에 최소 변경, 설정 CLI/app 연결, 원장/UI 의미 유지.
3. 기기 관측 보존·재조회/내보내기와 학습용 원본 lineage 연결, 테스트/보존 범위 확인.
4. 규칙집·D-685·계약·모듈 로그/생성 문서 갱신, 커밋 HEAD 원격 테스트, 독립 리뷰 및 tools/land.py --tests auto.

## 현장 수용

현장 설정은 `fleet.stuck_resolver.autonomous_robots`에 승인된 ID를 명시한다. 기존 resolver credential/AI evidence와 로봇 CORE 계약은 별도 필요 조건이다. 기본 목록은 비어 있으므로 소스 머지가 현장 활성화가 아니다. 실제 설치/센서/시계 정합·두 로봇 교착/정지/복구·미확인 실행 대조와 기록 재생, 학습 데이터 분리 및 독립 평가/승격은 FIELD 증거로 분리한다. 푸시·배포·실제 motion은 이 세션에서 수행하지 않는다.

## 검증 증거

`7c0e4f049` 원격 관련 회귀 238 passed, known_failures NEW 0. Node UI 52 passed. 독립 pipeline_review의 phase/cap/mode/UNKNOWN/시간/학습 원본 경계 리뷰와 Fleet parent 53532 재판정을 반영했다. 마지막 fixture 보강과 최신 main 통합은 tools/land.py의 원격 최종 gate에서 재검증한다. 현장 활성화와 학습 실행 증거는 없다.

자율 대상 설정은 durable Task journal과 백그라운드 stuck resolver가 모두 구성된 경우에만 시작한다. 이동 후보는 owner 호출 전에 기존 원장에 `FLEET_STUCK_DISPATCH_PENDING`을 FULL synchronous로 저장하고, 저장/재대조 실패면 전송하지 않는다. 쓰기 await 뒤 law/AI/사람 점유를 다시 확인한다. 이미 전송을 시작한 pending은 확정 receipt 또는 정확한 CORE 사건 종료를 durable 대조한 뒤에만 해제한다. 강제 프로세스 종료로 receipt 기록이 없어도 재시작에서 pending을 동결하며, 기록 손실을 근거로 재발행하지 않는다. 새 코드들은 Fleet 내부 원장 표식이며 CORE receipt를 위조하지 않는다. 저장 매체 자체의 파손은 별도 현장 장애다.
