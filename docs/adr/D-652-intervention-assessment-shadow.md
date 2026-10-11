## D-652 공통 개입 평가 v1 내부 shadow 계약과 최소 설치 범위

**Status:** Accepted (2026-10-11, 사용자의 바로 처리 요청에 따른 내부 구현 계약). 운영 판단 활성화·장치/현장 수용은 별도이며 D-647/D-648 전체를 수용하는 결정이 아니다.

### 범위와 소유
Situation의 `assessment.py`는 표준 라이브러리만 쓰는 불변 입력/출력과 순수 필요성 평가를 소유한다. `snapshot_assessment.py`는 기존 Fleet 로봇 snapshot을 입력으로 받는 순수 도메인 변환이다. Situation 서비스와 Fleet stuck board는 같은 구현을 shadow로 소비한다. 평가 결과는 장치 요청, 기존 resolver 결정, AI facts/proposals, 외부 API, Mission/Job/claim DB를 변경하지 않는다. CORE/OMX의 writer와 독립 목표 검증은 유지한다.

### 내부 계약
입력은 대상·현재 revision·사건 binding·현재 owner, 출처/참조/관측 시각을 가진 근거 tuple, 도메인이 확인한 condition, 지속 시작/대기 또는 담당 기한, 상충 여부다. 시각은 같은 UTC epoch seconds이며 bool·NaN·Infinity·미래 시각·근거 없는 revision은 유효한 시각/근거로 보지 않는다. 도메인 predicate 자체의 물리 정답은 공통 평가기가 만들어내지 않는다.

출력은 `INTERVENE`, `DO_NOT_INTERVENE`, `ABSTAIN` 필요성 권고, 사유, 입력/정책 revision, 근거 참조, 평가 시각/유효기간이다. 내부 Python/log 계약이며 새 wire enum이나 명령이 아니다. 소비자는 대상·사건·revision·owner·유효기간을 현재 입력과 다시 대조해야 한다. 점수나 모델 합의는 근거 신선도·원인 확정·실제 해소를 대신하지 않는다.

| 조건 | 판정 | 기준 |
|---|---|---|
| 신선한 정상/목표 진척 | DO_NOT_INTERVENE | 실제 도메인 근거와 owner가 있음 |
| 허가된 안전 대기·담당 처리 중 | DO_NOT_INTERVENE | 근거 신선도와 명시한 기한 중 짧은 기간까지만 |
| 현재 근거로 확인한 해소 | DO_NOT_INTERVENE | 현재 상태와 같은 사건 binding; 과거 closed_at만으로 만들지 않음 |
| 일시 막힘 | DO_NOT_INTERVENE | 근거 있는 since와 정책 confirm_s 미만; 확인 경계에서 재평가 |
| 지속 막힘·기한 초과·복구 예산 소진·새 위험·owner 상실 | INTERVENE | 신선하고 사건/대상에 맞는 근거; 실행 요청은 별도 owner 책임 |
| unknown·연결 단절·stale·미래 시각·상충·누락·다른 사건 | ABSTAIN | 정상 비개입과 구별; 재관측/담당 확인 필요 |

정책은 revision, max_age_s, confirm_s, ttl_s를 명시한다. 출력 만료는 정책 TTL, 가장 오래된 근거의 신선도, 대기/담당 기한, 지속 확정 경계의 최솟값이다. 만료 경계는 포함하지 않는다. invalid 설정은 오류이고 미확인 현장 입력은 기권한다.

### 최초 도메인 소비
로봇 adapter의 신선도/출력 TTL 3초는 기존 Situation facts TTL과 맞추며 새 장치 안전 한계가 아니다. CORE가 이미 보고한 stuck은 confirm_s=0으로 재-debounce하지 않는다. state의 seq/timestamp와 Fleet가 제공한 state_age_s를 함께 사용하고 HTTP 수신 뒤 경과를 포함한다. snapshot 수집 완료 시각으로 오래된 state를 새로 만들지 않는다. server-judged evidence가 delayed/disconnected/unavailable이면 fresh로 승격하지 않는다.

현재 CORE stuck id와 별도 pending id가 다르면 상충/기권한다. BACKING·SETTLING·TURNING·CRAWLING은 device owner 처리 중이지만 종료 기한을 관측할 수 없으면 기권한다. ASKING/WAITING_CONSOLE은 현재 막힘이며 정상 신호 대기로 추론하지 않는다. stuck 없음과 mode OFF는 해당 line-follow 감시의 정상 비개입이며 전체 Mission 성공을 뜻하지 않는다. 활성 모드에서 실제 목표 진척이 확인되지 않으면 기권한다. 문/암/다중 로봇의 공통 condition은 동일 함수로 시험하지만 실제 domain adapter 활성화는 해당 producer 계약/검증 뒤에 한다.

### 설치와 기록
Fleet는 `rosy_situation`의 `__init__.py`, `assessment.py`, `snapshot_assessment.py`만 기존 static holder/sdist/wheel로 제공한다. Situation service·analyzers·vision·entrypoint·credential은 포함하지 않는다. 새 서비스·패키지·원장을 만들지 않는다. Situation의 기존 bounded JSONL에 전이와 60초 정상/지속 상태 표본을 남기고 기존 input log를 평가 분모로 사용한다. Fleet의 shadow cache는 현재 roster로 제한한다.

ContextDraft는 사건당 영구 1회 억제 대신 현재 열린 사건의 기존 3초 TTL 뒤 재관측하며, 다른 사건의 state는 현재 근거로 쓰지 않는다. 고정 0.45/0.35/0.2 초안 점수는 그대로 가설 점수로 유지한다.

### 수용과 후속

사용자의 책임 분리 선택(2026-10-11)에 따라 설치 구성은 `tools/packaging/fleet_sources.py`로 분리한다. Fleet `setup.py`는 메타데이터/entrypoint만 선언하고 기존 holder 위치 계산은 `_source_layout.py`에 유지한다. sdist는 빌드 helper의 `_build` 복사본을 포함해 저장소 없이 재빌드하며 wheel runtime에는 helper를 설치하지 않는다. 현장 source image의 Docker COPY/allowlist도 세 평가 파일만 포함한다. 판단·현장 연결·빌드 책임 분리이며 새 서비스나 새 SIZE_UNIT, 크기 임계값 변경은 아니다.

현재 정책 revision도 권고 재사용 조건이다. `Assessment.applies_to`는 소비자가 현재 정책 revision을 반드시 전달하게 하며, 입력 전체가 같아도 정책 revision이 바뀌면 과거 평가 재사용을 거절한다.
단일 암 셀·로봇·다중 로봇·Mission 없는 관측의 정상/막힘/근거 부족, 대기 만료, 상충, 잘못된 case/revision/owner, NaN/bool/미래 시각, 늦은 결과를 fake clock으로 원격 검증한다. 비개입/기권 소비가 신규 command/proposal/problem alert를 만들지 않음을 단언하고 checkout 밖 wheel/sdist 최소 closure를 확인한다. 이 시험은 물리 원인 정확도나 독립 현장 평가가 아니다. D-642~D-646의 현재/과거 UI·원장·알림·독립 평가와 D-648의 dispatcher/workflow 이전은 후속으로 유지한다.
