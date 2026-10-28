# 좁은 공간의 카메라 교정 워크숍 (D-636)

이 도구는 촬영한 표적으로 렌즈 후보를 계산하고 검증한다. 기존 `tools/calibration/camera_board.py`는 이미 주어진 내참수로 로봇 전방 카메라 자세를 구한다. 여기서는 렌즈 내참수 자체를 구하며, 천장 카메라와 전방 카메라는 별도 source·촬영 조건·후보를 사용한다. 운영 tracking record나 로봇 명령을 자동 변경하지 않는다.

## 표적과 촬영

사이트 Vision 컨테이너에서는 패키지 실행 파일을 PATH에 설치하지 않으므로 아래 명령의 `rosy-camera-calibrate`를 `python3 -m rosy_vision.camera_calibration`로 바꿔 실행한다. ROS 패키지 설치본에서는 기존 실행 파일을 사용한다.

`rosy-camera-calibrate target --output <new-output-dir>`는 AprilTag 36h11의 3×3 판을 생성한다. 기본 태그의 검은 테두리 포함 한 변은 30 mm, 간격은 태그 크기의 0.3배, 흰 여백은 grid pitch 하나이다. 전체 SVG는 186×186 mm다. PNG는 미리보기이며, SVG를 100%로 인쇄하고 태그 한 변과 가로·세로 전체 길이를 다시 실측한다. 평평하고 단단한 판을 사용한다. 프린터의 자동 맞춤으로 크기가 바뀌면 manifest의 실측값을 고쳐 새 후보를 구한다.

더 작은 공간에서는 입력 JSON `{"rows":2,"cols":2,"tag_size_m":0.03,"spacing_ratio":0.3,"first_id":0}`을 `target --input <grid.json>`에 준다. 이 판은 147×147 mm다. 최소 세 개의 완전한 태그가 보여야 하므로 잘린 태그나 두 태그만 보이는 영상은 사용하지 않는다. 판 일부만 보이는 관측은 완전히 보이는 태그의 ID로 대응한다. [Kalibr 공식 표적 안내](https://github.com/ethz-asl/kalibr/wiki/calibration-targets).

판이 작아도 천장 카메라에서 태그가 몇 픽셀뿐이면 사용할 수 없다. 도구는 검출된 최소 태그 변이 24 px보다 작으면 `tag_pixels_low`로 추가 촬영을 권한다. 이 값은 수집 안내 기준이며 정확도 보증이 아니다. 태그를 키우거나 가까이 촬영해야 한다. 가까이 촬영하면서 렌즈나 초점·줌·해상도·크롭·회전·손떨림 보정 상태를 바꾸면 다른 교정 조건이 된다.

카메라 입력을 고정하고 판을 중앙·가장자리·모서리와 서로 다른 기울기에 배치해 촬영한다. 기본 최소치는 학습 8장, 독립 검증 2장이다. 최소 장수만 채워도 정확도가 보장되지는 않는다. 같은 원본을 두 집합에 재사용하면 SHA-256 중복으로 거부한다. 판은 렌즈 측정용이므로 꼭 바닥에 둘 필요가 없다. 바닥과 지도 위치 등록은 별도 측량이다.

## 측정 후보

다음 manifest를 원본 영상과 함께 준비한다. 경로는 manifest 위치 기준이다. `capture_signature`에는 렌즈·고정 초점·줌·출력 해상도·crop·회전·안정화 조건을 기록한다. 설정이 같다는 사실은 사람이 확인해야 하며, 도구가 문자열로 하드웨어 상태를 검증하는 것은 아니다.

```json
{
  "source_id": "camera-source",
  "capture_signature": "standard-fixed-focus-640x480-no-crop-rotation0-no-eis",
  "grid": {"rows":3,"cols":3,"tag_size_m":0.03,"spacing_ratio":0.3,"first_id":0},
  "training": ["train01.png", "train02.png", "train03.png", "train04.png", "train05.png", "train06.png", "train07.png", "train08.png"],
  "validation": ["check01.png", "check02.png"]
}
```

`rosy-camera-calibrate fit --input <manifest.json> --output <new-fit-dir>`는 Brown pinhole과 OpenCV fisheye를 비교한다. 독립 영상에는 내참수를 다시 맞추지 않고 판 자세만 추정해 재투영 잔차 RMS/p95/max(px)를 계산한다. 가장자리 관측·기울기 다양성 부족을 경고한다. 수치 잔차는 실물 지도 오차(cm)가 아니다. 모델 실패는 실패로 기록하고, 후보는 항상 `applied:false`다. [OpenCV fisheye 모델](https://docs.opencv.org/4.13.0/db/d58/group__calib3d__fisheye.html).

`preview --input <pinhole.json-or-fisheye.json> --image <raw.png> --source-id <same-source> --capture-signature <same-signature> --output <new-preview-dir>`는 원본, 보정 영상, 유효 픽셀 mask와 관측 비율을 출력한다. 후보의 source·촬영 조건·이미지 크기가 다르면 거부한다. 보정 후에도 촬영되지 않은 곳은 원본으로 채울 수 없다.

## 바닥과 지도 등록

렌즈 후보로 보정한 영상에서 실제 측량한 바닥 anchor를 찍는다. 독립 check point는 anchor와 다른 위치에 두고, 동일한 판 추정이나 기존 H로 계산한 좌표를 실측으로 쓰지 않는다. JSON 필드는 `lens_candidate`(상대 파일 경로), `map_id`, `pixel_space:"undistorted"`, `pixels`와 대응 `metres`, `check_pixels`와 대응 `check_metres`다. anchor 최소 4개, 비공선 독립 check 최소 3개다.

`floor --input <floor-measurements.json> --output <new-floor-dir>`는 USAC_MAGSAC으로 등록한다. 2 cm inlier 기준은 후보 생성용이며 현장 허용 오차가 아니다. independent p95/max(m)를 보고하되 자동 승인하지 않는다. 허용 오차는 실제 로봇 크기·차선 폭·거리·측량 오차에 맞춰 별도로 판단한다.

`plane --input <lens.json> --floor <floor.json> --image <raw.png> --source-id <same-source> --capture-signature <same-signature> --bounds <min-x> <min-y> <max-x> <max-y> --output <new-plane-dir>`는 지도→보정 ray→원본 픽셀을 한 번에 remap한다. 출력 400 px/m, 각 변 최대 1920 px다. raw-pixel H를 렌즈 보정 뒤에 재사용하지 않는다. lens revision이 다르면 새 바닥 등록이 필요하다.

알려진 2D 지도를 그리는 것은 관측과 독립이다. 도면·저장 프로필·차선 규칙·축구장 치수로 카메라 밖의 지도도 표시할 수 있다. 현재 로봇 위치는 별도 신선한 관측이나 승인된 odom 연결이 있어야 한다. 운영 map plane의 hatch와 `X-Frame-Observed-Fraction`은 영상에 채울 수 있는 원본 픽셀만 나타내며, 가려짐이나 위치 정확도는 나타내지 않는다.

## 판단이 어려울 때

`fit`는 좌표·원본 경로·인증정보가 없는 `ai-request.json`을 만든다. 측정 실패에도 검토 필요 요청을 남기며 종료 코드는 2다. AI 또는 사람이 허용된 촬영·검토 권고와 설명만 JSON으로 답할 수 있다:

```json
{"recommendations":["move_target_to_edges","vary_target_tilt","collect_validation"],"explanation":"가장자리와 독립 검증 자료를 보강하세요."}
```

`advice --input <reply.json> --output <new-advice-dir>`는 형식을 검사하고 `needs_human_review:true`로 저장한다. 모델이 계수·좌표·명령·승인을 반환하면 거부한다. 원격 provider를 자동 호출하거나 응답을 운영에 적용하지 않는다. 미응답이어도 기준 지도와 측정 상태는 유지된다. 기존 Situation 사건 판단은 사건·두 카메라·안전 계약에 묶여 있으므로 이 교정 검토와 합치지 않는다.

출력 디렉터리는 새 경로여야 하며 기존 결과를 덮어쓰지 않는다. 개발용 생성물·로그는 $ROSY_SCRATCH의 관리된 세션에 둔다. 실측 수용은 실제 표적 영상, 독립 측량, 고정 카메라 상태와 현장 지도 readback이 필요하다.

## 승인 가능한 묶음과 설치 화면 (D-775)

`bundle --input <bundle-input.json> --output <new-bundle-dir>`는 기존 report와 floor 후보를
검증해 `bundle.json`을 만든다. 입력의 `report`, `floor`는 입력 파일 기준 상대 경로다.
`context`는 다음 필드를 모두 포함한다.

```json
{
  "report": "fit/report.json",
  "floor": "floor/floor.json",
  "context": {
    "map_revision": "활성 지도의 sha256",
    "survey_digest": "독립 바닥 측량 원본의 SHA-256",
    "capture": {
      "signature": "fit과 같은 고정 촬영 조건",
      "lens": {"kind":"standard", "focal_mm":5.4, "hfov_deg":66.9},
      "rotation_deg": 0
    },
    "bounds_m": [-1.4, -0.63, 1.4, 0.63],
    "evidence_kind": "measured"
  }
}
```

위 문자열은 설명용 자리표시자다. 실제 sha256과 촬영 조건을 사용한다. 합성 자료는
`evidence_kind:synthetic`으로 남긴다. 숫자와 digest 검증은 측량의 진실성을 인증하지 않는다.
실측 주장을 하는 운영자는 원본·측량·독립 check point를 함께 검토해야 한다.

Fleet에는 기존 sighting source 설정과 영속 `--sightings-db`, 현재 활성 지도가 필요하다.
메모리 전용이면 화면에 그렇게 표시되며 재시작 뒤 보존되지 않는다. Vision은 기존
`--track` config 동기화를 사용하고 Fleet과 같은 preview 서명 키로 direct preview를 제공한다.
이 절은 장치에 접속하거나 배포하라는 명령이 아니다.

설치 화면의 **카메라 설치·보정 → 실측 교정**에서 source를 선택하고 묶음을 가져온다.
지도·독립 오차를 검토한 뒤 p95/최대 허용 오차를 직접 입력하고 이름 있는 운영자로
승인한다. **저장됨**은 DB 선택 결과이며, 현재 연결의 촬영 조건을 확인하고 지도로 그린
영상이 돌아와야 **Vision 적용 중**이 된다. viewer는 이미 확인된 영상만 읽는다.

카메라 재접속, 렌즈·JPEG 크기·회전 변경은 재확인을 요구한다. 지도·승인 revision 변경,
철회, 설정 갱신 5초 만료 때 옛 결과를 사용하지 않는다. 화면/source 전환은 진행 중인
읽기를 폐기한다. 철회는 기대 revision이 일치할 때만 성공한다. 충돌하면 새 저장 기록을
다시 읽고 판단한다. 이 승인은 미리보기 전용이며 높은 로봇 마커의 위치 sighting이나
주행 허가로 사용할 수 없다.
