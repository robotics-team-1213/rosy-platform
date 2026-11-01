## D-898 Fleet 인식 모델 승인을 모델 PC 레지스트리에 반영 — 사람이 나르는 서명 결정 파일 (D-891 보충)

**Status:** Proposed (2026-10-27). D-891 「Not in this decision」의 레지스트리 반영을 정한다. 배포·활성화·실행 권한은 바꾸지 않는다(D-446, D-793 유지).

### Context

D-891은 Fleet에 사람의 결정만 남긴다. 모델 PC 레지스트리(`learning/registry/perception/store.py`)에는 그 결정이 닿는 경로가 없다. 모델 PC가 Fleet에서 당기면 모델 PC에 Fleet 자격 증명이 필요하고(Account 토큰은 사람 로그인으로만 나온다), Fleet이 밀 경로도 없다. 한편 `models/accepted/<revision>`은 지금도 "intake 관문 통과"일 뿐 사람 승인이 아니다. HF 등 다른 intake도 accepted와 로봇 shadow까지 간다.

### Decision

1. **서명 결정.** Fleet `GET /api/fleet/perception-promotions/{sha}/decision.signed`(viewer)는 `{"key_id", "decision", "signature"}`를 돌려준다. `decision`은 `rosy.fleet.perception-decision/1` 기록(`bundle_sha256`·`model_revision`·`files`·`proposed_by`·`decided_by`·`decided_ns`·`state`)을 `promotion_request.encoded`로 정본 인코딩한 바이트, `signature`는 그 바이트에 스키마와 key id를 앞에 붙인 메시지의 Ed25519 서명(base64)이다. 인코더·`sign`·`verify`는 `rosy-contracts-learning` 0.1.15 `promotion_request`에 하나만 둔다. 결정 전이면 409, 키가 없거나 잘못 설정되면 503이고 서명 없는 결정은 내보내지 않는다.
2. **새 신뢰 키.** 역할 키 `perception-decision`을 새로 만든다. 다른 역할(모델 코드, 릴리스, Account)의 키를 재사용하지 않는다(`deploy/site/model-code-update.md`). Fleet은 환경 변수 `ROSY_PERCEPTION_DECISION_KEY`가 가리키는 저장소 밖 보호 파일(`{"key_id", "private_key_file"}`, 소유자 전용)에서 개인 키를 읽는다. 모델 PC에는 공개 키와 key id만 둔다. 저장소에는 키가 없다.
3. **모델 PC 반영.** 사람이 서명 파일을 모델 PC로 옮겨 `learning/registry/perception/approval_import.py`를 실행한다. model-watch 실행기와 같은 `<model-code root>/work.lock`을 비차단으로 먼저 잡고(바쁘면 75로 끝, 다음에 다시), 그 잠금 안에서 차례로 확인한다: 고정 key id(`[A-Za-z0-9._-]{1,96}`)와 서명, `state == APPROVED`; 로컬 `<state>/promotion-requests/<sha>.json`의 해시·revision·files; D-874와 같은 `state.json` 행 조회(`promotion_request.ready_rows`)의 결과 폴더가 `--results-root` 안에 있고 모델 파일 집합이 승인 files와 정확히 같음(추가 파일은 거절, 이름은 중복 없는 단순 이름, intake가 쓰는 `model_manifest.json`·`intake_report.json`만 이름으로 제외); `decided_by != proposed_by`. 그다음 승인된 파일(과 위 두 이름)만 inbox에 복사하고, 복사본을 승인 해시와 비교한 뒤(원본이 검사 뒤 바뀌어도 걸러진다) `store.accept`로 `accepted/<revision>`에 넣는다. 같은 파일 집합으로 이미 있으면 accepted는 그대로 두고, 다르면(추가 파일 포함) 거절한다. 결정 바이트와 서명 파일은 `models/approvals/.tmp-<sha>`에 쓴 뒤 `os.replace`로 `models/approvals/<sha>/`(accepted 밖)에 놓는다. `decision.json`이 없는 디렉터리는 중단 흔적으로 보고 없는 것으로 취급한다.
4. **accepted는 승인이 아니다.** 승인 표시는 `models/approvals/<sha>/`뿐이다. accepted 폴더 안에 승인 표시를 넣지 않아 모델 폴더 해시가 바뀌지 않는다.

### Trust limits

- 모델 PC가 믿는 것은 고정 공개 키 하나다. Fleet 개인 키를 가진 사람은 임의 결정을 서명할 수 있다. 키 폐기·교체는 모델 PC의 고정 키를 바꾸는 사람의 작업이다.
- 서명은 Fleet 행을 옮길 뿐이다. 두 사람 규칙은 Fleet 기록(D-891)과 모델 PC의 `decided_by != proposed_by` 재확인 두 곳에서 보지만, 두 principal이 실제 다른 사람인지는 Fleet 계정 관리에 달려 있다.
- 결정에는 만료가 없다. 나중에 Fleet에서 거절해도 이미 반영한 approvals는 지우지 않는다.
- 결과 폴더 검사는 묶음의 모델 파일만 본다. manifest·보고 파일은 accepted로 함께 가지만 승인 해시 대상은 아니다.

### Not in this decision

- 배포·활성 포인터·shadow·로봇(D-446, `rosy_ml promote`). 로봇 활성화가 accepted를 승인으로 읽으면 안 된다.
- 자동 채널. Fleet→모델 PC도 사람이 파일을 옮긴다.
- Learning→Fleet. D-891의 사람 업로드를 유지한다(제안자가 기계 계정이면 D-793 두 사람 규칙이 무너진다).
- 관제 화면. API와 CLI만 있다.

### Consequences

- Fleet과 `rosy-execution-local` 설치본은 `rosy-contracts-learning` 0.1.15를 쓴다.
- 서명은 `cryptography` Ed25519다. Fleet 설치본(`deploy/site/requirements-fleet.txt`)과 모델 코드 venv(`~/rosy-ml/.venv`, 2026-10-27 모델 PC에서 50.0.0 확인)에 이미 있어 새 의존성은 없다. `rosy-contracts-learning`은 `cryptography`를 선언하지 않고 `sign`/`verify` 호출 때 가져온다.
- **배포 전제.** `approval_import.py`는 `cryptography`가 있는 venv(모델 코드 venv)에서 실행한다. 센터 학습 venv(`~/.local/share/rosy-learning-center/venv-cpu`)에 있는지는 확인하지 못했고 이 결정은 거기서 돌리지 않는다. 다른 venv에서 쓰려면 먼저 `cryptography` 설치 여부를 확인한다. 이 결정은 의존성을 추가하지 않는다.
- approval_import는 `rosy_model_code.py exec`로 돌리지 않는다. 실행기가 같은 잠금을 이미 잡아 75로 끝난다.

### References

D-446, D-449, D-793, D-874, D-891; `contracts/learning/src/rosy/contracts/learning/promotion_request.py`, `operations/fleet/fleet/server/missions/perception_promotion.py`, `learning/registry/perception/approval_import.py`
