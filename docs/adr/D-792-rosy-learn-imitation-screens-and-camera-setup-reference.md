## D-792 Rosy Learning(학습 관리 센터) 이름과 모방학습 화면 — 카메라 촬영 기준을 점선 가이드로 재현하고 녹화 전에 확인한다

**Status:** Proposed

## Context

2026-10-18 사용자 지시: 모방학습용 learning 앱과, 비디오를 이미지 처리해 객체 탐지·분할하는 앱을 정하고 구축과 이름을 검토한다. 추천안(앱 하나에 정식 이름과 모방학습 화면을 더한다)으로 빠르게, 반복해서 진행한다. 모방학습을 위해 카메라 각도·높이(cm)·이전 화면의 모양과 위치를 같게 맞추는 점선 가이드와, 그것으로 캘리브레이션하는 구조를 ADR에 담는다.

조사한 현재 상태는 다음과 같다.

| 항목 | 현재 |
|---|---|
| 모델 PC 앱 | `learning/curation/perception/review_app.py` 하나가 `rosy-review-v13.service`로 돈다(D-545). 화면 제목은 "Rosy 개발", 문서에서는 "학습 관리 센터"(D-745)와 "검수 스튜디오"(D-538)가 섞여 쓰인다. |
| 비디오·비전 | 객체 검수 `/`, 픽셀 검수 `/pixels`, SAM3·Qwen 초안(D-465), 자료 등록 `/catalog`, 프레임 추출(`media_pipeline.py`, `frames.py`, `bag_to_video.py`)이 이미 있다. |
| 모방학습 | `/learning`의 `omx` 항목(`learning_workspace.py` `WORKFLOWS`)은 보고서 링크다. Episode 선택·학습 실행 화면은 없다. 백엔드는 `learning/curation/omx/lerobot_export.py`, `learning/training/omx/act_job.py`, 소유 실행기 제어(D-745)가 있다. |
| 카메라 기록 | OMX Episode `provenance.camera`는 `name`, `identity`, `camera_info_sha256`, `width`, `height`만 요구한다(`contracts/learning/src/rosy/contracts/learning/omx.py`). 카메라 높이·각도·위치, 이전 세션과의 차이는 어디에도 없다. |
| 교정 | 내부 교정은 AprilGrid 측정(`operations/overhead/rosy_vision/camera_calibration.py`, D-633·D-636)이고, 승인·적용·무효화는 목적별 기존 소유자가 맡는다(D-775). OMX 카메라에는 교정 코드가 없고 화질 점검만 있다(`deploy/robot/omx/camera_*.py`). |
| 점선 그리기 | Console `calibration/map-fit-view.js`(호모그래피로 투영한 차선 점선), `shared/guide-layer.js`(D-536), 검수 `review_app_web/app.js`(AI 초안 점선)가 있다. 이전 화면을 겹쳐 보는 기능은 없다. |

ACT 같은 모방학습 정책은 학습 때 본 카메라 시점에 강하게 묶인다. 카메라가 몇 cm 내려가거나 1°만 기울어도 같은 정책이 다른 물체 위치를 본다. D-423은 Pinky 카메라의 실측 기울기 11.2–11.8°와 URDF 8°의 차이가 거리 오차를 만든 사례다. 녹화 때마다 시점이 조금씩 달라지면 데이터는 쌓여도 정책은 좋아지지 않고, 나중에는 어느 Episode가 다른 시점이었는지 알 수 없다.

## Decision

### 1. 앱 하나, 이름은 Rosy Learning(학습 관리 센터)

1. 모델 PC의 학습·검수 웹앱 전체를 **Rosy Learning**(한국어 표기 **학습 관리 센터**)이라 부른다. 이 이름은 이미 D-461의 작업 화면 표시 이름이고 D-377 이름 규칙(Rosy + 영어 한 단어)에 맞으므로 새 이름을 만들지 않는다. 브라우저 제목은 개발 도구 표면 규칙(`shared/web/surfaces.yaml`의 `surface: dev`)대로 "Rosy 개발 — <화면>"을 유지하고, 별도 런처·PWA 등록도 하지 않는다(D-461).
2. 앱을 둘로 나누지 않는다. 비디오 탐지·분할(객체 검수·픽셀 검수)과 모방학습은 같은 앱의 화면이다. 서비스, 릴리스(D-545), 계정, 통합 셸(D-741), `shared/web`을 그대로 쓴다.
3. 실행 파일·서비스·폴더 이름(`review_app.py`, `review_app_web/`, `rosy-review-v13.service`)은 이 ADR에서 바꾸지 않는다. 진행 중인 `learning-plan`·`learning-delivery` 작업과 배포 경로를 깨지 않기 위해서다. 이름 변경은 별도 ADR에서 한 번에 한다.
4. 화면 이름은 다음으로 고정한다.

| 화면 | 경로 | 상태 |
|---|---|---|
| 객체 검수 | `/` | 있음 |
| 픽셀 검수 | `/pixels` | 있음 |
| 자료 등록 | `/catalog` | 있음 |
| 학습 작업 | `/learning` | 있음(목록) |
| 카메라 맞춤 | `/learning/camera` | 새로 만듦(§3) |
| 모방학습 | `/learning/omx` | 새로 만듦(§5) |

5. 쓰지 않는 이름: **Studio**는 검수 작업대(D-538 "검수 스튜디오")에만 쓴다. **Lab**은 원격 pytest 대상 실험실 PC와 헷갈린다. **Cell**은 팔레타이징 앱이다. **Vision**은 `operations/vision`과 `rosy_vision`(천장 카메라)이 쓴다. **Perception**은 ROS `control` 패키지와 관측 층 이름이다.

### 2. 카메라 촬영 기준(Camera Setup Reference)

카메라 역할(OMX `front`·`top`, Pinky `front`)마다 **촬영 기준** 한 개를 불변 기록으로 둔다. 스키마는 `rosy.camera-setup-reference/1`이고 `contracts/learning`(ROS·torch 의존 없음, D-449)이 검증한다.

**맞추는 방식은 마커 없는 `features`가 기본이다.** 2026-10-18 사용자 확인으로 OMX 작업대에는 마커가 없다. 마커를 새로 붙이지 않고, 기준 사진과 지금 사진에서 움직이지 않는 배경(작업대 가장자리·벽·팔 베이스)의 ORB 특징점을 맞춘 호모그래피로 카메라 움직임을 잰다. 작업면 마커(ArUco `DICT_4X4_50` 4장)를 두는 `markers`는 높이·거리를 cm로 봐야 할 때 쓰는 선택 방식이다.

| 묶음 | 필드 | 출처 |
|---|---|---|
| 식별 | `camera_role`, `camera_identity`, `width`, `height`, `fps` | 녹화 장치. Episode `provenance.camera`와 같은 값 |
| 내부 교정 | `intrinsics`(`camera_info_sha256`, `revision`, `k`, `dist`) | 측정 교정 소유자(D-633·D-775). 이 ADR은 값을 만들지 않고 복사해 지문으로 묶는다. `features`도 각도 환산에 `k`를 쓴다 |
| 방식 | `method`: `features`(기본) 또는 `markers` | 기준을 만드는 사람 |
| 확인 자세 | `check_pose`: 팔에 달린 카메라(OMX `front` 손목)만, 관절 이름·각도(rad)·허용치. 고정 카메라는 null | 기준 사진을 찍을 때의 관절 readback |
| 실측 장착 | `mount.measured`: `height_cm`(작업면에서 렌즈 중심까지), `distance_cm`(작업대 원점에서 렌즈까지 수평), `tilt_deg`, `pan_deg`, `roll_deg`. 모르는 값은 null | 사람이 줄자·수평계로 잰 값 |
| 추정 장착 | `mount.estimated`: 같은 다섯 값. `features`는 null | `markers`만 기준 마커로 계산한다(solvePnP) |
| 기준 화면 | `reference_still`(JPEG 한 장의 SHA-256), `marker_dictionary`·`markers`(`markers`만, ID별 네 꼭짓점 픽셀), `guides`(작업면 가장자리·작업 구역 다각형·물체 윤곽선, 픽셀 좌표) | 기준을 만들 때 찍은 한 장과 사람이 확인한 윤곽. 물체 윤곽은 픽셀 검수 마스크에서 가져오거나 손으로 그린다 |
| 버전 | `revision` = 위 내용의 SHA-256, `created_at`, `created_by` | 내용이 바뀌면 새 revision이다 |

- `features` 기준 사진은 특징점이 500개 이상이어야 한다. 비어 있거나 어두운 사진으로 만든 기준은 이후 모든 판정을 `측정 불가`로 만들기 때문이다. 기준은 조명이 켜진 조건에서 만든다.
- `markers`는 실측과 추정을 둘 다 남긴다. 차이가 2 cm·3°를 넘으면 줄자 기록이나 마커 배치 중 하나가 틀린 것이므로 기준을 거절한다. OpenCV 4.6 ArUco 파라미터 segfault(`docs/solutions/runtime-errors/opencv-4-6-aruco-detector-parameters-segfault-2026-09-24.md`)를 피하는 기존 방식을 따른다.
- 카메라를 일부러 옮기면 새 기준을 만든다. 이전 기준은 지우지 않는다.
- **팔에 달린 카메라는 확인 자세에서만 판정한다.** 2026-10-16 보존 프레임(`~/rosy-test/omx-camera-hires-033ab57d1/` on Fleet)으로 확인하면 OMX `top`은 두 팔과 매트 전체를 보는 작업대 고정 카메라이고, `front`는 그리퍼 바로 위에서 매트를 내려다보는 손목 카메라다(양쪽 집게 손가락이 화면에 보인다). 손목 카메라는 팔 자세가 바뀌면 화면 전체가 바뀌므로 그대로 비교하면 의미가 없다. 그래서 팔에 달린 카메라의 기준은 `check_pose`(`joint_names`, `positions_rad`, `tolerance_rad` 0.001–0.05, 기본 0.01)를 가진다. 판정은 지금 관절 readback을 함께 받고, 가장 큰 관절 차이가 허용치를 넘으면 사진을 비교하지 않고 `측정 불가`로 두며 그 차이를 `pose_error_rad`에 남긴다. readback이 없으면 판정을 거절한다. 0.01 rad는 0.2 m 팔 길이에서 손목 2 mm이며 화면 이동 기준보다 작다. 이것이 보는 것은 브래킷이 그리퍼에 같은 자리로 붙어 있는지다. 고정 카메라는 `check_pose`가 null이다.

### 3. 카메라 맞춤 화면: 점선 가이드

`/learning/camera`는 현재 카메라 화면 위에 기준을 겹쳐 그린다.

```
┌──────────────────────────────────────────────┐
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐   기준(점선)   │
│  ╎ ↘┌──────────────────────┐ ╎   현재(실선)   │
│  ╎  │   ( ─ ─ ─ ) 물체 윤곽 │ ╎                │
│  ╎  │   ( ─── )           ↗│ ╎                │
│  ╎  └──────────────────────┘ ╎                │
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘                │
├──────────────────────────────────────────────┤
│ 맞춘 특징점 1584 · 화면 이동 평균 20.0 px       │
│ pan +1.0° · tilt 0.0° · roll 0.0° · 크기 0.0%   │
│ 판정: 조정 필요               [기준 겹쳐 보기 40%] │
└──────────────────────────────────────────────┘
```

1. **점선은 기준, 실선은 현재**다. 기준 화면 안쪽 10% 틀, 작업면 가장자리·작업 구역·물체 윤곽(그리고 `markers`의 마커 사각형)을 점선으로 그린다. `features`는 같은 윤곽을 잰 호모그래피로 옮겨 실선으로, `markers`는 지금 검출된 마커를 실선으로 그린다. 틀 네 꼭짓점·화면 중심(또는 마커마다)에 기준에서 현재로 가는 화살표를 그린다. D-538에서 점선이 "확정이 아닌 참고"를 뜻하는 것과 같은 의미다.
2. **기준 화면 겹쳐 보기**: 기준 사진을 투명도 0–100%로 겹친다(기본 40%).
3. **숫자 표시**: 맞춘 특징점 수(또는 보인 마커 수), 화면 이동(평균·최대 px), pan·tilt·roll 차이(°), 크기 차이(%; 가까워지면 +), `markers`일 때 높이·거리 차이(cm)를 보여 준다.
4. **판정**은 `맞음`, `조정 필요`, `측정 불가` 셋이다. `측정 불가`는 맞춘 특징점이 150개 미만(너무 어둡거나 장면이 크게 바뀜)이거나, `markers`에서 마커가 3개 미만이거나, 내부 교정 지문·해상도가 기준과 다를 때다. 처음 기준값은 640×480 기준 화면 이동 평균 ≤ 3 px·최대 ≤ 6 px, 각도 ≤ 1°, 크기 ≤ 1%, 높이·거리 ≤ 0.5 cm다. 해상도가 다르면 px 기준은 대각선 비율로 환산한다. 재지 않은 값(null)은 판정에 넣지 않는다. 이 값은 시작점이며 S5에서 shadow 기록으로 실제 정책 성능 차이와 대조해 조정한다.
5. 그리기는 새로 만들지 않는다. 점선 투영은 Console `map-fit-view.js`·`guide-layer.js`의 방식, 점선 모양은 검수 `app.js`의 `setLineDash`를 따른다. 화면은 통합 셸(D-741)의 본문 칸에 둔다.
6. 첫 조각은 정지 사진 한 장(업로드 또는 녹화 장치에서 받은 한 프레임)으로 판정한다. 실시간 갱신은 같은 판정 함수를 프레임마다 부르는 다음 조각이다.

#### 마커 없는 방식의 실물 근거 (2026-10-18)

관제 PC의 실제 천장 카메라 프레임(1280×720, 86장)으로 확인했다. 같은 카메라의 다른 프레임 8장(LED·로봇만 바뀜)은 차이 0.0 px·0.0°였다. 실제 프레임에 카메라 회전을 넣으면 pan 0.5°·1°·2°를 0.49°·1.02°·2.02°로, tilt 1°를 0.93°로, roll 1°·3°를 1.00°·3.01°로, 2%·5% 접근을 2.0%·5.0%로 찾았다. 밝기 50%·25%·25%+노이즈·흐림·JPEG q30은 0.0 px였고, 밝기 10%+노이즈에서도 맞춘 점 295개·0.1 px였다. 밝기 5%에서 38개·0.9 px로 무너져 `MIN_MATCHES = 150`을 정했다. 어둡게 하고 pan 1°를 넣어도 1.01°였다. 이 장면은 정지 장면이라 쉬운 조건이며, 팔이 움직이는 OMX 작업대에서의 확인은 첫 현장 확인이 한다.

한계: 호모그래피는 장면을 멀거나 평평하다고 본다. 카메라가 회전 없이 옆으로만 밀리면 가까운 물체와 먼 배경의 시차가 pan·tilt 값에 섞인다. 판정은 화면 이동 px가 주도하므로 같은 시점으로 되돌리는 목적은 지킨다. `features`는 높이·거리를 cm로 재지 않는다.

### 4. 녹화 전 확인과 Episode 기록

1. 판정 함수는 하나다: `check(frame, reference, camera_info_sha256, still) → setup_check`. 입력은 프레임, 기준, 지금 카메라의 교정 지문, 기준 사진이고 출력은 숫자와 판정이다. 화면, 녹화 직전 점검, 오프라인 재점검이 모두 같은 함수를 쓴다.
2. 녹화 시작 직전에 한 번, 끝난 직후에 한 번 판정한다. 둘 사이에 카메라가 밀렸는지 보기 위해서다.
3. 결과는 Episode `provenance.camera.setup`에 남긴다. 재지 않는 값은 null이다(`features`의 cm, `markers`의 크기).

```json
{
  "reference_revision": "<sha256>",
  "before": {"method": "features", "matches": 1584, "pose_error_rad": null, "px_mean": 2.1, "px_max": 3.4,
             "d_pan_deg": 0.1, "d_tilt_deg": 0.6, "d_roll_deg": -0.2, "d_scale_pct": 0.3,
             "d_height_cm": null, "d_distance_cm": null, "verdict": "ok"},
  "after": {"...": "같은 모양"},
  "mode": "shadow"
}
```

4. 처음에는 **shadow**다. 판정을 기록만 하고 녹화를 막지 않는다. 판정 기준이 실제로 쓸모 있다고 확인되면(§6 S5) **enforce**로 바꾼다. enforce에서는 `before`가 `조정 필요`·`측정 불가`면 녹화를 시작하지 않고, `after`가 그렇다면 그 Episode를 자동으로 drop 후보로 표시한다.
5. 한 `DatasetManifest`는 카메라 역할마다 촬영 기준 revision 하나만 담는다. 다른 revision을 섞으려면 사람이 명시해서 섞어야 하고, 그 사실이 manifest에 남는다. 정책 산출물의 `camera_profile_revision`(D-449)은 이 revision을 가리킨다. 실물 정책 설치 때 카메라 identity를 대조하는 D-787의 방식을 촬영 기준 revision까지 넓힌다.
6. 내부 교정 지문(`camera_info_sha256`)이 기준과 다르면 판정은 `측정 불가`다. 교정을 다시 했으면 새 기준을 만든다.

### 5. 모방학습 화면

`/learning/omx`는 다음 순서를 한 화면에 둔다. 각 단계는 이미 있는 잡을 부르고, 화면이 새 학습 로직을 갖지 않는다.

| 단계 | 하는 일 | 쓰는 것 |
|---|---|---|
| 카메라 맞춤 | 역할별 기준 선택, 판정이 `맞음`인지 확인 | §3 |
| 시연 수집 | 녹화 시작·중지, 판정 before/after 기록 | `learning/curation/omx/native_capture.py`, `collection_pipeline.py` |
| Episode 검수 | 영상과 관절 궤적을 같이 재생, keep/drop, 판정 표시 | `common_episode.py` |
| 내보내기 | 고른 Episode를 LeRobot 형식으로 | `lerobot_export.py` |
| 학습 | ACT 시작·중지·재시도, 진행 상태 읽기 | `act_job.py`, D-745 소유 실행기 제어 |
| 평가·승격 | 평가 결과 확인 후 PromotionRecord | `contracts/learning`(D-449) |

Pinky 행동 학습도 같은 순서를 쓰되, 화면은 OMX가 끝까지 한 번 돈 다음에 연다.

### 6. 빠르게, 반복해서 내는 조각

조각마다 따로 착지한다. 각 조각은 자체 시험을 가지고, 원격 pytest의 affected 실행으로 확인하며, 모델 PC 반영은 D-545 릴리스로 한다.

| 조각 | 범위 | 끝난 기준 |
|---|---|---|
| S0 | 이 ADR, `CONCEPTS.md` 용어, ADR Log 행 | lint 통과 |
| S1 | `rosy.camera-setup-reference/1` 검증기와 `check()` 순수 함수(`features` 기본, `markers` 선택) | 합성 장면에 회전·접근·가림·어둠을 넣었을 때 판정이 바뀌는 시험, 실물 천장 프레임 근거(§3) |
| S2 | `/learning/camera` 정지 사진 판정과 점선 가이드, 다섯 화면 레일에 카메라 칸 | 화면 스모크(`learning/curation/perception/tools/review_app_smoke.py` 방식) |
| S3 | OMX 녹화가 `provenance.camera.setup`을 shadow로 기록, manifest의 revision 섞임 거절 | `contracts/learning` 시험, 수집 파이프라인 시험 |
| S4 | `/learning/omx` 화면(Episode 검수·내보내기·학습·승격) | 실제 Episode 몇 개로 끝까지 한 번 |
| S5 | shadow 기록과 정책 평가를 대조해 판정 기준을 고정, enforce로 전환 | 기준값 근거를 이 ADR의 후속 ADR에 기록 |

S1과 S2는 실시간 스트림이 없어도 된다. 사진 한 장으로 판정과 가이드가 돌면 실물 카메라에서 바로 반복해 맞출 수 있다.

#### S3·S4 구현 범위 (2026-10-18)

- S3는 녹화 PC가 아니라 모델 PC의 intake에서 판정한다. 촬영 기준은 리뷰 앱 상태(`<state>/camera-setup/`)에만 있어 녹화 PC가 닿지 않기 때문이다. 녹화 PC는 샘플 행에 실제 관절 각도 `joint_positions_rad`(profile 관절 순서)만 더 남긴다. `collection_intake.py prepare`·`collection_pipeline.py prepare`의 `--camera-reference ROLE=PATH`가 Episode마다 첫 프레임(before)·마지막 프레임(after)을 판정해 `camera-setup.json`(`rosy.omx-camera-setup-intake/1`)으로 남긴다. 한 번의 prepare는 역할마다 기준 하나만 받으므로 "역할당 revision 하나" 규칙은 그 자체로 지켜진다. 역할별 `camera_info` 지문도 같은 파일에 남겨 기준을 만들 때 그대로 복사하게 한다. 실물 OMX 데이터는 `rosy.dataset-manifest/1`을 만들지 않으므로(시뮬레이션·Pinky 전용) §4-5의 manifest 규칙은 실물에서는 이 파일이 맡는다.
- S4 첫 조각은 읽기 전용이다. `/learning/omx`는 `omx` 학습 행으로 연결한 intake 폴더를 읽어 Episode별 검수 결정, 학습이 쓰는 `reviewed_splits` 규칙으로 본 학습 가능 여부, S3 카메라 판정을 보여 준다. 응답에 서버 절대 경로를 넣지 않는다. keep/drop 쓰기, ACT 시작·중지(현재 `learning_control`은 perception 파이프라인만 묶는다), 승격(D-793에 따라 Fleet 소유)은 아직 만들지 않는다.

## 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-427 | 새 화면과 판정은 `learning/` 안에 둔다. 장치 쪽 녹화기는 판정 결과를 받아 적기만 한다. operations의 `rosy_vision` 코드를 learning이 직접 import하지 않는다. 필요한 마커 검출은 learning 쪽에서 OpenCV로 직접 하거나 공용 contracts로 옮긴 뒤 쓴다. |
| D-429 | 장치 제어 포트를 바꾸지 않는다. 카메라 맞춤은 관측만 하고 팔·바퀴를 움직이지 않는다. |
| D-430 | safety 경로를 바꾸지 않는다. enforce는 녹화 시작만 막으며 로봇 동작 권한과 무관하다. |
| D-299 | 시연 수집은 LeRobot 실험 경로(native)를 그대로 쓰고 운영 팔 제어권과 분리한다. |
| D-449 | 촬영 기준과 판정 기록을 학습 산출물의 출처 계약에 더한다. |
| D-377·D-461 | 앱 이름은 기존 표시 이름 Rosy Learning을 정식화한다. 브라우저 제목·앱 등록 규칙은 바꾸지 않는다. |
| D-538 | 점선은 참고, 실선은 현재라는 표시 규칙을 이어 쓴다. Studio라는 이름은 검수 작업대에 남긴다. |
| D-545 | 화면 추가는 같은 릴리스 경로로 모델 PC에 간다. |
| D-633·D-636·D-775 | 내부 교정 값은 이 ADR이 만들지 않는다. 기준은 교정 지문만 묶고, 교정이 바뀌면 기준도 새로 만든다. |
| D-741 | 새 화면은 통합 셸의 다섯 자리를 쓴다. |
| D-745 | 학습 시작·중지·재시도는 소유 실행기 제어를 그대로 부른다. |
| D-787 | 시뮬레이션 정책 설치의 카메라 identity 대조를 실물에서는 촬영 기준 revision 대조까지 넓힌다. 시뮬레이션 쪽은 바꾸지 않는다. |

## Consequences

- 같은 시점에서 모은 Episode만 한 데이터셋에 들어가므로, 정책 성능이 떨어졌을 때 카메라 시점 탓인지 바로 가를 수 있다.
- 녹화 전에 사람이 카메라를 맞추는 시간이 생긴다. 판정이 몇 초 안에 나와야 반복이 빠르므로 S2의 기준은 "사진 한 장 판정이 1초 이내"다.
- 마커 없는 방식은 장면 배경에 기댄다. 작업대 주변 배경(선반·벽 물건)을 크게 바꾸면 맞춘 점이 줄어 `측정 불가`가 되고, 그때는 같은 카메라 자리에서 새 기준을 만든다. `markers`를 쓰면 마커 위치가 촬영 기준의 일부다.
- 판정 기준값은 아직 근거가 없는 시작점이다. S5 전까지는 막지 않는다.

## Validation

- S0: `python tools/harness/rosy_harness.py lint`
- S1 이후: `test/learning/` 아래 조각별 시험. 경로는 각 조각의 커밋에서 정한다.

## References

D-100, D-199, D-377, D-461, D-299, D-423, D-427, D-429, D-430, D-449, D-465, D-538, D-545, D-633, D-636, D-741, D-745, D-775, D-787

## Amendment by D-857 (2026-10-24)

§1.4의 화면 목록은 5단계 메뉴(홈·자료·정답·학습·평가·승격)로 바뀐다. 도메인은 메뉴가 아니라 필터다. §1.3의 `rosy-review-v13.service`는 기능을 센터(8768)로 옮긴 뒤 퇴역한다. 카메라 촬영 기준과 모방학습 흐름은 그대로다. [D-857](D-857-rosy-learning-product-definition.md)
