# fleet_decision verification log

2026-10-12: source 8036d90c09 independently reviewed without blockers; remote integration 210 passed, NEW0. Frozen evaluation profile revisions and globally unique recording IDs close final review defects. Fleet52019/Decision231 independently measured; source/installed contract only. See docs/validation/decision-deliberation-2026-10-12/result.md.

2026-10-12: D-640 bounded advisory supervisor/CLI translator, Fleet durable journal and existing offline comparison tool implemented. Source 150c3e0f3d: remote fake/installed scope 43 passed, NEW0. Live provider, deployment and independent FIELD remain HOLD; see docs/plans/2026-10-12-decision-deliberation-boundary.md.

2026-10-11: D-637 folder move in progress; committed-SHA verification pending.

2026-10-11: source d4988bffba landed on local main after independent review, remote regressions/known_failures 0 NEW and installed wheel/sdist/HTTP proof. SOURCE/LOCAL GO only; CI FULL and ROS-SIM/ARM64/device/field remain unverified. See docs/validation/d637-remaining-folders-2026-10-11/result.md.

## 2026-10-12 · 4c47e3823e · D-679/D-681 조건부 검토와 모델 주도 종결 목표

- 변경: 동일 사건의 Fleet 기준과 Qwen 의견 불일치를 제한된 GLM 검토로 연결하고 기존 정책과 cached 결과 교차 사용을 거부한다. 설치·실행 경계를 분리하고 모델 교체·확률 보정·자동 처리·최종 사람 인수·개선의 통합 목표를 기록했다.
- 증거: 원격 통합 146 passed, exit 0, NEW 0; 마지막 통합 실행은 자원 하한 fallback 경고가 있어 성능 증거로 쓰지 않는다. docs/validation/deliberation-host-admission-2026-10-12/conditional-review.md.
- gate 변화: SOURCE/원격 논리만 확인했다. 실제 Fleet 기준 선택 생산자·격리 SDK/모델 호출·독립 보정·자동 처리·배포·현장 수용은 미확인이다. Discord는 담당 세션 작업이다.

## 2026-10-12 · 8709923045 · verify: GLM 응답 모델 결속과 독립 검토

- 변경: upstream 모델 ID와 assistant 역할이 고정 요청과 다르면 결과 재작성 전에 거부한다.
- 증거: 새 3개 RED 확인 후 통합 149 passed, exit 0, NEW 0; opencode_admission 독립 검토에서 blocker 해소. model-binding-green/run-1.txt. 자원 하한 fallback 경고는 유지되므로 운영 성능 증거가 아니다.
- gate 변화: SOURCE/원격 검증만 확인. 실제 호출·영속 사용 표식·배포·자동 처리·독립 보정·현장 수용은 미확인 유지.

## 2026-10-12 · 79febfdbe2 · D-681/D-684 판정 계약과 사건 관측 경계

- 변경: v2 프로파일·판정 JSON·공통 요청·CLI/로컬 어댑터·독립 보정을 구현하고 모델 프로파일 전체 SHA에 보정을 고정했다. GLM 첫 호출의 영속 표식과 Pinky 전용 읽기/지속 예산 계약을 추가했다. 로컬 실행은 기본 미수용이다.
- 증거: 통합 239 passed와 wheel/sdist·로컬 회귀 34 passed, exit 0, NEW 0. 두 실행은 자원 하한 fallback이며 지연·용량 수용이 아니다. 여유 호스트 component 145/82/94 passed는 범위 중복으로 합산하지 않는다. versioned-judgment.md에 근거를 기록했다.
- 검토: v2 판정·CLI의 독립 검토에서 중요 blocker 없음. 로컬 격리 표식 blocker를 수정했으며 최종 통합 검사를 수행한다.
- gate 변화: SOURCE/원격 논리·설치 패키지 증거. 실제 SDK/GLM·Qwen v2·독립 현장 보정·운영 루프·배포·현장 수용은 미확인이다. Discord 설정은 담당 세션 작업이다.

## 2026-10-12 · 5941920df7 · D-720 읽기 전용 status 도메인
- 변경: fleet_status/READ_ONLY_QUERY, channel READ_ONLY schema, 고정 status profile·source-bound calibration-exempt factual-display 정책을 추가했다. 기존3domain payload/digest는 유지한다.
- 증거: status68, codecs/launcher111 원격 선택 GREEN, NEW0; source review 승인. 모델 ready 자체는 admission 증거가 아니다.
- gate 변화: source 계약. 일반 사건 calibration과 실제 보호 GLM cost/host/admission·독립 정답 수용은 유지한다.

## 2026-10-12 · 1164d858e · D-728 independent natural conversation proposals

- 변경: Added pure `rosy.decision.conversation` profile/input/flat semantic-step codec, explicitly installed by the existing Fleet distribution. Model output maps only to existing validated `core_common.intent` grammar. No Fleet writer, network, credential or activation exists in this holder. D-720 status-only calibration exemption cannot admit this profile.
- 증거: Independent structure precheck256 physical lines; source/installed/architecture remote checks71/129/38 passed with0 NEW.
- gate 변화: Actual synthetic Qwen semantic conformance has three unresolved cases, so admission remains OFF. Fleet retains current authority, durable attempts and grounded replies; CORE retains final motion authority.

## 2026-10-12 · a5925d7ae · D-728 후속 대화 입력

- 변경: 제안 이력과 별도로 같은 사용자·채널의 완료 실행 문맥을 입력에 결속한다. CHAT 응답은 대화 자료로만 보관하며 실행 권한이 아니다.
- 증거: 원격 집중 시험 284개와 공개 CORE epoch CAS 2개 통과, NEW0. 실제 모델 38개 평가와 보호 설치는 별도 대기다.
- gate 변화: 없음. 이전 31개 평가를 새 입력·소스의 수용 증거로 재사용하지 않는다.

## 2026-10-20 · uncommitted · Console 조회 대화 계약

- 변경: Discord v1과 구별되는 OperatorScope/Input/Profile/Answer와 근거 참조 검증을 추가했다. 모델은 분류·참조만 내고 공개 응답은 Fleet가 사실 또는 고정 안내문으로 구성한다.
- 증거: dab629c171의 집중 회귀 167개에 새 계약·provider 검증과 기존 대화 회귀를 포함했다. 가짜 provider 검증이며 실제 모델 정확도 증거가 아니다.
- gate 변화: 없음. 독립 모델-PC 의미 평가·승격과 보호 설치는 대기다.

## 2026-10-20 · b1f18674b2 · D-821 한국어·영어 의미 평가와 읽을 수 있는 입력

- 변경: 웹 모델 profile revision과 locale을 구분하고 두 언어의 부정·인용·안전·사생활 사례를 평가했다. 모델 설명문은 고정 값으로 제한하며 Discord처럼 최신 원문을 읽을 수 있게 전달한다.
- 증거: 실제 고정 Qwen 모델에서 CHAT 사실 주장이 거부되었고, 10/19·15/19 실패를 보존한 뒤 원문 전달 보완으로 19/19 통과했다. 큰 source inventory는 추론 패킷 제한과 별개인 기존 배포 해시 함수로 검증했다.
- gate 변화: 없음. 고정 사례 통과는 일반 언어 성능·운영 승격·장치 수용을 뜻하지 않는다.

## 2026-10-21 · d7fedbc9ab · D-831 관제 입력 전처리와 제안 경계

- 변경: 공통 Decision 정규화·등록 이름 해소·충돌/부정/조건/복합 후보 차단, Console/Discord 새 profile, broker 실제 사용량과 Fleet digest 검사·개인정보 없는 로그를 연결했다. 새 Discord profile은 자동 실행 worker를 설치하지 않는다.
- 증거: source 8454618b94 원격 전처리/보호 설치 123 passed; NFD+등록 이름 공백 회귀 RED1/36 뒤 d7fedbc9ab GREEN37. 독립 계약 검토의 이름 공백/장소-only STATUS 지적을 수정했다. 실제 모델 전후와 최종 영향 검증은 docs/validation/operator-preprocessing-2026-10-21/result.md에 기록한다.
- gate: 기존 SOURCE/LOCAL 경계만 다룬다. 새 확인 API·보호 설치·실음성·장치/현장 수용은 미실행. source 통과를 운영 활성화로 표시하지 않는다.

## 2026-10-21 · 5d90c8d670 · D-831 인용·Unicode 검색 경계 보완

- 변경: 원문과 모델용 인용문은 보존하고 검색 사본만 NFC/공백 정규화한다. 유의미한 공백의 등록 이름이 있으면 입력 사본 정규화를 생략해 혼합 조합형도 보존한다.
- 증거: 추가 RED5/37 및 RED1/42 후 GREEN43, 독립 계약 재검토 지적 해결. 실제 고정 모델 비교군19/19·Console26/26·Discord46/46, 입력 토큰 절감 없음. docs/validation/operator-preprocessing-2026-10-21b/result.md.
- gate: 보호 설치·실음성·장치/현장 수용·새 자연어 확인 API는 미실행. 새 Discord 자동 실행은 OFF.

## 2026-10-21 · uncommitted · 관제 AI 전처리의 공개 원격 분리

- 변경: 기존 로컬 D-831 구현의 원문 보존·Unicode/별칭 충돌·부정/인용/복합 명령·참조 검증과 실제 사용량 계약을 추출했다. Console과 새 Discord profile에서 사용하고 실행 권한은 Fleet/CORE에 둔다.
- 증거: 원본과 추출본의 새 모듈 바이트를 비교하며 새 게시 SHA에서 동일 ko/en 모델 suite를 다시 실행한다. 이번 적용 자체는 새 평가 receipt가 아니다.
- gate 변화: 없음. 입력 토큰 절감 효과를 주장하지 않으며 자연어 확인 API는 별도다.

## 2026-10-27 · 398b533c38 · RejectedJudgment 공개 이름 전환

- 변경: fleet 자동화 worker가 `rosy.decision.billing`의 `_RejectedJudgment`를 분포 경계 너머 import·타입 검사하므로, 이름을 공개 `RejectedJudgment`로 바꾸고 패키지 안 provider 3곳·fleet worker(엄격 타입 검사 포함)·회귀 시험을 같은 커밋에 갱신했다. 순수 이름 변경이라 행동 변이 프로브는 해당 없음(누락 위치는 import 즉시 red).
- 증거: 원격 5 suite(known-cost·deliberation 3종·installed wheel 검사) green, known NEW 0.
- gate 변화: 없음. 거절 증거의 검증 규칙·엄격 타입 검사·설치 경계는 불변.

## 2026-10-29 · 587c0b4c8c · 판단 난항의 조건부 독립 모델 협력

- 변경: D-913 역할별 context, 측정·workload에 결속된 순차/병렬/auto 선택, 비용 예약·호출 중단·재사용과 후보 원장 policy/configuration fence를 구현했다. 기존 의존 검토·v2 사건 처리·장치 실행 권한은 유지한다.
- 증거: 독립 소스 검토와 원격 핵심 회귀·설치 wheel/sdist 통과, NEW0. 여섯 정책의 동일 사건 비교 도구도 원격 검증했다. 상세: `docs/validation/conditional-model-cooperation-2026-10-29/result.md`.
- gate 변화: SOURCE/LOCAL 근거 갱신. 실제 provider·GPU admission·독립 모델 품질·실물/현장 수용은 미검증이며 운영 활성화는 HOLD다.
