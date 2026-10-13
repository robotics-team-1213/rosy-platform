# 10/6 차선·주행영역 원본 후보 검토 묶음 (2026-10-08)

**판정: 후보 진단만, 사람 승인 정답 0건.** [전체 3,129프레임의 모델 출력 진단](../drivable-smoke-1006-full-2026-10-08c/result.md)에서 확인할 장면을 골랐고, 검토 화면에는 원본 MP4 프레임만 넣었다. D-475의 고정 평가 세트나 주행 허가 근거가 아니다.

## 산출물과 재현

- X: `DevTemp/rosy-lane-1006-review-candidates-20261008/`에 `candidate-gallery.html`, `candidate-review-queue.csv`, `frames/` 178장, `receipt.json`이 있다. [생성 스크립트](evidence/build_candidates.py)는 두 MP4·sidecar의 SHA-256, 프레임 수·순서·stamp를 확인하고 지정한 연속 구간의 RGB 프레임을 추출한다. [영수증](evidence/receipt.json)은 후보 개수와 산출물 해시를 고정한다.
- 긴 `082612Z` 영상 2,487장 중 103장: 188–211, 876–892, 2118–2140, 2448–2463, 2464–2486. 짧은 `091340Z` 영상 642장 중 75장: 180–202, 387–410, 440–450, 625–641. 각 구간은 연속 프레임이므로 경계 소실 전후를 볼 수 있다.
- 영상 SHA-256: 긴 영상 `e6c3785b4cbc0cbd8f81ce4b09b1202ec4c15792981ee803628becef5949dd13`, 짧은 영상 `cb4eb6d39c24a6a0cc4ad5adee615b0e21ef2ef781f6b8d68aa89fe9fff3c491`. 원본 MCAP과 변환 계보는 X: `DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings/`의 `source-readback-1006.json`, `conversion-readback-1006.json`에 있다.
- 큐 SHA-256: `a297fd4777a8042c24ddfc70ddb9173a14d3d9ed15631342299aa748060c3372`. 갤러리 SHA-256: `7fb268d60be7f855ab93a7a8b64347f38761d935d17cda33102b02f17e20dc1d`.

## 확인 결과와 사용 범위

독립 확인에서 CSV 178행, PNG 178장, 이미지별 해시 178건 일치, stamp 순서 역전 0건, HTML 이미지 링크 178건을 확인했다. `same_lane_pair`, 좌우 물리 경계 ID, 소실 원인, 재출현, 보이는 주행영역, 검수자 및 시각은 모두 공란이다. 검토자가 연속 화면의 같은 물리 경계인지와 가림·과노출·벽·분기 여부를 직접 판독할 수 있도록 둔 칸이다.

일부 구간은 앞선 시험 모델의 이상 출력을 보고 선택했다. 따라서 선택 편향이 있으며, 원본 화면만 보여 주더라도 이 큐를 D-475의 모델 출력과 독립인 고정 평가 초안으로 승격할 수 없다. 프레임은 검증된 MCAP을 MP4로 변환한 파생 화면이므로 원본 MCAP 화소와 동일하다고 주장하지 않는다. 사람 승인 마스크·경계 ID·벽 음성·연속 소실 정답이 없어서 IoU, `R_F/R_M`, 한쪽 선 소실 복원률, 주행 성공률을 계산하지 않았다. 모델 면적이나 이 큐로 STOP을 해제하지 않는다.
