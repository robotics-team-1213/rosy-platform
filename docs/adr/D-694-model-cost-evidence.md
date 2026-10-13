# D-694 모델 비용 근거와 사건 receipt v2

**Status:** Accepted (2026-10-12, 소스 계약). 실제 제공자·계정·호출·현장 활성화는 별도 admission이다.

### Context

포함 요금제의 marginal cash 0과 실제 청구액 미관측(null)은 서로 다른 사실이다.
숫자 비용만 전달하면 gateway의 작업·프로파일·판정 결속, usage와 정책 근거가 사라진다.

### Decision

1. 기존 ModelProfile와 tuple2 제공자 결과는 유지한다. 선택적 frozen CallResult는
   `(judgment, cost_usd)` 두 값으로 unpack되며 CostEvidence를 해당 호출에 고정한다.
2. 비용 상세는 trusted transport metadata에서만 가져온다. 현재 입력 SHA, 정확한
   단일 프로파일 SHA, 검증된 판정 SHA와 job SHA를 provider 경계에서 대조한다.
   Fleet는 모델명으로 분기하지 않는다. 모델 JSON의 비용 필드는 인정하지 않는다.
3. 비용 근거는 basis, marginal_cash_usd, observed_usd_charge, 정책 revision/evidence SHA,
   credential fingerprint, provider opaque request/response ID와 제한된 usage만 보존한다.
   원문 키, account_ref/key_ref, endpoint와 transcript는 저장·export하지 않는다.
   포함계획·로컬무료·제공자 보고 비용을 구별하며 null 청구액을 0 청구로 바꾸지 않는다.
4. 기존 model_receipt/1의 다섯 필드는 그대로 재생한다. CostEvidence가 있는 새
   model_receipt/2에 cost_evidence를 추가한다. parent 전체 프로파일 SHA와 attempt의
   input/generation/role 결속을 유지하고 actual_micros와 marginal cost를 대조한다.
5. 검증된 판정·비용 근거와 숫자 비용을 같은 SQLite completion transaction에 기록한다.
   근거 거절은 원문을 저장하지 않으며 이미 확인된 비용은 REJECTED로 보존한다.
   UNKNOWN 비용은 기존 보수적 예약을 유지한다. 거절된 판단으로 다음 step을 선택하지 않는다.
6. export는 기존 read-only snapshot JOIN과 1MiB 봉투를 사용하고 UNREVIEWED를 유지한다.
   비용 근거 자체는 독립 품질 평가·청구 확인·모델 수용 또는 실행 권한이 아니다.

### Verification

과거 tuple2/receipt 재생, 현재 입력·프로파일·판정·job/비용 불일치, 청구 null 보존,
개인정보 projection 차단, 실제 worker→atomic receipt→export, 근거 거절의 known billing
보존과 step 차단, UNKNOWN 예약 회귀를 원격 시험한다. 실제 네트워크·모델 호출은 하지 않는다.

**Related:** D-681, D-684.
