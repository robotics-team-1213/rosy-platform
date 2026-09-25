# 카메라 지면 캘리브레이션

`camera_detect_node`가 영역(region)까지의 거리를 미터로 보고하려면 카메라 높이·피치·초점거리가
필요합니다. 이 값이 없으면 `ground_plane()`이 `None`을 돌려주고, 모든 영역은 지금처럼
`distance_m: null`(거리 미상)로 나갑니다. **측정하지 않은 값을 기본값으로 넣지 않습니다** —
그럴듯한 가짜 거리는 거리 없음보다 나쁩니다.

## 왜 필요한가

지금 카메라의 출력은 "왼쪽/가운데/오른쪽 3분할 컬럼의 장애물 픽셀 비율"입니다. 라이다는 미터로
말하고 카메라는 사각형의 백분율로 말하니 둘을 융합할 수 없습니다. 지면 평면(homography)을 알면
영역의 **아랫변**(바닥에 닿는 지점)을 미터로 바꿀 수 있고, 그때부터 정지거리와 직접 비교됩니다.

## 전제 두 가지 (Ulrich & Nourbakhsh, AAAI-00)

- **평평한 바닥** — 경사가 있으면 접지점이 밀리고 추정값도 같이 틀립니다.
- **돌출물 없음** — 아랫변을 재므로 책상 상판 같은 돌출물은 "그 아래 바닥까지의 거리"로 읽힙니다.
  이 경우는 초음파 센서가 담당합니다(원 논문도 같은 처방을 냅니다).

## 절차

### 권장 구조: 내부 보정과 지면 보정을 분리

ArUco 마커 한 장을 한 번 보는 것은 카메라 내부 파라미터와 로봇 기준 지면 거리를 동시에
확정하지 못합니다. 다음 두 단계를 분리합니다.

1. **내부 보정**: ChArUco 보드를 여러 거리·각도·화면 위치에서 촬영해 카메라 행렬과 렌즈 왜곡을 구합니다.
2. **고정 장착 지면 보정**: 마운트를 고정한 뒤 바닥에 둔 보드의 점과 실측 로봇 전방 거리를 대응시켜
   호모그래피를 만들고, 학습에 쓰지 않은 별도 사진으로 검증합니다.

OpenCV도 일반 ArUco 모서리보다 ChArUco 모서리의 정확도가 높아 카메라 보정에는 ChArUco 사용을
권장합니다. 일부 가림을 허용하는 장점도 있습니다.

- [OpenCV ChArUco 카메라 보정](https://docs.opencv.org/4.12.0/da/d13/tutorial_aruco_calibration.html)
- [OpenCV ChArUco 검출·자세 추정](https://docs.opencv.org/4.12.0/df/d4a/tutorial_charuco_detection.html)
- [OpenCV 보정 품질·뷰 선택](https://docs.opencv.org/4.5.5/d7/d21/tutorial_interactive_calibration.html)

### 1. 내부 파라미터 (초점거리, 주점)

체커보드를 인쇄해 **실제 운용 해상도(320x240)** 로 10장 이상, 각도와 거리를 바꿔가며 촬영합니다.

```bash
# 로봇에서, 노출을 고정한 상태로 촬영할 것
ros2 run control camera_detect_node --ros-args -p camera_lock_enabled:=true
```

OpenCV `findChessboardCorners` → `cornerSubPix` → `calibrateCamera`로 카메라 행렬을 얻습니다.
행렬의 `fx`, `fy`가 초점거리(px), `cx`, `cy`가 주점입니다.

> **해상도 주의**: 내부 파라미터는 libcamera 센서 모드마다 크롭/비닝이 달라 그대로 옮겨지지
> 않습니다. 반드시 운용 해상도 그대로 캘리브레이션하거나, 크롭·스케일 배율을 정확히 반영해
> `fx, fy, cx, cy`를 환산하십시오.

캘리브레이션 전 임시값이 필요하면 `camera_ground.focal_from_hfov(320, radians(54))`로 시작할 수
있습니다. OV5647 표준 3.6mm 렌즈가 수평 약 54도입니다. 이는 **출발점이지 대체품이 아닙니다.**

### 2. 높이와 피치

- **높이**: 바닥에서 렌즈 중심까지 자로 잽니다. CAD 값을 믿지 말고 실측하십시오.
- **피치**: 아래 4점 대응으로 역산하는 편이 각도기보다 정확합니다.

### 3. 4점 대응 (지면 호모그래피)

1. 로봇 전방 바닥에 **치수를 아는 직사각형**(예: 60cm x 40cm)을 로봇 전진축에 맞춰 테이프로 붙입니다.
2. 노출이 고정된 상태에서 한 프레임을 캡처합니다.
3. 네 모서리의 이미지 좌표를 찍습니다.
4. 렌즈 왜곡을 먼저 제거하고(`cv2.undistortPoints`) 대응을 맞춥니다. 왜곡이 남은 점으로
   호모그래피를 맞추면 그 네 점 근처에서만 맞고 나머지가 전부 틀어집니다.
5. `cv2.getPerspectiveTransform(image_pts, ground_pts)`로 호모그래피를 얻고, 여기서 피치를
   역산하거나 `GroundPlane`의 값과 교차검증합니다.

> 320x240에서 프레임 전체를 `undistort`할 필요는 없습니다. 실제로 변환하는 점은 영역당 한 개
> (아랫변)이므로 `undistortPoints`로 **점만** 펴는 편이 훨씬 쌉니다.

### 4. 검증

물체를 **실측 1.0m** 지점에 놓고 보고되는 `distance_m`이 맞는지 확인합니다. 0.5m, 2.0m에서도
반복하십시오. 피치 오차가 지배적이라 1도만 틀려도 원거리에서 크게 벌어집니다.

### 5. 신뢰 범위 결정

지평선 근처에서는 역탄젠트가 발산해 **세그멘테이션이 한 행만 흔들려도 거리 오차가 미터 단위**가
됩니다. 검증에서 오차가 감당 못 할 만큼 커지는 거리를 찾아 그 값을 `camera_max_range_m`으로
잡으십시오. 그 너머는 `None`(미상)으로 나가며, **미상은 통행 가능이 아닙니다.**

## 파라미터 기록

측정이 끝나면 `config/camera.yaml`에 넣습니다.

```yaml
camera_detect_node:
  ros__parameters:
    camera_height_m: 0.0        # 실측 렌즈 높이 (m)
    camera_pitch_rad: 0.0       # 하향 피치 (rad)
    camera_focal_px: 0.0        # 운용 해상도에서의 fx (px)
    camera_principal_x: 0.0     # cx (px)
    camera_principal_y: 0.0     # cy (px)
    camera_max_range_m: 0.0     # 신뢰 범위 (m). 그 너머는 미상
```

여섯 값이 모두 유효해야 거리 보고가 켜집니다. 하나라도 0이거나 비정상이면 전체가 꺼지고
`distance_m: null`로 되돌아갑니다 — 부분적으로 맞는 캘리브레이션은 없느니만 못하기 때문입니다.

## 선택형 ChArUco/호모그래피 프로필

기존 핀홀 모델 대신 검증된 이미지→지면 행렬을 쓰려면 `camera.yaml`에서 모드를 명시적으로
바꿉니다. 기본값은 기존 동작을 보존하는 `pinhole`입니다.

```yaml
camera_ground_mode: homography
camera_homography_path: /var/lib/rosy/camera/ground-profile.json
camera_homography_enabled: false
camera_homography_allow_uniform_resize: false
camera_homography_max_fit_rmse_cm: 0.8
camera_homography_max_validation_rmse_cm: 1.0
camera_homography_max_validation_error_cm: 2.0
camera_homography_min_validation_points: 8
camera_homography_min_validation_frames: 2
camera_homography_min_validation_span_cm: 10.0
camera_homography_max_range_m: 0.6
```

대시보드의 `카메라 지면 거리 보정 사용` 스위치는 현재 세션에서만 `enable`/`disable`을 보냅니다.
재부팅 기본값을 바꾸려면 검증 기록을 검토한 뒤 YAML을 의도적으로 수정해야 합니다.

### 프로필 필수 구조

```json
{
  "version": 3,
  "status": "validated",
  "method": "charuco_ground_homography",
  "image_size": [320, 240],
  "processed_rotate_deg": 180,
  "camera_profile_revision": "camera-profile-v1",
  "intrinsic_calibration": {
    "revision": "ov5647-intrinsic-v1",
    "image_size": [320, 240],
    "distortion_model": "opencv_plumb_bob",
    "points_undistorted": true
  },
  "image_to_ground_homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  "coordinates": {
    "x": "board-relative lateral right; NOT robot lateral",
    "y": "forward floor distance from camera ground projection, cm"
  },
  "reference_frames": [
    {"image": "fit-01.jpg", "pixel_points": [[0, 0]], "ground_points_cm": [[0, 0]]}
  ],
  "validation_frames": [
    {"image": "holdout-01.jpg", "pixel_points": [[0, 0]], "ground_points_cm": [[0, 0]]}
  ],
  "physical_validation": {
    "square_size_measured": true,
    "board_flat": true,
    "camera_mount_locked": true,
    "robot_forward_axis_checked": true
  }
}
```

예시는 필드 모양을 보여줄 뿐이며 단위행렬이나 한 점으로는 절대 통과하지 않습니다. 런타임은 파일의
`fit_rmse_cm`을 신뢰하지 않고 모든 대응점을 다시 투영해 오차를 계산합니다. `validation_frames`의
파일 이름은 `reference_frames`와 달라야 하고 설정한 최소 점 수, RMSE, 최대 오차를 모두 통과해야 합니다.
독립 사진 수와 검증 전방 거리 폭도 각각 설정한 최소값을 넘어야 하므로, 같은 거리의 한 사진을
복제하거나 좁은 구간만 잘 맞춘 프로필은 활성화되지 않습니다.

### 화면 체크박스의 의미

다음 항목은 조작 체크박스가 아니라 노드 판정의 읽기 전용 표시입니다.

- 프로필 로드
- 해상도·회전·카메라 프로필 일치
- 내부 보정 리비전·왜곡 제거점 계약
- 행렬·참조점 오차
- 독립 검증점 오차
- 보드·바닥·마운트·로봇축 물리 확인

자동 검사 실패를 사람이 체크해서 통과시키는 우회는 없습니다. `board-relative` X는 전방 Y 거리만
사용하고 좌우 로봇 좌표는 항상 미상으로 둡니다. 좌우 거리가 필요하면 보드를 `base_link`에 정렬한
별도 검증과 그 좌표계 계약이 필요합니다.

### 제공된 640x480 값의 현재 판정

제공된 `two_photo_checker_ground_homography`는 `status`가
`approximate_requires_physical_validation`이고, 현재 처리 영상은 320x240/180도입니다. 균일 1/2 축소는
옵션으로 지원하지만, 보정 당시 회전과 `camera-profile-v1` 결합 정보, 독립 검증 사진, 물리 확인이
없으므로 현재 값은 **후보 표시만 가능하고 활성화 불가**입니다. 또한 X가 보드 기준이라고 명시되어
있어 로봇 좌우 여유에는 사용하지 않습니다.

## 섀시를 건드렸다면

카메라 마운트를 조정했거나 떨어뜨렸다면 높이와 피치를 다시 재십시오. 피치 민감도가 지배적이라
눈에 안 보이는 정도의 변화도 원거리 추정을 망칩니다.
