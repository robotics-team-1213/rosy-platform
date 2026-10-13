# 10/7 MCAP 검수 후보의 D-475 격리 가져오기 연습

**판정: 가져오기 PASS, 평가 발행 HOLD.** 사람 승인 정답은 0건이다. 이 실행은 X:의 빈 연습 store와 별도 검수 state에만 썼다. 운영 학습 store, 고정 평가 세트, 로봇 주행 상태는 바꾸지 않았다.

## 입력과 실행

- 코드: local `main` commit `f4448f848d6d8fb93773e05133a8e63a358cdf33`.
- 입력: [10/7 원본 207프레임 출처 증명](../lane-1007-source-proof-2026-10-08/result.md)의 `X:/DevTemp/lane-goal-20261008/1007-proven/verified-inputs.jsonl` (SHA-256 `036c620b8379a9945216b552f2915774941ae7f5377052388489009a126ed5a0`). 두 세션은 124장과 83장이다.
- 클래스: `learning/training/perception/classes/lane_lr6_drivable.yaml` (SHA-256 `5f7b5b82c15bd035b6f097b3699d87e86d6464868346e2ae1a1a09b0131dcc48`). D-475의 보이는 도로면 정의를 쓴다.
- 명령: `python learning/training/perception/dataset/review_eval_bootstrap.py --store X:/DevTemp/d475-1007-rehearsal/store --state X:/DevTemp/d475-1007-rehearsal/state --catalog X:/DevTemp/lane-goal-20261008/1007-proven/verified-inputs.jsonl --classes learning/training/perception/classes/lane_lr6_drivable.yaml --catalog-sha256 <위 입력 SHA-256> --classes-sha256 <위 클래스 SHA-256>`.

가져오기는 `added=207`, `frames=207`을 반환했다. 연습 store의 `eval-reservations/`에는 두 원본 세션 각각의 capture group 예약이 있다. `ReviewStore.list_frames()`로 독립 재확인한 결과 **207건 모두 `pending`**이었다. [원본 갤러리](../lane-1007-source-gallery-2026-10-09/result.md)의 사람 검수 빈칸과 일치한다.

같은 격리 state에 `--ready`를 실행하면 `ValueError: every evaluation frame needs an approved mask`로 거절된다. 이는 의도한 거부이며 고정 평가 세트가 발행되지 않았음을 확인한다. 다음 근거는 사람이 원본의 좌우 물리 경계, 소실·재출현, 보이는 도로면과 255 unknown을 실제로 검수해 승인한 mask다. 이 연습 state의 `pending` 프레임을 학습 정답이나 주행 허가로 쓰지 않는다.
