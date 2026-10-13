# 카메라 자동 보정 실기 결과

사용자는 수동 보정 대신 자동 보정을 요청했고, 대상이 카메라라고 명확히 했다.
`feat/camera-auto`는 수동 높이·피치 측정 안내를 자동 정지 수집·계산 명령으로 교체한다.
기존 일반 보정 세션은 카메라 수치 입력 모드가 아니라 동시 작업 소유권 잠금이므로 유지한다.

## 구현

- `tools/calibration/camera_auto.py`: 등록된 pinned SSH 별칭을 사용한다. 새 JSON 증거를 저장하며 Windows는 X:/DevTemp 안으로 제한한다. 기존 파일은 덮어쓰지 않는다.
- `camera_capture.py`: 읽기 전용 ROS 구독, 이동·모드·보정 적용 명령 없음. 카메라·LiDAR·오도메트리의 타임스탬프 나이·0·반복·역행, 이동·드리프트, scan 기하 일관성, quaternion을 검사한다.
- 설치된 `control.calibration_camera.run_camera_extrinsic`을 사용한다. URDF nominal 기하를 읽으며 실측 LiDAR mount로 꾸미지 않는다.
- 기존 계산기가 추천하지 않은 후보는 REJECTED(종료 코드 2), 추천 후보도 CANDIDATE이며 `applied: false`다. 자동 계산과 런타임 적용을 구분한다.
- 내부 초점거리·렌즈 왜곡을 새로 추정하는 기능이나 자동 승인·FIELD 수용은 추가하지 않았다.

## 실제 장치

대상 9dfk, 설치된 런타임은 `2026.10.05-042`, source `07dc89f20d681e581277d84d3cd38ebd7ddffea7`.
이 PC 도구의 코드를 pinned SSH stdin으로 보내 실행했다. 릴리스 파일·설정·장치 보정 저장소는 바꾸지 않았다.

09:01:20 UTC 강화된 최종 worker 결과: scan 40, frame 15, odometry 121, 수집 guard fault 없음.
피치 후보 0.14835 rad, 롤 후보 -0.06109 rad. 높이 0.0634 m는 `height_source: base`이며 측정으로 결정한 값이 아니다.
벽 기준점 8개, 피치 uncertainty 0.4도·롤 2.75도·높이 0.0275 m. `recommended: false`,
사유 `too few wall returns in view`. CLI는 **REJECTED, applied false**를 저장했다.
이는 자동 보정 계산의 실행 증거이며, 보정 성공이나 자동 주행 성공 증거는 아니다.
앞선 실험 prototype은 벽 점 5개였으며 최종 worker의 결과와 섞지 않는다.

## 검증과 한계

호스트 관련 검사: 기존 보정 suite와 새 회귀, 공개 provenance 총 87 PASS, known failures 0 NEW.
독립 리뷰에서 arrival-only freshness와 동일 길이 scan 기하 혼합 문제를 찾아 타임스탬프·metadata 검사로 보완했다.
수동 측정 안내 제거와 자동 후보 계산은 구현됐다. 품질 미달 후보를 런타임에 적용하거나 NOMINAL 진행 조건을 없애지는 않았다.
현재 장면에서 자동 보정을 완료하려면 같은 벽이 카메라·LiDAR 양쪽에 충분히 보이는 관측이 필요하다.
추가 시점의 관측 없이 단일 장면의 높이·피치 분리를 보장하지 않는다.

증거: `X:/DevTemp/line-remote-20261005/camera-auto-device-final.json`, `camera-auto-final-tests.txt`,
`camera-auto-red.txt`, `camera-auto-guards-red.txt` 및 `X:/DevTemp/camera-auto-review-20261005/`.
