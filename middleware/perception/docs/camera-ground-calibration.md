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

## 기본 경로: 자동 카메라 보정

수동으로 렌즈 높이를 재거나 피치를 입력하는 절차 대신 카메라·LiDAR·오도메트리를 자동 수집하고
설치된 `camera_extrinsic` 계산기로 피치·롤·높이 후보를 구합니다. 보정용 운전 모드로 전환하지 않습니다.
이 명령은 읽기 전용 센서 구독만 하며 모터 명령이나 모드 변경을 보내지 않습니다.

```powershell
python tools/calibration/camera_auto.py --robot rosy-pinky-9dfk --output X:/DevTemp/camera-auto/run-01.json
```

`--robot`은 미리 등록된 SSH 별칭입니다. 호스트 키를 엄격히 검증하고 대화형 로그인을 시도하지 않습니다.
`--output`은 새 파일이어야 하며 기존 보정·증거를 덮어쓰지 않습니다. Windows 검증 출력은 X:에 둡니다.

이 맞춤은 최초 주행 전, 로봇이 정지해 있고 `/camera/controls`가 `exposure=` 또는 `v4l2 exposure=`로 잠긴 뒤에 한 번 합니다. 잠기기 전에는 거절합니다. 후보는 그때의 잠금 문구와 선명도 0, 노이즈 감소 Fast를 `image_controls`에 적습니다. 주행에 쓰는 선명도가 그 값입니다. 나중에 노출만 다시 잠겨도 피치·높이·선명도는 이 후보를 다시 맞추지 않습니다.

로봇이 정지한 상태에서 카메라와 LiDAR에 같은 트랙 벽의 접지점·상단이 보여야 합니다.
한 번의 수집은 약 4초이며 최소 10개 scan과 5개 frame이 필요합니다. 오도메트리가 0.25초 이상
오래되거나 이동·회전·드리프트가 검출되면 계산을 거부합니다. 카메라·scan 수신도 0.5초 이내여야 합니다.

출력의 `verdict`는 다음 뜻입니다.

- `REJECTED`(종료 코드 2): 수집 조건 또는 기존 계산기의 품질 조건 미달. 이유를 보고 더 좋은 관측으로 재시도합니다.
- `CANDIDATE`(종료 코드 0): 기존 계산기가 추천하는 후보. `applied: false`이며 런타임을 바꾸지 않습니다.

`height_source: base`는 높이를 영상으로 결정하지 못했다는 뜻입니다. 단일 정지 시점에서는 높이와
피치를 분리하지 못할 수 있습니다. `lidar_mount_source: URDF_NOMINAL_NOT_MEASURED`도 실측이 아닌
출발값입니다. `fx/cx/cy`와 렌즈 왜곡은 기존 프로필을 사용하며 이 명령이 내부 보정을 새로 추정하지 않습니다.
벽 기준점이 부족한 후보를 자동 승인하거나 NOMINAL을 측정 완료로 바꾸지 않습니다.

유효 후보의 적용·롤백은 [D-47 보정 저장소](../../../docs/adr/D-47-core-sensor-adapter-calibration-binding.md)의
버전 기록 경로를 따릅니다. 자동 계산과 적용은 별개이며, 현재 명령은 적용하지 않습니다.
NOMINAL 추종의 진행 확인, 장애물 정지, 일반 보정 작업의 소유권 잠금은 그대로 유지합니다.
사용자의 수동 카메라 수치 입력 없이 계산할 수 있다는 뜻이지 자동 주행 수용을 뜻하지 않습니다.

### 바닥 체커보드로 자동 자세 추정

서로 다른 위치에서 촬영한 체커보드 영상 두 장과 인쇄된 칸 크기로 높이·하향각을 자동 계산합니다.
카메라 높이나 각도를 직접 입력하지 않습니다. 판에 붙인 보드라면 표면 높이를 더해야 하며,
두께를 추정했다면 `--board-elevation-estimated`로 표시합니다. 모르면 두께 옵션을 생략합니다.

```powershell
python tools/calibration/camera_board.py --reference X:/DevTemp/board/near.png --validation X:/DevTemp/board/far.png --camera-profile middleware/apps/device/pinky/profile/config/camera_nominal.yaml --square-mm 17 --board-elevation-mm 1 --board-elevation-estimated --output X:/DevTemp/board/candidate.json
```

원본 픽셀 재투영 오차와 두 영상의 자세 일치도를 검사합니다. 종료 코드 0은 이 일치도 검사를
통과했다는 뜻이며 적용·수용 완료가 아닙니다. 기존 내부값을 사용하고 왜곡을 0으로 가정하므로
새 내부 보정으로 취급하지 않습니다. 결과는 항상 후보이며 자동 적용하지 않습니다.
영상·프로필 해시와 내부 행렬, 두께 출처를 결과에 기록합니다.

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

카메라 마운트를 조정했거나 떨어뜨렸다면 자동 보정을 다시 실행하고 새 후보의 품질을 확인하십시오.
피치 민감도가 지배적이라 눈에 안 보이는 정도의 변화도 원거리 추정을 망칩니다.
