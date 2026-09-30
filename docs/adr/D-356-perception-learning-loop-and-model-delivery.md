## D-356 인식 학습 루프와 모델 전달 — 학습은 밖, 약속·접수·전달·섀도 추론은 안

**Status:** Proposed (2026-09-30). 설계: [2026-09-30-perception-learning-loop-design.md](../plans/2026-09-30-perception-learning-loop-design.md).
잇는 결정:

- [D-209](D-209-perception-folder-and-learned-backend.md)(Accepted): 학습 모델은 `backend_learned`이고 `perception/evidence`만 낸다. 가중치는 `src/`에 두지 않는다. 학습·채점은 `tools/perception/`, 산출물은 `data/perception/`이다.
- [D-199](D-199-camera-perception-contracts-and-backends.md)(Proposed): 모르는 `model_revision`은 닫힌다.
- [D-205](D-205-real-lane-mission-transition-order.md)(Proposed): 주행 선택은 텔레옵 재생 게이트 합격 뒤다.
- [D-137](D-137-yolo-lidar-ir.md)(Proposed): 모델 교체는 되돌릴 수 있는 세대 전환이다.
- D-186: 큰 데이터는 저장소에 넣지 않는다. D-290: 수집 전에 출처·캘리브레이션·모델 revision을 묶는다.

**Context:**

1. 외부(Colab)에서 학습한 차선 분할 모델 `0930_best_model.torchscript.pt`(LaneUNet, 입력 `1×3×240×320`, 출력 4클래스)가 생겼다. 이 모델을 읽는 코드, 추론 런타임, 로봇으로 보내는 경로가 없다.
2. 학습은 앞으로도 이 저장소 밖(Colab·GPU PC)에서 돈다. 학습 환경과 로봇 사이에 입력·출력 약속이 없다.
3. 로봇에서 카메라와 명령·관측을 함께 기록하는 도구가 없다. 로봇→PC 경로는 브라우저 수동 다운로드뿐이다.
4. 코드 릴리스(서명 페이로드)는 데이터 파일 하나를 바꾸려고 다시 만들기에 무겁다.

**Decision:**

1. **학습은 저장소 밖이다.** 저장소는 약속만 갖는다: 입력은 HF private dataset 저장소의 commit SHA, 출력은 HF private model 저장소 commit의 `model.onnx`와 `model_manifest.json`(`rosy.perception.model/1`). manifest는 파일별 sha256, 입력 전처리(색 순서·scale·mean·std), 클래스와 닫힌 role 목록(`background`, `lane_marking`, `drivable`, `stop_line`, `ignore`), 데이터셋 revision, CameraProfile revision을 적는다.
2. **로봇 추론 형식은 ONNX, 런타임은 onnxruntime(CPU)이다.** torch는 로봇에 올리지 않는다. TorchScript는 개발 PC에서 변환한다. Hailo는 같은 ONNX에서 나중에 별도 산출물로 다룬다.
3. **모델은 데이터 세대로 전달한다.** 사이트 PC가 접수(manifest·해시·ONNX 로드·재생 보고서)를 통과한 모델만 SSH로 `/var/lib/rosy/models/<revision>/`에 놓고, 포인터 파일을 원자적으로 바꾼다. 이전 포인터를 남겨 한 명령으로 되돌린다. 로봇은 인터넷의 모델 저장소에 직접 붙지 않는다.
4. **이번 결정의 로봇 추론은 섀도 전용이다.** 학습 모델 노드는 `perception/learned/shadow`에 결과를 내고, 어떤 제어 경로도 그것을 읽지 않는다. 접수 보고서는 섀도 배포 자격일 뿐 D-205 주행 선택 자격이 아니다. 활성화(`perception.backend=learned_seg`)는 D-205 P3 합격 뒤 별도 ADR이다.
5. **수집은 rosbag2 MCAP이다.** 압축 카메라, `cmd_vel`, 관측, 섀도 결과를 세션 단위로 기록하고 `session.json`에 D-290 항목을 적는다. 수거 전 세션은 할당량 때문에 지우지 않는다.

**Consequences:** 학습 코드가 어디서 돌든 manifest만 맞으면 로봇까지 간다. 섀도 결과가 쌓이면 규칙 기반과의 차이를 수집 트리거와 D-205 재생 게이트의 입력으로 쓸 수 있다. onnxruntime은 장치 이미지에 없으므로 이미지 반영(해시 고정 requirements)은 Pi 실측 뒤 별도 작업이다. 데이터와 모델이 외부 클라우드(HF private)에 올라가므로 토큰은 사이트 PC와 학습 환경에만 둔다.

**Validation:** ROS-free 모듈의 호스트 pytest, 합성 ONNX 통합 시험, 실제 `0930` 모델의 변환·접수 보고서 1회. 호스트 합격은 장치 합격이 아니다. Pi 5에서의 지연 실측이 섀도 배포의 첫 장치 증거다.

---

### 보강 2026-09-30 — 텔레옵 학습 영상 압축(H.265/H.264)과 로봇 압축 기록 제안

**Status:** 1–3은 개발 PC 도구 결정(이 보강으로 적용). 4는 **제안이며 사용자 승인 전에는 로봇에 반영하지 않는다.**

**Context:** 첫 실주행 세션 `20260930T124745Z_rosy-pinky-8kcn`(282 s)의 bag은 raw `sensor_msgs/Image` bgr8 320×240 @8 fps를 zstd_fast로 담아 488 MB, **103.7 MB/min(6.2 GB/h)** 이다. Decision 5가 적은 "압축 카메라"는 아직 로봇에 없다. 학습에는 모든 프레임과 명령·자세·관측의 시각 정렬만 있으면 되므로, 손실 영상으로 줄여도 학습 입력이 상하지 않는지 재어 보았다.

**Decision:**

1. **변환기 `tools/perception/dataset/bag_to_video.py`.** 세션의 `camera/front`(raw) 또는 `camera/front/compressed`(JPEG)의 모든 프레임을 원 크기 그대로, 평균 카메라 주기의 CFR로 인코딩하고 `data/teleop/learning/teleop_<device>_<UTC stamp>.{mp4,jsonl,json[,scan.npz]}`를 쓴다. `.jsonl`의 i행은 디코딩 프레임 i이다. 필드와 시계는 아래 sidecar 스키마를 따른다. LiDAR가 있으면 프레임별 직전 스캔을 `.scan.npz`(float16 `ranges[frame, beam]`, 스캔 stamp, dt, 각도·거리 메타)로 둔다(D-379 벽 라벨러 입력). `.json`은 `session.json` 원문과 변환 메타이다. `extract.py`는 mp4 옆 sidecar를 읽어 기록 stamp·부수 데이터·세션 이름을 그대로 쓴다(세션 분할이 원 bag과 같다). 변환 뒤 ffprobe 프레임 수와 sidecar 행 수가 다르면 실패한다.
   **Sidecar 스키마 `rosy.teleop.video/1`(이 브랜치와 D-379 공통 시계 규칙, 2026-10-01 검토 반영):**
   - `index`: 디코딩 프레임 번호(0부터, mp4 프레임 순서와 같다).
   - `t`: **카메라 헤더 stamp(초, float)**. `extract.py`의 MCAP 경로·영상 경로와 D-379 자동 라벨러가 모두 이 시계를 쓴다.
   - `stamp_ns`, `log_ns`: 헤더 stamp와 bag log time(ns 정수, 정확값). 카메라 log−stamp는 10–27 ms(평균 13 ms) 실측.
   - `side`: 부수 토픽별로 **프레임 bag log time 이하의 가장 최근 메시지**(나중 메시지는 쓰지 않는다 — 미래 누설 없음). `cmd_vel`={linear, angular}, `odom`={x, y, yaw}, `line/observation`·`perception/learned/shadow`=디코딩한 JSON, `scan`={stamp_ns}(거리값은 `.scan.npz`의 같은 행). `--max-gap`(기본 0.5 s)보다 오래됐거나 앞선 메시지가 없으면 null. `Twist`에 헤더가 없어 부수 토픽 선택의 공통 시계는 bag log time이다.
   - `dt`: 토픽별 (부수 log time − 프레임 log time) 초, 항상 ≤ 0, 없으면 null.
   - `motion`: {moving, commanded, v, w}. 프레임 이전 0.5 s의 odom 변위와 현재 명령으로만 정한다.
   - `extract.py`의 MCAP 경로도 같은 규칙이다: `t`=헤더 stamp, `side`=bag 순서상 프레임 이전의 최신값, 행에 `stamp_ns`·`log_ns`를 같이 적는다.
2. **기본값: 보관은 H.265 `libx265 -preset slow -crf 24`, 호환은 H.264 `libx264 -preset slow -crf 23`(`--codec h264`). 둘 다 yuv420p와 `scale=flags=accurate_rnd+full_chroma_int`.** 근거는 아래 표이다. H.265 CRF 24는 bag 대비 156배(0.66 MB/min)이고 차선 검출 차이가 CRF 18과 구별되지 않는다. 320×240에서 H.265의 이득은 작다(같은 PSNR에서 x264 slow 대비 약 6 %). 호환이 중요하면 H.264 CRF 23(0.71 MB/min)으로도 충분하다. `accurate_rnd`는 swscale 기본 BGR→YUV 반올림 편향(무손실 qp 0에서도 BGR 평균 −1.5…−2.9)을 줄인다. 크기 변화 없이 PSNR +1.0 dB, 흰 마스크 IoU 0.963→0.973, line 오차 MAE 0.0038→0.0027이다.
3. **공개 저장소 보호.** `data/teleop/learning/*`를 gitignore한다(`.gitkeep`만 허용). 2026-09-19 클립 7개는 이 규칙 전에 커밋되어 아직 추적된다. 추적 해제(`git rm --cached`)는 별도 결정이다. 원 bag은 `data/perception/raw`에 그대로 둔다.
4. **제안(승인 필요): 로봇은 raw 대신 `camera/front/compressed` JPEG q85를 기록한다.** 학습 루프 소유자(D-356/D-373)의 선호와 같고, `extract.py`·`bag_to_video.py`가 이미 읽는다. 같은 헤더 stamp를 유지하고 부수 데이터는 stamp/log time으로 맞춘다. 로봇 인식 경로는 계속 raw를 프로세스 안에서 쓴다. H.264 bag 토픽(`foxglove_msgs/CompressedVideo` 또는 `ffmpeg_image_transport`)은 JPEG보다 3.7배 작다. 하지만 프레임 간 의존(키프레임 간격, 분할 시 손실)이 있고 Jazzy arm64 패키지와 이미지 반영이 필요해 2단계로 미룬다.

**증거 — 코덱 비교(세션 1, 2258 프레임, 4.704 min, 개발 PC Ryzen AI 7 PRO 350 / Radeon 860M).** 품질은 raw 프레임 대비이다. PSNR은 BGR 전체(괄호는 최악 프레임), SSIM은 ffmpeg Y이다. 흰 IoU는 `lane_replay.white_mask`(괄호는 p5), 바닥 IoU는 `floor_white_mask`이며 3프레임마다 쟀다. 검출기 열은 `tools/lane_replay.py --crop none --detectors line,between,keep`를 raw와 디코딩 프레임에 각각 돌려 비교한 값이다: 가시성 일치율 / |error| 차 평균 / p95(error는 화면 반폭 단위, 0.01 = 1.6 px). enc fps는 CPU 계열과 하드웨어 계열을 동시에 돌린 벽시계 값이다. 공정한 비교값은 괄호의 CPU ms/frame(user+sys, raw 읽기 포함)이다. NVENC·QSV는 이 PC에서 쓸 수 없다(NVIDIA 드라이버 없음, QSV MFX 세션 실패). 그래서 하드웨어 비교는 AMD AMF로 했다.

| 설정 | MB/min | bag 대비 | PSNR dB (최악) | SSIM Y | 흰 IoU (p5) | 바닥 IoU | enc fps (CPU ms/f) | line 일치/MAE/p95 | between | keep |
|---|---|---|---|---|---|---|---|---|---|---|
| raw bag (zstd_fast) | 103.7 | 1 | ∞ | 1 | 1 | 1 | – | 1/0/0 | 1/0/0 | 1/0/0 |
| **x265 CRF24 slow + accurate_rnd (기본)** | **0.66** | **156** | **37.24 (34.1)** | 0.983 | **0.973 (0.931)** | 0.975 | 26 (35.0) | 1.000/0.0027/0.017 | 0.997/0.0096/0.024 | 0.997/0.0304/0.029 |
| x265 CRF20 slow | 1.40 | 74 | 37.07 (34.5) | 0.990 | 0.966 (0.890) | 0.980 | 31 (43.6) | 1.000/0.0036/0.024 | 0.999/0.0089/0.024 | 0.996/0.0303/0.021 |
| x265 CRF24 slow | 0.67 | 155 | 36.20 (33.5) | 0.983 | 0.963 (0.884) | 0.975 | 19 (34.8) | 1.000/0.0038/0.024 | 0.999/0.0104/0.024 | 0.995/0.0211/0.027 |
| x265 CRF24 medium | 0.61 | 170 | 35.94 (33.2) | 0.981 | 0.962 (0.883) | 0.974 | 57 (15.2) | 1.000/0.0038/0.024 | 0.998/0.0069/0.011 | 0.996/0.0297/0.034 |
| x265 CRF26 slow | 0.48 | 217 | 35.63 (32.9) | 0.978 | 0.962 (0.883) | 0.971 | 46 (30.0) | 1.000/0.0037/0.024 | 0.999/0.0162/0.056 | 0.995/0.0191/0.025 |
| x265 CRF28 slow | 0.35 | 298 | 34.97 (32.2) | 0.971 | 0.960 (0.883) | 0.967 | 39 (27.5) | 1.000/0.0040/0.025 | 0.998/0.0078/0.024 | 0.994/0.0264/0.032 |
| x264 CRF18 medium | 1.95 | 53 | 37.16 (34.8) | 0.990 | 0.966 (0.894) | 0.980 | 290 (10.4) | 1.000/0.0036/0.023 | 0.998/0.0073/0.024 | 0.995/0.0251/0.026 |
| x264 CRF18 slow | 1.87 | 56 | 37.20 (34.8) | 0.991 | 0.966 (0.892) | 0.980 | 160 (17.5) | 1.000/0.0036/0.023 | 0.999/0.0073/0.024 | 0.996/0.0258/0.027 |
| x264 CRF23 medium | 0.74 | 141 | 35.97 (33.6) | 0.982 | 0.963 (0.887) | 0.973 | 298 (7.9) | 1.000/0.0038/0.023 | 0.998/0.0099/0.022 | 0.994/0.0170/0.027 |
| x264 CRF23 slow | 0.71 | 146 | 36.05 (33.6) | 0.983 | 0.963 (0.886) | 0.973 | 217 (11.7) | 1.000/0.0037/0.023 | 0.998/0.0069/0.024 | 0.996/0.0236/0.034 |
| x264 CRF28 medium | 0.33 | 317 | 34.24 (31.6) | 0.963 | 0.956 (0.875) | 0.964 | 319 (6.8) | 1.000/0.0042/0.024 | 0.997/0.0126/0.034 | 0.994/0.0245/0.035 |
| x264 CRF28 slow | 0.31 | 332 | 34.34 (31.6) | 0.965 | 0.957 (0.878) | 0.964 | 279 (9.7) | 1.000/0.0039/0.024 | 0.997/0.0092/0.028 | 0.995/0.0187/0.026 |
| x264 CRF23 ultrafast zerolatency, 1 thread | 2.24 | 46 | 36.31 (34.2) | 0.984 | 0.964 (0.882) | 0.977 | 931 (1.36) | 1.000/0.0036/0.023 | 0.999/0.0090/0.040 | 0.995/0.0274/0.029 |
| x264 CRF23 superfast zerolatency | 1.66 | 62 | 35.97 (33.9) | 0.985 | 0.962 (0.886) | 0.975 | 765 (2.3) | 1.000/0.0037/0.023 | 0.998/0.0086/0.025 | 0.995/0.0268/0.032 |
| AMF H.264 QP23 | 0.79 | 131 | 35.10 (34.0) | 0.972 | 0.961 (0.883) | 0.968 | 191 (3.3) | 1.000/0.0038/0.024 | 0.998/0.0108/0.024 | 0.994/0.0275/0.033 |
| AMF H.264 QP28 | 0.36 | 292 | 32.97 (31.7) | 0.936 | 0.948 (0.840) | 0.955 | 244 (2.7) | 1.000/0.0044/0.029 | 0.997/0.0207/0.085 | 0.993/0.0585/0.481 |
| AMF HEVC QP24 | 0.66 | 157 | 34.94 (33.7) | 0.970 | 0.960 (0.874) | 0.967 | 307 (2.8) | 1.000/0.0039/0.025 | 0.998/0.0087/0.024 | 0.993/0.0260/0.023 |
| AMF HEVC QP28 | 0.33 | 313 | 33.16 (32.2) | 0.939 | 0.953 (0.857) | 0.957 | 246 (2.7) | 1.000/0.0043/0.026 | 0.998/0.0099/0.024 | 0.992/0.0168/0.023 |
| JPEG q75 (프레임별, OpenCV) | 6.19 | 17 | 34.31 (33.4) | – | 0.963 (0.911) | 0.959 | 1079 (0.93) | 1.000/0.0009/0.002 | 0.999/0.0314/0.108 | 0.996/0.0137/0.028 |
| **JPEG q85 (제안: 로봇 기록)** | **8.27** | **13** | 36.08 (35.2) | – | 0.972 (0.928) | 0.966 | 1304 (0.77) | **1.000/0.0007/0.002** | 0.999/0.0149/0.058 | 0.995/0.0305/0.029 |
| JPEG q95 | 15.03 | 7 | 39.87 (38.2) | – | 0.982 (0.951) | 0.980 | 978 (1.02) | 1.000/0.0005/0.001 | 0.999/0.0082/0.039 | 0.997/0.0297/0.026 |

읽는 법: `line` 검출기는 모든 설정에서 가시성이 100 %이고 목표 오차 차는 평균 0.7 px 이하이다. `between`·`keep`의 MAE 0.007–0.03은 JPEG q95와 x264 CRF18에서도 같은 크기이다. 따라서 코덱 품질 탓이 아니라, 드문 프레임에서 검출기가 두 해 사이를 오가는 불안정이다(keep의 |차| > 0.1 비율은 모든 설정에서 약 2 %). 품질이 무너지는 설정은 AMF QP28(keep p95 0.48)뿐이다. 하드웨어 AMF는 같은 크기에서 x265보다 PSNR이 1–2 dB 낮다.

**변환 결과(개발 PC `data/teleop/learning/`, gitignored):**

| 세션 | 프레임 | 길이 | bag | mp4 (H.265 CRF24) | sidecar | moving 프레임 |
|---|---|---|---|---|---|---|
| `20260930T124745Z` real-lane-drive | 2258 | 282 s | 488 MB | 3.12 MB (156×) | jsonl 1.2 MB | 653 (29 %) |
| `20260930T133221Z` intersection-claude-scripted | 6940 | 867 s | 1420 MB | 3.89 MB (365×) | jsonl 4.4 MB, scan.npz 3.6 MB (720 beams) | 772 (11 %) |

moving은 명령(|v| > 0.01 m/s 또는 |ω| > 0.05 rad/s)이 있거나, 프레임 이전 0.5 s 창의 odom 변위가 0.01 m/s 또는 0.03 rad/s를 넘는 프레임이다. 이 로봇의 텔레옵은 0.03 m/s·0.1 rad/s이고, 정지 중 odom 잡음은 p99 기준 0.005 m/s·0.008 rad/s 아래였다. 보관 영상에는 정지 프레임도 모두 남긴다.

**제안 4의 추정(로봇 반영 전에 Pi 실측 필요):**

- 저장량: raw bag 6.2 GB/h → JPEG q85 약 **0.50 GB/h**(부수 토픽 수십 MB/h 별도. 720 beam 10 Hz LiDAR를 raw float32로 담으면 약 0.1 GB/h 추가) → x264 ultrafast/zerolatency CRF23 약 **0.13 GB/h** → 개발 PC 보관 H.265 **0.04 GB/h**. SD 여유 20 GB 기준 raw는 약 3 h, JPEG q85는 약 35 h이다.
- CPU: 개발 PC(Zen 5) 한 스레드에서 JPEG q85는 0.77 ms/frame, x264 ultrafast는 1.36 ms/frame(raw 읽기 포함)이다. Pi 5(Cortex-A76 2.4 GHz)의 단일 스레드 성능은 대략 3–5배 느리다고 본다(공개 Geekbench 6 단일 코어 비교 수준의 추정). 그러면 Pi 5에서 JPEG q85는 약 2.5–4 ms/frame(libjpeg-turbo NEON), x264 ultrafast는 약 4–7 ms/frame이다. 8 fps에서 **코어 하나의 2–6 %**(4코어 전체의 1–1.5 %)이다. 320×240@8 fps는 0.61 Mpx/s로, Raspberry Pi가 Pi 5에서 소프트웨어 인코딩으로 감당한다고 밝힌 1080p30(62 Mpx/s)의 약 1 %이다. 반대로 raw 기록은 1.8 MB/s를 zstd로 압축해 SD에 쓰므로, 압축 기록은 SD 쓰기(마모)와 zstd CPU를 오히려 줄인다.
- 로봇 변경 범위(승인 뒤 별도 작업): 카메라 노드가 같은 헤더 stamp로 `camera/front/compressed`(JPEG q85)를 내고, `control/recording.py`의 `RECORD_TOPICS` 카메라 항목을 압축 토픽으로 바꾼다. 이미지 반영이나 릴리스 푸시가 필요하다. 첫 증거는 Pi에서 기록 중 CPU·지연·드롭 프레임 실측이다.

**Validation:** `tools/perception/test/test_bag_to_video.py`(합성 MCAP으로 프레임 수, ns stamp, 직전값 정렬(미래 메시지 배제), extract 헤더 stamp 시계, max-gap null, LiDAR npz, 압축 입력, motion, extract 왕복을 확인)가 통과했다. 코덱 연구 스크립트와 결과는 저장소 밖 `X:\DevTemp\teleop-video\`에 있다. 호스트 결과는 장치 결과가 아니다.
