# Pinky 네이티브 런타임: motor 벤치에서 SLAM 맵핑까지

이 문서는 Ubuntu/systemd 릴리스에 적용한다. `runtime-mode.sh`와 Docker Compose는
레거시 개발 경로다. 장치 주소와 계정 토큰, 실제 G4/G5 원시 자료는 공개 저장소에
적지 않는다. 원격 작업 파일은 작업 PC의 `$ROSY_SCRATCH/`에 둔다.

Rosy Cam은 원격 명령·관찰 담당자의 현장 시야로 사용할 수 있다(D-521).
G4 schema v2와 G5는 별도 현장 담당자 없이 진행할 수 있다. 영상·프레임 나이·
로봇 신원·이동 여유·기존 정지 경로를 확인할 수 없으면 HOLD로 멈춘다.
카메라 프레임은 아래 원시 odom 정지 계측이나 승인 파일을 대신하지 않는다.

## 1. 현재 상태 판정

읽기 전용으로 장치의 `boot_id`, `/opt/rosy/current` 릴리스, 다음 값을 함께 확인한다.

```bash
sudo -n grep -E '^ROSY_(ROBOT_NUMBER|RUNTIME_MODE|NAVIGATION_BACKEND|IO_DRIVE_ENABLED)=' /etc/rosy/runtime.env
systemctl is-active rosy-core rosy-io rosy-navigation
sudo -n ls -l /etc/rosy/approvals
sudo -n find /var/lib/rosy/commissioning -maxdepth 3 -type f
```

`motor` + `drive=true`는 G4 제한 제어다. LiDAR 프로세스나 옛 `map_id`가
보여도 SLAM 실행을 뜻하지 않는다. G4의 제한 수동 운전은 motor 모드에서
CORE·IO·odom·E-Stop과 단일 최종 `cmd_vel` 발행자를 확인한다. SLAM/Nav2는
G4의 선행 조건이 아니다. G5 맵핑 전에는 `ros2 node list`에서
`slam_toolbox`, Nav2 controller, 양쪽 costmap을 확인하고
`/api/v1/navigation/state`의 필수 readiness를 읽는다. `cmd_vel`은
`ros2 topic info /<namespace>/cmd_vel -v`에서 CORE 발행자 하나여야 한다.

`navigation.readiness.required=true`를 유지한 motor 커미셔닝은 명시적인
`navigation.readiness.profiles.motor: [motor_adapter]`를 사용한다. 이 profile이 없거나
모터 어댑터 항목이 없으면 설정 오류로 중단하며, localization/SLAM profile로 대체하지 않는다.
hardware 모드는 기존 backend별 Nav2·위치 추정 요구를 그대로 사용한다. 서명 payload 갱신 뒤
기존 G4 봉인이 source/release 불일치로 무효가 되면 motor 모드에서 새 원시 G4를 획득한다.
readiness를 끄거나 승인 없이 Nav2를 먼저 올려 이 순서를 피하지 않는다. 원시 odom·현장 시야·
단일 publisher 확인은 G4/UI의 관측 조건이며 범용 CORE teleop의 추가 odom 차단 조건을 뜻하지 않는다.

## 2. G4: 제한된 지면 이동과 정지 수용

원격 조작자가 Rosy Cam 시야와 기존 정지 경로를 확인한다. `test_surface=floor`를 기록하고 각 시험에서
누적 이동 길이 10 cm, 선속도 0.03 m/s, 각속도 0.10 rad/s를 넘지 않는다.
바퀴를 들어 올린 배치도 `test_surface=lifted`로 기록할 수 있다.
schema v2에서는 전진·후진·좌회전·우회전의 버튼 해제 정지와 전진의
명령 소실 정지를 각 한 번씩, 총 다섯 번 실시한다. 기존 schema v1 기록은
8개 시험과 별도 검토자 조건으로 계속 검증한다.
각 시험은 시작 전 `motor/ready`, `odom`, E-Stop과 단일 최종 publisher를 읽고
대시보드의 홀드 제어로 최저 속도를 준다. 네 방향에서는 버튼 해제 순간,
전진 추가 시험에서는 명령 소실 순간부터 오도메트리의 지속 0 도달 시간을
기록한다. 각각 0.65초 이내여야 한다.
예상 밖 방향·진동·소음·ID 유실 또는 정지 실패는 즉시 기존 정지 경로를 사용하고 G4를 HOLD로
남긴다. 시험당 원시 odom과 명령 시각, 중지 시각, 결과를 서로 다른 파일로 보존해
네이티브 G4 번들과 해시 목록을 만든다. 한 번의 정상 전진이나
API의 `accepted` 응답만으로 G4를 완료하지 않는다.

새 번들은 `mapping_approval.py`의 `schema_version=2` 형식을 따른다.
`robot_number`, `release_id`, `source_revision`, `operator`,
`test_surface=floor|lifted`, `motor_preflight`의 파일명·SHA-256,
`trials` 5개의 방향·정지 원인·파일명·SHA-256을 기록한다.
사전 점검 원시 JSON은
`configured_ids`와 `responded_ids`가 `[1,2]`이고 `torque_free=true`여야 한다.
각 시험의 원시 JSON에는 `direction`, `stop_cause`, `requested_linear_mps`,
`requested_angular_rps`, `stop_requested_at`, `samples`를 둔다. 각 샘플은 같은
단조 시간축의 `t`, `linear`, `angular`, odom `x`, `y`, `yaw`를 담는다.
중지 전 실제 운동, 중지 후 지속 0 속도, 오도메트리 방향과 누적 이동 길이를 검증한다.
원시 파일은 현장 측정에서 가져오고 서명 릴리스와 장치 ID를 별도 readback한다.

## 3. 승인과 네이티브 전환

G4 레코드와 장치 readback, 서명 릴리스가 같은 장치/세대임을 확인한 뒤
`motor` 모드에서 다음 명령으로 봉인한다. 이 도구 자체는 주행을 명령하거나
자료를 채집하지 않는다. 채집과 봉인을 한 번에 하는 제품 경로는 로그인한 운영자의
`/api/v1/navigation/approval` API와 작업 준비의 항법 재승인 카드다(D-986). 아래 명령은 그 경로를
쓸 수 없을 때의 수동 절차다.

```bash
sudo -n python3 -B /opt/rosy/native-runtime/mapping_approval.py approve \
  --bundle /var/lib/rosy/commissioning/g4.bundle.json \
  --evidence-dir /var/lib/rosy/commissioning/g4-evidence
```

명령은 현재 장치·릴리스, 5개 시험의 속도·방향·정지 지연·원시 해시를 검증하고
`hardware.approved`와 `navigation.approved`를 마지막에 생성한다.
`rosy-navigation.service`는 기동마다 봉인된 원시 자료와 두 승인 기록을 다시
검증한다. **내용 없는 marker를 시험 대신 만들지 않는다.** 검토와 설정 변경 전에는
`/etc/rosy/runtime.env`를 장치에서 백업한다.

`/etc/rosy/runtime.env`는 A/B 정규 투영 파일이다. `sed`·편집기로 직접 고치면 다음
`rosy-sd-provision`이 `OS_STATE_HOLD`로 막고 CORE가 뜨지 않는다(2026-11-03·11-04 두 번
재현). 값은 `os_state_config.commit_runtime`으로만 바꾸고 `os_storage_dispatch.py
--projected`가 `PROJECTED`인지 확인한다. 절차와 실패 문구는
[solutions/deployment](../solutions/deployment/native-hardware-mode-profile-and-canonical-runtime-env-2026-11-03.md)에
있다. 서명 payload 안 파일(예: `nav2_params.yaml`)도 같은 이유로 고치지 않는다
([payload 편집 lesson](../solutions/deployment/release-payload-hand-edit-bricks-boot-gate-2026-11-04.md)).

다음 전환은 G4 수용 후 현장 감독 아래에서만 한다. `rosy-navigation.service`는
`rosy-io.service`와 `Conflicts=` 관계이며 기본 target에는 없다. 따라서
`commit_runtime`으로 `ROSY_RUNTIME_MODE=hardware`, `ROSY_NAVIGATION_BACKEND=slam`,
`ROSY_IO_DRIVE_ENABLED=true`를 넣고, `rosy-io`를 내린 후 CORE와 navigation을 순서대로
시작한다. 각 단계에서 `systemctl` 결과, 실제 ROS graph, SLAM lifecycle,
최신 `/scan`·`/odom`, readiness, 단일 publisher와 최종 0 속도를 확인한다.
조건이 실패하면 navigation을 내리고 이전 설정으로 복귀한다. 설정만 바꾸거나
마커만 생성한 사실은 장치 동작 증거가 아니다.

이 `ExecCondition`은 네이티브 이미지 소속 unit에 들어간다. 기존 설치 장치는
새 서명 이미지 또는 기록된 벤치 설치로 unit·승인 도구를 함께 갱신하고
파일 해시와 `systemd-analyze verify`를 읽어 확인한다. 봉인 도구가 릴리스
payload에만 들어갔다고 unit이 갱신된 것으로 취급하지 않는다.

옛 frozen OS의 `rosy-os-update.service`가 `Wants=rosy-io.service`를 포함하면
업데이트 없음 점검도 I/O를 시작해 항법을 중지시킨다. 감독 시험 전에 frozen 제어기의
`status`에서 pending 없음과 업데이트 service 비실행을 확인하고, 기존 타이머 활성 상태를
기록한 뒤 시험 동안 타이머만 정지한다. 진행 중인 업데이트를 중단하지 않는다.
시험 종료 시 항법 정지·최종 0·원래 runtime 복귀를 먼저 확인하고, 원래 활성 상태였던
타이머를 다시 시작한다. 이는 임시 복구다. 영구 수정의 frozen OS 배포 경계와
회귀 근거는 [해결 기록](../solutions/deployment/os-update-poll-starts-conflicting-io-2026-11-05.md)을 따른다.

## 4. G5: 짧은 바닥 맵핑

확보된 구역에서 실제 크기와
여유 공간, 속도·시간 한계, 중단 조건을 먼저 기록한다. E-Stop을 유지한 채
SLAM/Nav2와 LiDAR가 준비된 것을 확인한 뒤 운영자가 해제한다. CORE의
`/api/v1/slam/start` 응답 이후에도 `/map` 갱신, scan/odom/TF와 최종 `cmd_vel`을
관찰한다. 짧은 수동 홀드 이동으로 맵을 만들고, 지도 YAML/PGM 및 MCAP을
저장·해시한다. `/api/v1/slam/stop`, 최종 0 속도와 E-Stop을 확인한다. 지도 파일,
실측 변위와 정지 자료가 없으면 G5는 HOLD다. 첫 실물 맵을 데모 맵 ID와 혼동하지
않는다.

**2026-11-04 벤치 관찰 (release 2026.10.29-001):** `/api/v1/slam/start`는
`HARDWARE_NOT_READY: missing_or_stale:controller_server,local_costmap,global_costmap`로
막힌다. Nav2 합성 노드가 올라오지 않는 릴리스 결함이며 수정은 릴리스 작업이다. 세션이
서지 않으므로 `/api/v1/slam/save`는 400 `no active mapping session`을 돌려준다. 이
상태에서 주행한 맵을 잃지 않으려면 slam_toolbox를 직접 띄워 두고 주행한 뒤 서비스로
저장한다.

```bash
ros2 service call /$ROSY_NAMESPACE/slam_toolbox/save_map slam_toolbox/srv/SaveMap \
  "{name: {data: '/var/lib/rosy/maps/<id>'}}"
```

2026-11-04 같은 장치에서 `result=0`과 `/var/lib/rosy/maps/<id>.{yaml,pgm}`
(rosy-io:rosy-core, resolution 0.05) 생성을 확인했다. 이 경로는 CORE를 거치지 않으므로
`map_id`·`map.saved` 이벤트가 남지 않는다. 수용 증거로 쓸 때 그 사실을 함께 적는다.

**2026-09-27 KST(2026-09-26 UTC) 진단:** 바퀴를 든 전진 1회는 약 0.53초 명령과 0 명령 후 약
0.43초의 API 0 속도 관찰, 약 0.026m 오도메트리 변화 및 현장 정상 방향 관찰을
얻었다. G4의 나머지 시험, 승인 마커, navigation 실행과 G5 맵 산출물은 없었다.
이 수치는 G4/G5 수용 값이 아니다.

**2026-11-04 KST 운영자 메모 — 후진 목표:** `allow_reversing`이 참이면
Nav2 목표로 후진 이동이 가능하다. 이때 **목표 yaw는 현재 yaw 그대로** 보낸다.
목표 yaw를 현재 yaw + π로 보내면 "뒤돌아 서기" 목표가 되어 `rotate_to_heading`이
제자리 회전을 먼저 수행한다(geg6 실측: 회전 중 LiDAR 전방거리 급변, AMCL 믿음
자세 점프, STUCK). yaw 유지 + 후방 15cm 목표는 회전 없이 순수 후진
0.069m로 `SUCCEEDED`([검증 기록](../validation/nav2-reversing-goal-2026-11-04/result.md)).
`xy_goal_tolerance` 0.10 안에서 멈추므로 실제 변위는 5–8cm가 된다.
