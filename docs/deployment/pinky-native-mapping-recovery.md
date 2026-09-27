# Pinky 네이티브 런타임: motor 벤치에서 SLAM 맵핑까지

이 문서는 Ubuntu/systemd 릴리스에 적용한다. `runtime-mode.sh`와 Docker Compose는
레거시 개발 경로다. 장치 주소와 계정 토큰, 실제 G4/G5 원시 자료는 공개 저장소에
적지 않는다. 원격 작업 파일은 작업 PC의 `X:\DevTemp\`에 둔다.

## 1. 현재 상태 판정

읽기 전용으로 장치의 `boot_id`, `/opt/rosy/current` 릴리스, 다음 값을 함께 확인한다.

```bash
sudo -n grep -E '^ROSY_(ROBOT_NUMBER|RUNTIME_MODE|NAVIGATION_BACKEND|IO_DRIVE_ENABLED)=' /etc/rosy/runtime.env
systemctl is-active rosy-core rosy-io rosy-navigation
sudo -n ls -l /etc/rosy/approvals
sudo -n find /var/lib/rosy/commissioning -maxdepth 3 -type f
```

`motor` + `drive=true`는 바퀴를 든 벤치 제어다. LiDAR 프로세스나 옛 `map_id`가
보여도 SLAM 실행을 뜻하지 않는다. `ros2 node list`에서 `slam_toolbox`, Nav2
controller, 양쪽 costmap을 확인하고 `/api/v1/navigation/state`의 필수 readiness를
읽는다. `cmd_vel`은 `ros2 topic info /<namespace>/cmd_vel -v`에서 CORE 발행자
하나여야 한다. 하나라도 불명확하면 바닥 주행은 HOLD다.

## 2. G4: 바퀴를 든 상태의 정지 수용

현장 조작자와 독립 전원 차단 담당자 두 명, 바퀴를 든 받침대, 유효한 배터리 및
물리 정지 경로가 필요하다. 방향별 전진·후진·좌회전·우회전을 각각 두 번 실시한다.
각 시험은 시작 전 `motor/ready`, `odom`, E-Stop과 단일 최종 publisher를 읽고
대시보드의 홀드 제어로 최저 속도를 준다. 놓는 순간과 CORE 중지/명령 소실에서
오도메트리의 지속 0 도달 시간을 별도로 기록한다. 각각 0.65초 이내여야 한다.
예상 밖 방향·진동·소음·ID 유실 또는 정지 실패는 즉시 물리 차단하고 G4를 HOLD로
남긴다. 시험당 원시 odom과 명령 시각, 중지 시각, 결과를 서로 다른 파일로 보존해
네이티브 G4 번들과 해시 목록을 만든다. 한 번의 정상 전진이나
API의 `accepted` 응답만으로 G4를 완료하지 않는다.

네이티브 번들은 `mapping_approval.py`의 `schema_version=1` 형식을 따른다.
`robot_number`, `release_id`, `source_revision`, 서로 다른 `operator`·
`safety_operator`, `wheels_lifted=true`, `hardware_cut_reachable=true`,
`motor_preflight`의 파일명·SHA-256, `trials` 8개의 방향·정지 원인·파일명·
SHA-256·`observed_direction=true`를 기록한다. 사전 점검 원시 JSON은
`configured_ids`와 `responded_ids`가 `[1,2]`이고 `torque_free=true`여야 한다.
각 시험의 원시 JSON에는 `direction`, `stop_cause`, `requested_linear_mps`,
`requested_angular_rps`, `stop_requested_at`, `samples`를 둔다. 각 샘플은 같은
단조 시간축의 `t`, `linear`, `angular`, odom `x`, `y`, `yaw`를 담는다.
중지 전 실제 운동, 중지 후 지속 0 속도와 오도메트리 방향을 검증한다.
원시 파일은 현장 측정에서 가져오고 서명 릴리스와 장치 ID를 별도 readback한다.

## 3. 승인과 네이티브 전환

G4 레코드와 장치 readback, 서명 릴리스가 같은 장치/세대임을 검토한 독립 담당자가
`motor` 모드에서 다음 명령으로 봉인한다. 이 도구는 주행을 명령하거나
자료를 자동 채집하지 않는다.

```bash
sudo -n python3 -B /opt/rosy/native-runtime/mapping_approval.py approve \
  --bundle /var/lib/rosy/commissioning/g4.bundle.json \
  --evidence-dir /var/lib/rosy/commissioning/g4-evidence \
  --reviewer '<independent-reviewer>'
```

명령은 현재 장치·릴리스, 8개 시험의 속도·방향·정지 지연·원시 해시를 검증하고
`hardware.approved`와 `navigation.approved`를 마지막에 생성한다.
`rosy-navigation.service`는 기동마다 봉인된 원시 자료와 두 승인 기록을 다시
검증한다. **내용 없는 marker를 시험 대신 만들지 않는다.** 검토와 설정 변경 전에는
`/etc/rosy/runtime.env`를 장치에서 백업한다.

다음 전환은 G4 수용 후 현장 감독 아래에서만 한다. `rosy-navigation.service`는
`rosy-io.service`와 `Conflicts=` 관계이며 기본 target에는 없다. 따라서
`runtime.env`를 `ROSY_RUNTIME_MODE=hardware`, `ROSY_NAVIGATION_BACKEND=slam`,
`ROSY_IO_DRIVE_ENABLED=true`로 맞추고, `rosy-io`를 내린 후 CORE와 navigation을 순서대로
시작한다. 각 단계에서 `systemctl` 결과, 실제 ROS graph, SLAM lifecycle,
최신 `/scan`·`/odom`, readiness, 단일 publisher와 최종 0 속도를 확인한다.
조건이 실패하면 navigation을 내리고 이전 설정으로 복귀한다. 설정만 바꾸거나
마커만 생성한 사실은 장치 동작 증거가 아니다.

이 `ExecCondition`은 네이티브 이미지 소속 unit에 들어간다. 기존 설치 장치에는
새 서명 이미지와 SD 갱신을 완료하기 전까지 적용되지 않는다. 봉인 도구가
릴리스 payload에만 들어갔다고 unit이 갱신된 것으로 취급하지 않는다.

## 4. G5: 짧은 바닥 맵핑

확보된 구역에 로봇을 내리고 현장 전원 차단 담당자가 지켜본다. 실제 크기와
여유 공간, 속도·시간 한계, 중단 조건을 먼저 기록한다. E-Stop을 유지한 채
SLAM/Nav2와 LiDAR가 준비된 것을 확인한 뒤 운영자가 해제한다. CORE의
`/api/v1/slam/start` 응답 이후에도 `/map` 갱신, scan/odom/TF와 최종 `cmd_vel`을
관찰한다. 짧은 수동 홀드 이동으로 맵을 만들고, 지도 YAML/PGM 및 MCAP을
저장·해시한다. `/api/v1/slam/stop`, 최종 0 속도와 E-Stop을 확인한다. 지도 파일,
실측 변위와 정지 자료가 없으면 G5는 HOLD다. 첫 실물 맵을 데모 맵 ID와 혼동하지
않는다.

**2026-09-27 KST(2026-09-26 UTC) 진단:** 바퀴를 든 전진 1회는 약 0.53초 명령과 0 명령 후 약
0.43초의 API 0 속도 관찰, 약 0.026m 오도메트리 변화 및 현장 정상 방향 관찰을
얻었다. G4의 나머지 시험, 승인 마커, navigation 실행과 G5 맵 산출물은 없었다.
이 수치는 G4/G5 수용 값이 아니다.
