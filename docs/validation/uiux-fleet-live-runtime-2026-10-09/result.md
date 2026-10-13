# Fleet 현장 로봇 위치·SLAM 읽기 전용 재검증 — 2026-10-09

## 범위와 기준

- 현장 설치 후보: `af80a5b37eec` (`site-af80a5b37eec`). 이전 설치·화면 증거는 [site-install.md](../uiux-fleet-site-map-task-order-2026-10-09/site-install.md)에 있다.
- 관찰 시각: 2026-10-09 02:41 UTC 이전. Fleet은 SSH 터널을 통해 개발 연결 모드의 브라우저에서 조회했다. 로봇 두 대는 저장된 호스트 키와 장치 이름을 대조한 뒤 키 인증 SSH로 조회했다. 실제 주소, 계정, 토큰은 이 공개 기록에 넣지 않는다.
- 수행: Fleet `/api/fleet/state`, `/api/fleet/tracking`, `/api/fleet/tracking/identity`, `/api/fleet/discovery/addresses` 읽기; 각 장치의 systemd 서비스·`runtime.env` 모드·지도 및 승인 디렉터리 읽기. E-Stop 해제, 모드 변경, 로봇 이동 명령은 실행하지 않았다.

## 관찰

| 항목 | 현장 결과 |
| --- | --- |
| Fleet·Vision | 설치된 proxy·Fleet·Vision 컨테이너는 `healthy`, `/healthz` 200. Vision의 `ceiling_north` 설정 조회는 200이고 source·map·calibration이 일치했다. 추적 API는 `OK`, 약 2.7 fps, 최근 프레임, 오류 없음이었다. 한 조회에서 익명 검출 4개였으나 이름이 확인된 로봇 검출은 0개였다. |
| 로봇 연결 | `rosy_26`, `rosy_60` 모두 Fleet에 온라인이며 CORE·I/O systemd 서비스가 실행 중이었다. SSH 장치 이름은 등록된 두 로봇과 일치했다. |
| 지도 위치 | 두 로봇의 상태에 오도메트리 `pose`/`odom_pose`는 있지만 `map_id=null`, `localization=null`이다. 추적은 모두 `NO_POSE`, `camera=null`, 표시 사용처는 `display-only`였다. identity 상태는 둘 다 `UNKNOWN`, `auto_request=false`였다. 오도메트리 좌표를 현장 지도상의 로봇 위치로 해석할 수 없다(D-395, D-457). |
| 장치 실행 모드 | 두 장치의 `/etc/rosy/runtime.env`는 `ROSY_RUNTIME_MODE=motor`. `rosy-navigation.service`와 `rosy-localization.service`는 inactive, `/var/lib/rosy/maps`에는 지도 파일이 없었다. `/etc/rosy/approvals`와 `/var/lib/rosy/commissioning`은 두 장치 모두 없었다. |
| 안전·운영 상태 | Fleet 상태의 navigation 및 safety evidence는 disconnected였고, 화면에는 `rosy_26`의 배터리 근거 확인 불가 경고가 있었다. `rosy_26`의 CPU 진단도 ERROR였다. 이 판독은 현장 이동 준비 완료의 근거가 아니다. |

현장 스크린샷은 `X:/DevTemp/projects/rosy-platform/2026-10-09--site-map-task-order/site/console-live-runtime-1009.png`에 보관했다. SHA-256: `653f884a40fb0fa5c57d38edde55383ab63d603d663e4b6c344f00b2cbc274b4`. 화면의 `카메라 관측 0/0대`는 이름이 붙은 로봇 관측을 뜻한다. 추적 API의 익명 검출 개수와 구별해야 한다.

## 판정과 다음 단계

`motor`는 G4 제한 제어 모드이며 실제 SLAM/Nav2 및 지도 기준 위치를 제공하지 않는다(D-144, D-295). G4 승인·원시 계측이 없는 상태에서 `hardware + slam`으로 전환하면 [네이티브 매핑 절차](../../deployment/pinky-native-mapping-recovery.md)의 선행 조건을 건너뛴다. 따라서 지도 위 실명 로봇 위치, 경로 추종, SLAM, 물리 정지, 운영자 G3 수용은 **HOLD**다. 설치·서비스 건강·브라우저 렌더·카메라 추적 자체는 앞선 범위에서 확인됐지만 이를 이동 수용으로 승격하지 않는다.

현장 담당자는 장치별로 시야, 조명, 정지 경로, 이동 여유를 확인한 뒤 G4의 실제 방향·정지 시험과 원시 증거를 확보하고 승인해야 한다. 그다음 승인된 절차에 따라 하드웨어 SLAM을 시작해 ROS 그래프·LiDAR·MCAP·지도 YAML/PGM·map-frame localization·목표 주행·최종 E-Stop/zero velocity를 별도로 검증해야 한다. 두 장치의 신원 마커 또는 신뢰된 map pose가 생긴 뒤 Fleet 이름 대조를 다시 확인한다. 현장 사용자의 G3 평가는 그 이후 별도 수행한다.
