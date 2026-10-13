# 10/7 원본에 합성 굽이 문맥을 준 후보 스트레스 재생

**판정: 활성화 HOLD.** 이 실행은 B9가 주행 판단을 바꾸는 프레임을 찾는 후보 분석이다. 실제 Fleet 지시, 승인된 물리 경계 정답, 로봇 주행의 증거가 아니다.

## 입력과 재현

- 코드: 로컬 `main` `73a4e7e05b9401b85ef2e4e8be5e49c4f68d84c0`의 `LaneKeeper`; 재생 스크립트 [`evidence/replay.py`](evidence/replay.py), SHA-256 `b31eeb1ed4e452c34ff880e387024105d77292340a4793bd28f68692c7a100f2`.
- 입력: [출처가 증명된 10/7 MCAP 207프레임](../lane-1007-source-proof-2026-10-08/result.md)의 `X:/DevTemp/lane-goal-20261008/1007-proven/verified-inputs.jsonl`, SHA-256 `036c620b8379a9945216b552f2915774941ae7f5377052388489009a126ed5a0`. 스크립트가 124/83 연속 순서와 각 JPEG SHA를 다시 검사했다.
- 실행: `python docs/validation/route-context-1007-stress-2026-10-09/evidence/replay.py --catalog X:/DevTemp/lane-goal-20261008/1007-proven/verified-inputs.jsonl --out X:/DevTemp/route-context-keeper/replay_1007_verified.json`.
- 출력 SHA-256: `e7285388b35e4dfbcd9b46683bcc0611fbde6860a9dde68cd90f0e8c8fa72388`.
- 음성 확인: 첫 이미지의 catalog SHA를 바꾼 복사본은 `ValueError: source image digest mismatch`로 거절됐다. 원본 파일과 출력은 바꾸지 않았다.

## 관찰

두 번의 keeper를 같은 영상에 독립 실행했다. 하나는 기본 규칙, 다른 하나는 **모든 프레임에 합성 `bend_expected=True`**를 주었다. 실제 D-531 문맥처럼 위치와 기대 창을 제한하지 않은 과잉 입력이므로 허가 시험이 아닌 스트레스 시험이다. `11.8°`는 당시 장치의 승인 보정값이 아닌 후보 투영이다.

| 원본 세션 | 투영 | HOLD→주행 | 주행→HOLD | 주행 목표 1 cm 초과 변화 |
|---|---|---:|---:|---:|
| 143038 (124장) | 공칭 | 1 (`000039.jpg`) | 0 | 14 |
| 143211 (83장) | 공칭 | 1 (`000067.jpg`) | 1 | 25 |
| 143038 (124장) | 11.8° 후보 | 0 | 0 | 0 |
| 143211 (83장) | 11.8° 후보 | 1 (`000059.jpg`) | 0 | 39 |

세 HOLD→주행 프레임에는 원형 선·횡단 표식·분기 후보가 함께 보인다. 이는 AI 후보 판독이며 D-475 사람 승인 정답이 아니다. 물리 경계 ID, 촬영 당시 카메라 보정, 실제 Fleet 장소·창, 지도 자세가 확인되지 않았으므로 이 세 프레임을 안전한 주행으로 승인하지 않는다. [P2 SOURCE 점검](../route-context-keeper-2026-10-09/result.md)의 실물 434프레임 시험도 여전히 건너뛰었다. `route_context_enabled=false`를 유지하고, 다음에는 실제 지시 시각·지도 버전과 사람 검수 경계를 맞춘 재생에서 HOLD→주행 및 차로 이탈을 판정한다.
