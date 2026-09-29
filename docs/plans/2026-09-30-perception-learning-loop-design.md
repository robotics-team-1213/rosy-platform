# 인식 학습 루프 — 수집에서 반영까지 한 바퀴 (설계)

**날짜:** 2026-09-30 · **ADR:** [D-356](../adr/D-356-perception-learning-loop-and-model-delivery.md) · **잇는 결정:** D-199, D-205, D-209, D-137, D-186, D-290

## 목적

외부(Colab·GPU PC)에서 학습한 차선 분할 모델을 로봇에 실어 추론하고, 로봇이 모은 데이터가
다시 학습으로 가는 루프를 만든다. 학습 자체는 이 저장소 밖이다. 이 저장소는 **수집 · 데이터셋 ·
학습과의 약속 · 모델 접수와 검증 · 전달 · 로봇 추론**을 맡는다.

첫 바퀴는 얇게 돈다. 모든 단계를 최소 구현으로 한 번 통과시키고, 각 단계는 다음 바퀴에서 키운다.

## 출발점: `0930_best_model.torchscript.pt`

| 항목 | 값 |
|---|---|
| 구조 | `LaneUNet` — 4단 U-Net, 기본 16채널, 파라미터 약 1.9M |
| 입력 | `1×3×240×320` (trace 입력). 실물 카메라 320×240 @ 8 fps와 같다 |
| 출력 | `1×4×240×320` 클래스 logit |
| 연산 | 프레임당 약 4 GMAC (구조에서 계산, 실측 아님) |
| 형식 | trace TorchScript (저장 포맷 3) |

클래스 4개의 의미, 정규화, 채널 순서는 파일에 없다. 학습 노트북에서 가져와 manifest에 적는다.
그 전에는 이 모델을 접수하지 않는다.

## 구조

```
[로봇 Pi 5]                         [사이트 PC / 개발 PC]                  [외부: HF Hub + Colab/GPU]
 camera ─► learned_lane (ONNX, 섀도) ─► perception/learned/shadow (JSON, 소비자 없음)
   │         line_observer(rule) ─► line/observation ─► CORE (유일한 /cmd_vel)
   └► recorder (rosbag2 MCAP)
        /var/lib/rosy/recordings ──► harvest ──► dataset (extract·prelabel·build) ──publish──► HF dataset@commit
                                                                                              │ 학습(외부)
 /var/lib/rosy/models/<rev> ◄── deliver ◄── intake (manifest·해시·ONNX·재생 보고) ◄──pull── HF model@commit
```

경계:

- 모델은 마스크에서 뽑은 **증거**만 낸다. 조향은 기존 `line/observation` → `LineFollowManager`
  경로다. 모델은 `cmd_vel`을 내지 않는다(D-2, D-209).
- 로봇은 인터넷에 붙지 않는다. HF 토큰은 사이트 PC와 학습 환경에만 있다.
- 모든 모델은 `model_revision`과 파일별 sha256으로 식별한다. 모르는 revision, 해시 불일치,
  입력 계약 불일치면 로드를 거부한다(fail-closed).
- 이번 바퀴에서 로봇의 학습 모델은 **섀도 전용**이다. 결과를 발행하지만 제어가 읽지 않는다.
  주행 경로로 쓰는 활성화는 D-205 P3 재생 게이트 합격 뒤 별도 결정이다.

## 코드 자리 (D-209)

| 무엇 | 어디 |
|---|---|
| ROS-free 모델 계약·로더·후처리 | `src/runtime/sensing/control/sensing/perception/learned/` |
| 섀도 노드 | `src/runtime/sensing/control/learned_lane_node.py` |
| 기록 launch/설정 | sensing 패키지의 launch·config (기존 관례를 따른다) |
| 데이터셋 도구 | `tools/perception/dataset/` |
| 모델 도구(변환·접수·전달) | `tools/perception/model/` |
| 학습 약속 문서와 템플릿 | `tools/perception/training/` |
| 산출물 | `data/perception/` (커밋 안 함). 가중치는 `src/`에 두지 않는다 |

## 1. Recorder (로봇)

- `ros2 bag record`를 감싼 launch. 새 노드를 쓰지 않는다.
  - MCAP, `--storage-preset-profile zstd_fast`, `--max-bag-duration 30`.
  - 토픽: 압축 카메라 JPEG, `cmd_vel`, `line/observation`, `perception/learned/shadow`, `odom`.
    raw `Image`는 기록하지 않는다.
- 모드: **session**(운영자 시작·종료). snapshot 모드와 불일치 트리거는 다음 바퀴.
- 세션 폴더 `/var/lib/rosy/recordings/<session>/`에 `session.json`을 쓴다(D-290 필수 항목):
  device, CameraProfile revision, 섀도 모델 revision, task ID, 사유, 시작·종료 시각.
- 할당량 4 GiB(설정). 넘으면 수거 완료(`harvested` 표시) 세션부터 지운다. 수거 전 세션은
  지우지 않고 녹화를 거부한다.

## 2. Harvest (사이트 PC)

- `python tools/perception/dataset/harvest.py <host>`: SSH로 완료 세션만 가져와 sha256을 대조하고,
  로봇 쪽 세션에 `harvested` 표시를 남긴다. 저장은 `data/perception/raw/<device>/<session>/`.
- 첫 바퀴는 수동 실행이다.

## 3. Dataset

`tools/perception/dataset/` CLI:

1. **extract** — MCAP 세션 또는 MP4에서 프레임을 뽑는다. JPEG은 재인코딩하지 않는다.
   0.5 s당 한 장 상한, 이미지 해시로 거의 같은 프레임을 뺀다. `frames.jsonl`에 시각과 곁 데이터
   (`cmd_vel`, 규칙 관측, 섀도 결과)를 남긴다.
2. **prelabel** — 현재 모델로 마스크 초안을 만들고, 선별 점수(픽셀 엔트로피, 차선 픽셀 부족,
   규칙 기반과의 차이)로 순서를 매겨 CVAT 가져오기 형식으로 낸다.
3. **build** — CVAT 결과를 8-bit 팔레트 PNG 마스크(값 = 클래스 인덱스, comma10k 규약)와
   `manifest.json`(프레임, 출처 세션, split, `deleted_indexes`, 클래스 표)으로 만든다.
   split은 **세션 단위**다. `classes.yaml`이 클래스 정본이다.
4. **publish** — HF private dataset 저장소에 1000장 단위 shard로 올리고 commit SHA를 받는다.
   학습에는 태그가 아니라 commit SHA를 넘긴다.

## 4. 학습과의 약속

학습은 어디서 돌려도 된다. 약속은 입력과 출력뿐이다.

- **입력:** HF dataset 저장소와 commit SHA.
- **출력:** HF model 저장소의 한 commit에 `model.onnx`(opset 17, 고정 입력 `1×3×240×320`)와
  `model_manifest.json`.

`model_manifest.json` (`schema: rosy.perception.model/1`):

| 필드 | 뜻 |
|---|---|
| `model_revision` | `lane-seg-YYYYMMDD-<sha8>` 형식, 전역 유일 |
| `task` | `lane_seg` |
| `files[]` | `name`, `sha256`, `precision`(`fp32`/`int8`) |
| `input` | `shape`, `color`(`rgb`/`bgr`), `scale`, `mean[3]`, `std[3]`, `layout: nchw` |
| `output` | `layout: nchw_logits`, `classes[]` = `{index, name, role}` |
| `dataset` | `repo`, `revision` |
| `camera_profile_revision` | 학습 영상의 CameraProfile |
| `metrics` | 검증 split의 클래스별 IoU |
| `trainer` | 코드 저장소·commit 또는 노트북 식별자 |

`role`은 닫힌 목록이다: `background`, `lane_marking`, `drivable`, `stop_line`, `ignore`.
후처리는 이름이 아니라 role을 읽는다. `lane_marking`이 하나도 없으면 접수를 거부한다.

`tools/perception/training/`에 약속 문서, 검사기(`check_manifest.py`), Colab 끝부분에 붙일
내보내기 셀 예시를 둔다. TorchScript만 있는 모델은 `tools/perception/model/export_onnx.py`로
개발 PC에서 변환한다(torch는 개발 PC에만 필요).

## 5. 접수 · 전달 · 로봇 추론

**intake** (`tools/perception/model/intake.py`):

1. HF model 저장소의 commit(또는 로컬 폴더)을 가져온다.
2. manifest 스키마와 파일 sha256을 확인한다.
3. onnxruntime으로 열어 입력·출력 모양을 확인한다. TorchScript 원본이 있으면 같은 입력의 출력
   차이(최대 절대오차)를 잰다.
4. `data/teleop/learning/` MP4를 재생해 **접수 보고서**를 쓴다: 프레임당 지연(호스트), 클래스
   분포, 마스크 차선 중심과 규칙 기반 중심의 차이, NaN 여부.
5. 판정 기준은 `tools/perception/model/intake_gate.yaml`에 미리 적는다. 합격하면
   `data/perception/models/<revision>/`에 보고서와 함께 둔다.

이 보고서는 **섀도 배포 자격**이다. D-205 P3 게이트(주행 선택 자격)가 아니다.

**deliver** (`tools/perception/model/deliver.py <host> <revision>`):

- SSH로 `/var/lib/rosy/models/<revision>/`에 복사하고 로봇에서 sha256을 다시 확인한다.
- `/var/lib/rosy/models/shadow` 포인터 파일을 원자적으로 바꾼다. 이전 값은
  `shadow.previous`에 남는다. `deliver.py rollback`이 되돌린다.
- 릴리스 페이로드를 다시 만들지 않는다. 모델 파일은 코드가 아니라 데이터 세대다(D-137의
  세대 전환: 포인터 교체와 되돌리기).

**learned_lane 노드 (로봇, 섀도):**

- `/var/lib/rosy/models/shadow`를 읽어 manifest를 검증하고 onnxruntime 세션을 연다.
- 포인터가 바뀌면 새 세션을 옆에서 열고 첫 프레임으로 검사한 뒤 교체한다. 실패하면 이전 세션을
  유지한다.
- 카메라 프레임마다(처리 중이면 건너뜀) 마스크 → `lane_marking` 픽셀 → 차선 중심 오차와 신뢰도를
  계산해 `perception/learned/shadow`(String JSON)에 발행한다: revision, 지연, 오차, 신뢰도,
  클래스 비율.
- onnxruntime이 없거나 모델이 없으면 노드는 이유를 로그하고 대기한다. 다른 노드에 영향을 주지
  않는다.
- 기본 비활성. launch 인자로 켠다.

onnxruntime은 장치 이미지에 없다. 해시 고정 requirements에 추가하는 것은 이미지 계층 변경이라
이번 바퀴에서는 벤치 장치에 수동 설치로 실측하고, 이미지 반영은 실측 뒤 별도 작업으로 한다.

## 오류 처리

| 상황 | 동작 |
|---|---|
| manifest 스키마 위반, 해시 불일치, role 누락 | intake 거부, 로봇 로드 거부 |
| onnxruntime 없음 | 노드가 대기하고 이유를 로그 |
| 추론 예외, NaN, 출력 모양 불일치 | 그 프레임을 버리고 카운터 증가, 연속 실패 시 세션 해제 |
| 교체 중 새 모델 실패 | 이전 세션 유지 |
| 녹화 할당량 초과(미수거) | 녹화 거부, 운영자에게 표시 |

## 시험

- ROS-free 모듈(manifest, 전처리, 후처리, 로더 교체, 할당량, harvest 목록 계산, 데이터셋 빌드)은
  Windows 호스트 pytest로 시험한다.
- onnxruntime 통합 시험은 작은 합성 ONNX 모델로 돈다.
- 실제 `0930` 모델의 변환과 접수 보고서는 개발 PC 가상환경(`X:\DevTemp`)에서 한 번 돌려
  증거로 남긴다.
- ROS 노드와 recorder launch는 Linux/WSL에서 확인한다. 호스트 pytest 합격은 장치 합격이 아니다.

## 이번 바퀴에서 하지 않는 것

snapshot 녹화와 불일치 트리거, Fleet 자동 수거, CVAT 자동 연동, FiftyOne, INT8 양자화, Hailo,
이미지에 onnxruntime 고정, 학습 모델의 주행 활성화, Fleet 콘솔 패널.

## 열린 입력

- 클래스 4개의 이름·role, 정규화, 채널 순서 — 학습 노트북에서 받는다.
- HF 조직과 저장소 이름, 사이트 PC의 토큰 보관 위치.

## 첫 실행 증거 (호스트, 2026-09-30)

- 호스트: AMD Ryzen AI 7 PRO 350 w/ Radeon 860M, Windows 11. 다른 세션과 공유 중이라 부하가 높았고 지연 수치는 상한 쪽으로 읽어야 한다.
- 소프트웨어: Python 3.12.14, torch 2.14.0+cpu, onnxruntime 1.30.0, onnx 1.23.1 (venv는 `X:\DevTemp\rosy-ml-venv`).
- 대상: Colab 산출 `0930_best_model.torchscript.pt` (LaneUNet, 입력 1x3x240x320, 4 클래스). 전처리는 rgb, scale 1/255, mean 0, std 1.
- `export_onnx.py` parity `max_abs_diff=3.58e-06` (허용 1e-3). model_revision `lane-seg-20260930-05ac31c0`.
- `check_manifest.py`: OK.
- `intake.py` (`--max-frames 100`, 소스 7개, 700 프레임, ORT threads=2): verdict **pass**, reasons 없음. nan_frames 0, error_frames 0.
- intake 지연: p50 91.2 ms, p95 173.3 ms (게이트 p50 <= 400 ms).
- visible_fraction 0.973 (게이트 >= 0.30).
- error_delta vs rule baseline: median 0.201, p95 0.793 (n=621).
- 평균 클래스 비율: floor 0.817, line_a 0.080, line_b 0.071, wall 0.032.
- 순수 onnxruntime 지연 (50 프레임, 첫 소스): 아래 표.

| threads | p50 ms | p95 ms |
|---|---|---|
| 1 | 113.4 | 181.2 |
| 2 | 66.2 | 108.2 |
| 4 | 54.1 | 115.7 |

- 주의: 클래스 역할(floor/line_a/line_b/wall -> background/lane_marking/lane_marking/ignore)은 시각 추정에 따른 **잠정값**이며 실제 클래스 목록은 학습 노트북에서 받아야 한다. dataset revision(0x40)과 camera profile revision(`unknown-provisional`)도 자리표시자다.
- 이것은 개발 호스트 증거이며 Pi 5 / 실기 증거가 아니다. 잠정 manifest는 커밋하지 않았고 로봇에 전달하지 않았다.
