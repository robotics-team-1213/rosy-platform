# 10/7 차선 검수 후보의 MCAP 화소 출처 증명

증거 등급: **로컬 원본 바이트 검증**. 사람 차선 정답, 평가 세트 발행, 주행 수용은 아니다.

- 코드: `7ddf999f1` (`main`). 입력은 X:에 복구된 원본 `20261007T143038Z_rosy_60`, `20261007T143211Z_rosy_60`의 MCAP과 영상 sidecar다. 원본 bag SHA-256은 각각 `0d8b19042429368c12c8a76349873c7d83fc7dfafe62ee4a97ffbc87bd4b7f76`, `287015247472833f8eae7c17e81cb33bd27c19fddc841d559804b10591c2d920`이다.
- `python X:/DevTemp/lane-goal-20261008/prove_1007.py`로 압축 카메라 메시지의 JPEG bytes를 그대로 X:에 추출하고, sidecar의 `(topic, log_ns, header stamp)`로 고른 프레임을 `mcap_proof.prove_frames`에 다시 넣었다. 이 함수는 bag의 같은 캡처 바이트에서 해시와 디코딩 화소를 검사한다. 첫 세션 **124/124**, 둘째 **83/83**, 합계 **207/207**이 증명됐다.
- 결과는 `X:/DevTemp/lane-goal-20261008/1007-proven/`에 있다. `verified-inputs.jsonl` SHA-256은 `036c620b8379a9945216b552f2915774941ae7f5377052388489009a126ed5a0`; 두 `proof.json` SHA-256은 순서대로 `983e4b89c9779d55d5b75dfe7725cf9d282397bbbcdef046e67ed9fc8f010ac4`, `bbb0bb6a5666c2bbe200cff24101ea0a4765c50931388741bae4c0eaed286b1c`이다. 목록의 `capture_group`은 세션명으로 선언한 값이며, 영상 화소 검증이 그룹 의미까지 증명하지는 않는다.

검수 대상으로는 [10/6–10/7 후보 목록](../../plans/2026-10-08-lane-papers-contract-fit.md)을 사용한다. 목록의 `both`, `ONE`, `STOP`은 검출기 출력이고 같은 물리 차선의 정답은 아니다. 207장에는 아직 사람의 경계 ID·동일 차로 여부·가림/시야 이탈/분기 원인 검수가 없다. 이 목록을 실제 고정 평가로 사용하려면 D-475의 평가 세션 예약, 검수 작업공간의 확정 class binding, 사람 승인, `human_reviewed_eval` 빌더와 MCAP companion 검증이 더 필요하다. 현재 운영 주행은 **HOLD**다.
