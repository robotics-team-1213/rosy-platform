# 스테이션 측정 카메라 구성

`rosy-vision station-vision --config private/station-cameras.json`은 설치 프로필의 카메라만 수신하고 기존 Fleet 관측 API에 후보를 보낸다. 일반 지도 표시용 `vision` 설정과 별개다. 실행 전에 패키지와 기존 런타임 의존성을 설치하고 phone/source 토큰을 각각 다른 환경변수로 제공한다. 토큰 값·실주소·현장 측정값은 gitignored private 파일에만 보관한다. 명령은 장치나 CORE capability를 활성화하지 않는다.

프로필은 strict JSON이며 최상위 `version: 1`, `sources` 배열을 갖는다. 한 스테이션의 `relative`와 `map`을 각 하나까지 설정한다. source ID는 기존 카메라 protocol의 1~32자 영문·숫자·밑줄·하이픈이다. `phone_token_env`는 WebSocket 인증, `token_env`는 Fleet source 인증에 사용하며 서로 및 다른 카메라의 값과 달라야 한다. Fleet에 같은 source ID·epoch·calibration revision·map·허용 robot 범위를 먼저 등록한다. Fleet robot credential을 이 프로필에 넣지 않는다.

각 source는 `kind`, `phone_token_env`, `token_env`, `fleet_base_url`, `max_age_s`, `lens`, `calibration`을 요구한다. 상대 관측만 `robot_id`가 필수다. `lens`와 `calibration`의 `source_id`, `source_epoch`, `revision`은 모두 같아야 한다. lens의 pinhole intrinsics/왜곡은 원본 영상에서 측정하고 marker-plane H와 고정 anchor pixel quad는 그 렌즈 보정 출력에서 측정한다. 설치 revision은 이 조합 전체를 식별한다. `approved`와 `lens_rectified`는 JSON boolean이며 자동 승인 기능이 아니다.

아래는 **합성 상대 카메라 형식 예시**다. 영 왜곡·homography·오차·치수는 실기 프로필이 아니며 현장에 복사하지 않는다.

```json
{
  "version": 1,
  "sources": [{
    "kind": "relative",
    "robot_id": "robot-1",
    "phone_token_env": "ROSY_STATION_PHONE",
    "token_env": "ROSY_STATION_SOURCE",
    "fleet_base_url": "https://fleet.example",
    "max_age_s": 0.25,
    "lens": {
      "source_id": "station-camera", "source_epoch": "camera-boot", "revision": "mount-1",
      "approved": true, "model": "pinhole", "width": 300, "height": 300, "rotation_deg": 0,
      "matrix": [300, 0, 150, 0, 300, 150, 0, 0, 1], "distortion": [0, 0, 0, 0, 0]
    },
    "calibration": {
      "station_id": "charger-1", "source_id": "station-camera", "source_epoch": "camera-boot",
      "revision": "mount-1", "marker_id": 7, "marker_side_m": 0.1,
      "marker_mount": {"x": 0.02, "y": 0, "yaw": 1.5707963267948966},
      "image_to_station": [0.001, 0, 0, 0, -0.001, 0, 0, 0, 1],
      "plane": "robot_marker", "lens_rectified": true, "approved": true,
      "uncertainty_m": 0.002, "uncertainty_rad": 0.005
    }
  }]
}
```

지도용 `kind: "map"`은 `StationMapCalibration`의 모든 필드를 사용한다. `image_to_map`은 station marker 높이에서 독립 측량한 H이며 `plane`은 `station_marker`다. `map_id/map_revision/pose_revision_hint`, `fixed_map_anchor: true`, `approach_offset_m`, 네 독립 고정 `image_anchors`와 명시적인 `max_anchor_error_px`가 필요하다. 각 anchor는 `marker_id`와 대응 순서의 네 `corners: [[x,y], ...]`를 갖는다. 고정 anchor의 중심을 볼록한 둘레 순서로 등록하고 스테이션 표식 전체가 그 범위 안에 들어오게 설치한다. 바닥 anchor를 station-marker-plane H로 투영하지 않는다. 지도 프로필에 robot/session scope를 만들어 넣지 않는다.

실행 중에는 D-774의 명시적 measurement demand를 요청하므로 화면을 닫아도 지정 카메라가 송출한다. 일반 `vision`은 D-691의 인증 미리보기 읽기/30초 규칙을 따른다. 폰의 발열 보호는 여전히 송출보다 우선한다. listener 주소·TLS cert/key는 기존 수신기 옵션을 사용한다. 설치 도구의 pinned `pair-link`를 사용하고 운영에서는 승인된 TLS/망 설정을 적용한다.

수신 frame의 크기·회전과 실제 JPEG 크기를 검사하며 자동 resize·회전 보정으로 기존 H에 맞추지 않는다. 설정의 `width` 요청만 폰에 보내므로 실제 aspect/rotation이 다르면 거절된다. 렌즈·해상도·crop·회전·마운트를 바꾸면 재측정·승인과 새 설치 revision이 필요하다. 현재 프로토콜은 카메라 하드웨어/렌즈 serial을 증명하지 않으므로 source credential의 물리 카메라 결속과 capture 설정 고정은 별도 설치 수용 항목이다.

종료 시 worker를 취소하고 measurement demand를 해제한 뒤 WebSocket과 source HTTP client를 닫는다. 프로세스 강제 종료·호스트 전원 상실은 종료 메시지를 보장하지 않으며, Fleet/CORE의 원래 관측 TTL과 fail-closed 정지 경로가 필요하다. 이 명령의 시작/종료 시험은 전체 Fleet/CORE 재시작·장애 수용이나 실기 정밀도 증거를 대신하지 않는다.
