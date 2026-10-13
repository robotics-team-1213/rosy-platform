## D-585 차선 완주는 학습 모델 도색으로만 센다 — 수용 기준, 장치 학습 도색 기본값, lane_seg 장치 정밀도(int8-hf), 별도 paint 포인터 슬롯

**Status:** Accepted (2026-10-10 기록. 1항 수용 목표는 사용자 결정 2026-10-09 "무조건 우리가 모델을 사용해서 완주하는게 목표"이다. 2–5항은 그 목표를 위해 2026-10-09/10 세션들이 정하고 측정한 것이다. 이 문서는 결정 기록이며, 브랜치 착지·릴리스 반영·로봇 overlay 변경·모델 전달은 각각 사용자 지시로 한다.)

### Context

- **완주가 모델 덕인지 알 수 없었다.** D-408 keep 모드는 학습 마스크가 없거나 오래되면 프레임 단위로 `denoise_fallback`으로 내려간다. 2026-10-09 9dfk 실측에서 `learned_paint_every_n` 2·보정 끔은 학습 마스크를 0/84 프레임에 썼다(D-570 배경). 모델 PC SIM(`docs/sim-model-lap-rosy26`, 아래 「증거」)의 실행 F(62db9403, every_n 2, 보정 끔, 300 ms 지연)는 한 바퀴를 `arrived`로 끝냈지만 learned 프레임이 0/552였다. 이름은 "학습 모델 주행"이지만 실제로는 denoise로 달린 바퀴다.
- **도색 마스크 재사용은 D-570으로 풀렸다.** 9dfk 실기에서 `every_n` 4 + `learned_paint_motion_compensation` true는 정지 상태 228/228 프레임을 `warped`로 썼고, `line_observer` CPU는 128 %에서 110 %로 내려갔다. SIM에서 같은 설정은 모든 모델에서 learned 95–99 %였다.
- **그런데 릴리스 도우미는 아직 옛 값을 쓴다.** `deploy/robot/pinky_pro/release/host_lane_perception.py`의 `LanePerceptionConfig.set("learned")`는 overlay에 `learned_paint_every_n=2`를 쓰고 보정 키를 쓰지 않는다. 운영자가 화면에서 학습 도색을 고르면 0 % 설정이 된다.
- **Pi 5 추론이 느리다.** fp32 lane_seg는 부하 아래 8kcn에서 p50 325–330 ms다. 행을 줄이는 길(D-572 위 잘라 내기)과 해상도를 줄이는 길을 시험했다(아래 「기각·보류」).
- **shadow 슬롯을 두 목적이 같이 썼다.** D-373/D-423의 lane_seg 포인터 `/var/lib/rosy/models/shadow`는 비교용 그림자 모델 자리다. 학습 도색(`learned_lane_pointer`)도 같은 포인터를 가리켜서, 세션 rosy-d1이 8kcn shadow에 v13(D-554)을 두는 동안에는 주행 도색 모델을 따로 바꿀 수 없었다.
- **실기 손실 원인은 모델이 아니었다.** D-578 루프가 9dfk 실기 손실을 분류한 결과는 모두 `pose_off_lane`이었고 `model_miss`는 0이었다. 따라서 수용 기준은 "모델이 도색을 맡았는가"와 "바퀴를 사람 손 없이 마쳤는가"를 따로 재야 한다. 차로를 벗어난 자세의 복구는 Fleet stuck 경로(D-577, 세션 rosy-22 소유)가 맡는다.

### Decision

1. **완주 수용 기준(현장).** 한 바퀴는 다음을 모두 만족할 때만 "모델 주도 완주"로 센다.
   - 로봇마다 전체 코스를 CORE `CAMERA_LINE` keep 모드로 끝낸다. overlay의 `paint_source`는 `learned`다.
   - `line/keep_debug`에서 `paint_source_used == learned`인 프레임(`paint_reuse`가 `fresh` 또는 `warped`)이 keep 프레임의 90 % 이상이다. `unwarped`와 `none`은 학습 프레임으로 세지 않는다.
   - 그 바퀴의 `paint_model_revision`을 기록한다. revision이 바퀴 중간에 바뀌면 그 바퀴는 세지 않는다.
   - 사람 개입이 0회다.
   - 대부분을 `denoise_fallback`이나 threshold로 달린 바퀴는 도착했어도 세지 않는다.
   - SIM에서도 같은 방식으로 센다. `paint_model_revision`이 그 실행의 모델과 같은 프레임만 learned로 센다. SIM 통과는 ROS-SIM 증거이고 장치·현장 수용을 대신하지 않는다.
2. **장치 학습 도색 설정.**
   - `learned_paint_every_n` 2에 `learned_paint_motion_compensation` false인 조합은 장치에 쓰지 않는다(실기 0/84, SIM F 0/552).
   - 학습 도색을 쓰는 로봇의 권장 설정은 `learned_paint_every_n: 4` + `learned_paint_motion_compensation: true`다. D-570의 노드 기본값(보정 끔, every_n 2)은 바꾸지 않는다. 이 조합은 운영 overlay와 릴리스 도우미가 쓴다.
   - 릴리스 도우미 `host_lane_perception.py`의 `set("learned")`가 이 두 값을 쓰게 고친다. 후속 구현이며, 이 ADR 브랜치에서는 별도 커밋으로 넣는다(테스트 `test/test_lane_perception_host.py`). 로봇에 반영되는 것은 다음 payload 릴리스부터다.
3. **lane_seg 장치 정밀도는 int8-hf다.**
   - 방식: 정적 INT8 QDQ, 활성·가중치 s8s8, 가중치는 채널별이다. 첫 Conv와 출력 head Conv는 fp32로 둔다. 이 조합을 `int8-hf`라 부른다. 구현은 브랜치 `feat/lane-int8-hf`의 `learning/training/perception/model/convert.py --int8-fp32-nodes`이다. `object_det`는 기존 u8 텐서별 방식을 그대로 쓴다.
   - 근거: 챔피언 `lane-seg-20261006-62db9403`(fp32)을 변환한 `lane-seg-20261009-3831b20d`는 intake 평가 mIoU 0.8110으로 fp32 0.8109와 같다. Pi 5(8kcn) 부하 아래 p50 196 ms, p95 221–237 ms로 fp32 p50 325–330 ms보다 빠르다.
   - 보정(calibration)은 메모리 상한 안에서만 돌린다. `systemd-run -p MemoryMax=3G`와 `CalibMaxIntermediateOutputs 7`을 쓴다. 상한 없이 돌린 한 번은 모델 PC를 약 1시간 멈추게 했다.
   - revision 규칙(`lane-seg-YYYYMMDD-<ONNX sha8>`)과 intake 게이트는 그대로다. int8-hf 번들도 fp32와 같은 intake·서명·전달 경로를 지난다.
4. **학습 도색은 별도 포인터 슬롯 `paint`를 쓴다.**
   - 경로는 `/var/lib/rosy/models/paint`다. `deliver.py --slot paint`(브랜치 `feat/deliver-paint-slot`)가 쓰고, 운영 overlay의 `learned_lane_pointer`가 이 포인터를 가리킨다. `shadow` 슬롯은 비교용 그림자 모델 자리로 남는다. 세션 rosy-d1과 합의했다(8kcn shadow의 v13 유지).
   - `paint` 슬롯은 `lane_seg`가 아닌 번들과 `v13-drivable` 계열을 거절한다. 도색 소비자는 lane_marking 역할을 읽으며, v13은 drivable 실험 모델이기 때문이다.
   - 첫 push에는 `previous`가 없다. 그때 되돌리기는 `learned_lane_pointer`를 원래 포인터(`/var/lib/rosy/models/shadow`)로 돌려놓는 overlay 변경이다.
   - 로봇 파일 권한은 D-373(`root:rosy-camera 0750`, 쓰기는 운영자 전달만)을 그대로 따른다.
5. **인식만 바꾼다.** 이 결정의 어느 항목도 twist나 `cmd_vel`을 내지 않는다. CORE가 유일한 최종 명령 발행자다.

### 기각·보류

- **위 잘라 내기, 같은 가중치(top-crop):** 정합률 57 %. 모델이 위치 사전지식을 배워서, 잘라 낸 입력의 새 위쪽 가장자리를 벽으로 읽었다.
- **위 잘라 내기 미세 조정(`lane-seg-20261009-7e89953e`):** 같은 행에서는 부모 모델과 맞먹지만 같은 행 채점에서 0.758로 챔피언 0.800보다 낮다. D-572(유효 행만 채점하는 게이트)는 Proposed로 둔다.
- **해상도 줄이기:** drivable IoU 0.12–0.39로 쓸 수 없다.
- **모든 노드 INT8:** drivable이 크게 나빠진다. 그래서 첫 Conv와 head를 fp32로 둔다.
- **NCNN(D-431):** 이 모델에서는 ORT보다 느렸다.
- **ORT XNNPACK:** 로봇 onnxruntime 1.30 빌드에 XNNPACK 실행기가 없다.

### 증거

- **SIM.** 브랜치 `docs/sim-model-lap-rosy26`의 결과 문서(작업 사본 `X:\DevTemp\sim-model-lap\result.md`), ROS-SIM, 모델 PC. 집계는 1항과 같다.
  - learned 비율은 문제가 아니었다. every_n 4 + 보정 켬에서 모든 모델이 95–99 %였다.
  - rosy26 모델은 둘 다 learned 도색으로 한 바퀴를 돌지 못했다. `lane-seg-20261006-28e8454d`는 흰 벽면과 벽 밑단을 도색으로 칠해 오른쪽 경계가 기울고, 가짜 `junction_transverse`가 났다. `lane-seg-20261006-62db9403`은 벽 쪽 오른쪽 차선을 거의 칠하지 못했다.
  - 고치는 일은 브랜치 `fix/learned-paint-floor-gate`에서 진행 중이다. 착지하지 않았다.
- **실기.** 9dfk(D-570 overlay): every_n 2·보정 끔 0/84, 정지 상태 every_n 4·보정 켬 228/228 `warped`, CPU 128 % → 110 %. 8kcn: int8-hf p50 196 ms, p95 221–237 ms.
- **평가.** `lane-seg-20261009-3831b20d` mIoU 0.8110, fp32 챔피언 0.8109. 이 번들의 학습 자료 그룹 표기는 D-586을 따른다.

### Consequences and verification

- 바퀴마다 남길 기록: 로봇, `paint_model_revision`, keep 프레임 수, `paint_reuse` 분포, 학습 프레임 비율, 개입 수와 그 시각. SIM과 현장 기록을 같은 집계 스크립트로 낸다.
- 1항을 만족하지 못한 바퀴는 실패 분석(D-578)으로 보낸다. 원인이 `model_miss`인 프레임만 라벨 후보가 된다. `pose_off_lane`은 D-577 경로의 일이다.
- 2항 도우미 변경은 호스트 테스트로 확인하고, 로봇에는 릴리스로 간다. 지금 로봇의 overlay를 바꾸는 일은 사용자 지시로 한다.
- 3·4항은 각 브랜치의 테스트와 착지 절차를 따른다. 이 ADR만으로 모델을 전달하거나 승격하지 않는다.

**Related:** [D-408](D-408-lane-paint-source-learned-floor-mask-with-opencv-fallback.md), [D-570](D-570-learned-paint-ego-motion-compensated-reuse.md), D-572(모델 유효 행 게이트, Proposed, 미착지), [D-577](D-577-trouble-fleet-rules-and-ai-pc-realtime-situation-facts.md), D-578(차선 실패 분석 루프, 미착지), [D-373](D-373-learned-perception-on-pinky-and-capture-loop.md), [D-423](D-423-camera-object-range-detection-and-model-slots.md), [D-431](D-431-pi-ncnn-models-with-opencv.md), [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-356](D-356-perception-learning-loop-and-model-delivery.md), D-586(학습 자료 capture_group 표기).
