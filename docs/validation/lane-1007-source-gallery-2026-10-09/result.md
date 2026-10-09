# 10/7 MCAP 원본 207프레임 연속 검수 후보 묶음

**판정: 후보 분석만, 사람 승인 정답 0건.** [원본 화소 증명](../lane-1007-source-proof-2026-10-08/result.md)의 124장과 83장을 프레임 순서대로 볼 수 있게 묶었다. 모델 마스크·재생 판정·AI가 추정한 경계는 갤러리에 넣지 않았다. 이 묶음은 D-475의 평가 workspace나 학습 입력이 아니다.

## 입력과 재현

- 입력: `X:/DevTemp/lane-goal-20261008/1007-proven/verified-inputs.jsonl` (SHA-256 `036c620b8379a9945216b552f2915774941ae7f5377052388489009a126ed5a0`) 및 그 목록의 원본 JPEG 207장. MCAP bag·metadata·디코딩 화소의 검증 범위는 앞선 [출처 증명](../lane-1007-source-proof-2026-10-08/result.md)을 따른다. 이번 실행은 bag을 다시 열지 않았다.
- 명령: `python docs/validation/lane-1007-source-gallery-2026-10-09/evidence/build.py --source X:/DevTemp/lane-goal-20261008/1007-proven --out X:/DevTemp/lane-1007-source-gallery-20261009`. 스크립트는 입력 목록 SHA, 두 세션의 124/83장 연속 index, 각 JPEG SHA, `source_kind=mcap` 및 고정 평가 세션 중복 표시를 확인했다.
- 산출물은 X:의 위 출력 폴더에만 있다: `candidate-gallery.html`, `candidate-review-queue.csv`, `frames/` 207장, `receipt.json`. 큐 SHA-256은 `396281d115cea785d9c9bb40f856f11742f15737e6848004c2a4d66a9d98ba7c`, 갤러리 SHA-256은 `939b2555d171498998129d81adc17b9e16ea024389f02e5adcaddd2625651ce9`이다. 영상·이미지는 공개 저장소에 넣지 않았다.

## 확인과 다음 판단

별도 확인에서 CSV 207행, 이미지별 SHA-256 일치 207건, HTML 이미지 링크 207개가 맞았다. `same_lane_pair`, 좌우 물리 경계 ID, 소실 원인, 재출현, 보이는 주행영역, 검수자와 시각은 **207행 모두 공란**이다. 원본을 연속으로 보며 한쪽 선 소실·가림·벽·분기 여부를 사람이 기록할 자리를 마련한 것일 뿐, 검수를 대신하지 않는다.

두 세션은 기존 고정 평가 세션과 겹친다. 이 큐를 학습에 넣거나 시험 모델의 출력을 평가 정답 초안으로 붙이지 않는다. 사람의 독립 검수와 D-475의 평가 세션 예약·workspace 승인·출처 검증·고정 평가 발행이 끝나기 전에는 IoU, 동일 경계 연속 miss/flicker, 주행 허가를 주장하지 않는다. 불확실한 경계는 STOP, 최종 `/cmd_vel`은 CORE 단일 발행으로 유지한다.
