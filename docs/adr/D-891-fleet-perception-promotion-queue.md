## D-891 Fleet 인식 모델 승격 대기열 — 올린 D-874 묶음을 다시 검사하고 결정만 기록한다 (D-874·D-793 보충)

**Status:** Proposed (2026-10-26). D-874 「Not in this decision」의 Fleet 대기열을 정한다. 레지스트리·배포·실행 권한은 바꾸지 않는다(D-446, D-793 유지).

### Context

D-874는 Learning이 사람 확정 정답 평가를 봉인한 `rosy.learning.promotion-request/1` 묶음(상태 `requested`)을 만들고, 승인은 Fleet에 두라고 했다. D-793은 승인을 사람의 기록으로, 제안자와 승인자를 다른 사람으로 정했다. 그런데 Fleet의 정책 제안 표(`fleet_policy_proposal`)는 `workcell_id`·stage·window·lease를 가진 OMX 작업대 모델이라 인식 모델에 맞지 않는다. Learning→Fleet 인증 채널도 없다(`learning_receiver.py`는 `not_verified`). 묶음 검사기는 Learning 모듈 안에만 있었다.

### Decision

1. **올리고 다시 검사한다.** policy-admin이 묶음 파일의 바이트 그대로를 `POST /api/fleet/perception-promotions?sha256=<hex>`로 올린다. Fleet은 (a) `sha256(raw)`가 주장한 해시와 같은지, (b) `raw == encoded(json.loads(raw))`인지(같은 내용의 다른 인코딩·BOM·이스케이프는 거절), (c) 공유 `validate`를 통과하는지 본다. 본문은 256 KiB까지다. 실제 묶음은 몇 KiB이고 이 한도도 255자 이름의 모델 파일 약 800개를 담는다. 넘으면 읽지 않고 413이다.
2. **공유 검증기.** `SCHEMA`·`FORBIDDEN`·`validate`·`encoded`를 `rosy.contracts.learning.promotion_request`(0.1.14)로 옮긴다. 인코더는 Learning의 `review_evidence.encoded`와 같은 바이트다(비ASCII 유지, 정렬 키, 끝 줄바꿈). `fleet_export.encoded`(ASCII·압축)와 다르다. Learning은 이를 import하므로 묶음 바이트와 해시가 바뀌지 않는다.
3. **결정만 기록한다.** 표 `fleet_perception_proposal(bundle_sha256 PK, bundle, model_revision, proposed_by, proposed_ns, state, decided_by, decided_ns)`를 governance SQLite 파일에 두고 같은 `_run` 트랜잭션을 쓴다. 행이 감사 기록이다. `POST …/{sha}/decision`(`APPROVED`/`REJECTED`)은 policy-admin만, 결정자는 제안자와 항상 달라야 하며(403), 결정은 한 번뿐이다(409). CSRF·역할 확인은 정책 governance 경로와 같다(`require_viewer`의 쿠키 Origin 검사, `permits_site("fleet.policy", {"policy-admin"})`). `GET` 목록·상세는 viewer가 읽는다. 승인은 묶음 sha·모델 revision·파일 sha256을 기록할 뿐이다.

### Trust limits

Fleet은 묶음의 모양, `human_reviewed_eval` 출처, HF `train_only`, 금지 키를 다시 본다. D-874 §2의 디스크 고정(평가셋이 소유 저장소 `evalsets/` 아래에 있음, `review_eval_bootstrap` 공개, 학습 기록 `state.json` 행 결속)은 Fleet이 볼 수 없다. 그 신뢰는 Learning에 남는다. 올린 사람이 policy-admin이라는 것과 결정자가 다른 사람이라는 것이 Fleet이 더하는 보증이다.

### Not in this decision

- 레지스트리 `accepted`·활성 포인터 이동과 `models/accepted` 쓰기.
- 배포(D-446)와 로봇 실행 권한.
- Learning→Fleet 인증 전달 채널. 지금은 사람이 파일을 옮긴다.
- 관제 화면. API만 있다.

### Consequences

- 같은 묶음은 한 번만 대기열에 들어간다(`PROPOSAL_ALREADY_EXISTS`). 거절된 묶음을 다시 올리려면 Learning에서 새 묶음(다른 해시)을 만든다.
- 제안자는 자기 제안을 거절할 수도 없다. 철회는 다른 policy-admin의 `REJECTED`다.
- Fleet 설치본은 `rosy-contracts-learning>=0.1.14`를 요구한다.

### References

D-446, D-449, D-793, D-874; `contracts/learning/src/rosy/contracts/learning/promotion_request.py`, `operations/fleet/fleet/server/missions/perception_promotion.py`
