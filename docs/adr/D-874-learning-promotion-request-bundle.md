## D-874 Learning 승격 요청 묶음 — 확정 정답 평가 근거를 봉인해 넘기고, 승인은 Fleet에 둔다 (D-857 보충)

**Status:** Proposed (2026-10-25). D-857 §1·§4를 보충한다. 로봇 실행·배포·실행 권한은 바꾸지 않는다(D-745, D-793 유지).

### Context

D-857은 Learning의 범위를 「평가 → 승격 기록」까지로 정하고, 승격 평가에는 사람이 확정한 정답만 쓰라고 했다. 「평가·승격」 화면의 「승격 요청」 버튼은 연결되지 않은 채 비활성이었다. 그 사이에 넘길 묶음의 모양과, Learning이 어디까지 써도 되는지가 정해지지 않았다. `build.py --eval-set` 평가셋은 LiDAR·궤적 자동 라벨로 만든다(D-379 d3). D-449 개정에 따라 이것은 승격 증거가 될 수 없다. HF 사진은 학습에만 쓴다(D-857).

### Decision

1. **묶음.** Learning은 `rosy.learning.promotion-request/1` JSON 하나를 만든다. 담는 것은 모델 revision과 파일 sha256, 학습 데이터셋 이름·content_sha와 `external_sources`(HF 장수·비율, `train_only`), 평가셋 content_sha·채점 장수·mIoU·클래스별 IoU, 학습 코드 commit·Python·torch(`learning_cycle.py`가 행에 남긴 경우만, 아니면 `null`), 요청자(서버가 아는 계정, 로컬 모드는 `local-unidentified`), 만든 시각, `state: "requested"`다. `review_evidence.encoded` 바이트의 sha256이 묶음의 이름이다. `<state>/promotion-requests/<sha256>.json`에 create-only로 한 번만 쓰고 덮어쓰지 않는다.
2. **확정 정답만.** 서버가 결과 폴더를 디스크에서 다시 읽어 판단한다. 수용 보고가 `pass`이고, 모델 파일 해시가 맞고, 평가가 학습과 분리(`disjoint: true`)되어 있어야 한다. 평가셋이 content_sha와 일치하고, 평가셋 프레임과 보고의 채점 출처(`source_groups`)가 모두 `human_reviewed_eval`이어야 한다. LiDAR·궤적 자동 라벨, HF 사진, 출처 표시가 없는 사진이 한 장이라도 있으면 거절하고 한국어 이유를 화면에 보인다. 2026-10-25 현재 이 조건을 만족하는 모델은 없을 것으로 본다. 화면은 그 이유를 그대로 보인다.
3. **신뢰 경계.** Learning은 승인을 표시할 수 없다. 묶음의 상태는 `requested` 하나다. 키 이름에 approve·stage·authority·decision·promote·activate·deploy·grant가 들어가면 쓰기 전에 거절한다. PromotionRecord(D-449)의 단계·권한은 Fleet 쪽 기록이다. Learning은 Fleet을 부르지 않는다. 화면은 해시와 「Fleet에서 승인권자가 이 해시로 제안을 만든다(D-793)」만 보인다.
4. **권한.** `POST /api/learning/promotion-requests`는 기존 Learning 쓰기 경로처럼 CSRF 토큰과 `manage` 권한을 요구한다(`authorize_write`의 `/api/learning/` 기본값). `approve`는 정답 승인용이라 쓰지 않는다. 승격 요청은 정답 판정이 아니라 프로젝트 관리 작업이고, Fleet의 승인도 아니다. 본문은 등록된 결과 id 하나뿐이고 서버 경로를 받지 않는다. `GET`은 `view`로 읽기만 한다.

### Not in this decision

- Fleet 쪽 인식 모델 후보 대기열은 만들지 않는다. 지금 Fleet의 정책 제안은 OMX 작업대 전용이다(`operations/fleet/fleet/server/missions/policy_governance_routes.py`, `/api/fleet/workcells/{workcell_id}/policy`). 해시로 제안을 만드는 Fleet 경로는 별도 ADR과 조각에서 정한다.
- `contracts/` 스키마는 바꾸지 않는다. 묶음 스키마는 Learning 모듈 안의 생산자 쪽 형식이다. Fleet이 받기 시작할 때 계약으로 옮긴다.

### Consequences

- 「승격 요청」은 서버가 요청 가능하다고 판단한 후보가 있을 때만 켜진다. 후보마다 거절 이유가 보인다.
- 자동 평가셋(`build.py`)만 있는 차로 모델은 사람이 확정한 평가셋(`review_eval_bootstrap.py --publish`, D-475)으로 수용 평가를 다시 돌리기 전까지 요청할 수 없다.
- 학습 코드 commit은 git 체크아웃에서 돌 때만 남는다. payload 설치본에서는 `null`이다.

### References

D-379, D-449, D-475, D-745, D-793, D-857; `learning/curation/perception/promotion_request.py`, `learning/curation/perception/docs/review-app.md`
