# Pinky Pro IR 차선 교정 런북 (D-344 §12)

**대상:** 바닥을 보는 좌·중·우 IR 세 개를 이 로봇의 카펫·흰 테이프에 맞춰 교정하고, CORE 의 IR 이탈 감시(`line_follow.ir_guard_enabled`)를 켤 준비를 한다.
**근거:** D-143(IR 증거·교정 해시), D-344 §12(카메라 + IR 두 겹 경계), D-342(수동 한도 계단).
**도구:** `middleware/perception/tools/device/ir_line_calibrate.py` — `ir_sensor/range` 를 구독만 한다. 바퀴 명령을 내지 않고 설정 파일도 쓰지 않는다. 결과 YAML 은 사람이 붙인다.

## 0. 전제

- 로봇은 손으로 옮긴다. 이 절차 동안 자동·수동 주행을 하지 않는다. 바퀴는 돌지 않아도 된다(구동 꺼짐 `drive=false` 여도 된다).
- rosy-io 가 IR 을 발행하고 있어야 한다(`bringup_robot.launch.py enable_ir:=true`, 네이티브 `rosy-io.service` 기본).
- 흰 테이프 한 조각(차선과 같은 것), 맨 카펫 한 곳. 조명은 주행 때와 같게.

```bash
ssh <alias> 'source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash && \
  ros2 topic list | grep ir_sensor && timeout 3 ros2 topic hz $(ros2 topic list | grep ir_sensor/range)'
```

약 20 Hz 가 나와야 한다. 네임스페이스가 있으면(`/<ns>/ir_sensor/range`) 아래 모든 명령에 `--topic /<ns>/ir_sensor/range` 를 붙인다.

## 1. 도구를 로봇에 올린다

도구와 교정 계산 모듈은 아직 설치 이미지에 없을 수 있다. 저장소의 `control` 패키지와 도구를 같은 배치로 임시 폴더에 복사한다(도구가 그 폴더를 `sys.path` 맨 앞에 넣는다).

```powershell
$RosyScratch = if ($env:ROSY_SCRATCH) { $env:ROSY_SCRATCH } else { [System.IO.Path]::GetTempPath() }
cd "<Rosy OS>\src\runtime\sensing"
tar -cf $RosyScratch/rosy-ir.tar control tools/device/ir_line_calibrate.py
scp $RosyScratch/rosy-ir.tar <alias>:/tmp/
ssh <alias> 'mkdir -p /tmp/rosy-ir && tar -xf /tmp/rosy-ir.tar -C /tmp/rosy-ir'
```

## 2. 네 자리 측정 (약 5 분)

```bash
ssh -t <alias> 'source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash && \
  cd /tmp/rosy-ir && python3 tools/device/ir_line_calibrate.py run --session ~/rosy-ir/session.json'
```

도구가 단계마다 물어보고, Enter 를 누르면 3 초(약 60 개) 표본을 모은다. 로봇을 놓은 뒤 손을 떼고 누른다.

| 단계 | 놓는 법 | 얻는 것 |
|---|---|---|
| carpet | 세 IR 모두 맨 카펫 위 | 채널별 검정 끝점 |
| left | 테이프를 **왼쪽** IR 밑에만 | 왼쪽 흰 끝점 |
| centre | 테이프를 **가운데** IR 밑에만 | 가운데 흰 끝점 |
| right | 테이프를 **오른쪽** IR 밑에만 | 오른쪽 흰 끝점 |

왼쪽·오른쪽은 **로봇이 앞을 볼 때** 기준이다(카메라 쪽이 앞).
한 단계만 다시 하려면: `python3 tools/device/ir_line_calibrate.py capture --phase left --session ~/rosy-ir/session.json` 뒤 `compute`.

## 2b. 손으로 놓을 사람이 없을 때 (원격, 2026-10-07 9dfk)

로봇을 몰아서 곧은 선을 비스듬히 넘기며 네 단계 표본을 얻는다. 자세한 근거와 수치는 `docs/solutions/workflow-issues/ir-line-calibration-by-guided-line-crossing-2026-10-07.md`.

- 지도(STL 도색)에서 주변에 다른 도색이 없는 곧은 구간을 고른다(260919: 서쪽 블록 남쪽 선, x ≈ −0.76 서쪽). 횡단보도·모서리 옆은 쓰지 않는다.
- 선과 약 25°, 선이 한쪽(예: 오른쪽)에서 오게 놓는다. 그러면 R → R+C → C → L+C → L 순서가 나오고 이것이 좌우 부호 확인이다.
- 6 mm 전진·1.2 s 정지를 반복하고 로봇에서 IR·odom을 20 Hz로 기록한다. 멈춤과 방향 판단은 odom이 아니라 LiDAR-벽 자세로 한다(카펫 제자리 회전은 odom이 크게 틀린다).
- 모든 이동 명령은 공유 `RobotBody` 여유 검사를 거친다(D-500). 움직이기 전에 로봇 식별과 케이블을 눈으로 확인한다.
- 정지 구간 중 카펫·한 센서만 흰색인 구간으로 세션 JSON을 만들고 `compute`를 돌린다. 적용·확인은 5·6단계 그대로다.

## 3. 판정

도구는 채널별 끝점(중앙값), 잡음(MAD), 각 단계가 어떻게 읽히는지를 보이고, 아래를 모두 통과할 때만 YAML 을 찍는다.

- 채널마다 쓸 수 있는 표본 20 개 이상, ADC 끝(0·4095)에 붙은 표본 10 % 이하.
- 테이프–카펫 차이 ≥ `min_span`(기본 100) 이고, 두 자리 잡음 합의 6 배 이상.
- 테이프를 둔 센서가 가장 크게 움직인 채널이다(아니면 채널 순서가 바뀌었거나 테이프를 잘못 놓음).
- 계산한 교정으로 되읽으면: 카펫 = 선 없음, 왼쪽 테이프 = 오차 ≤ −0.3, 오른쪽 = ≥ +0.3, 가운데 = |오차| < 0.3.

`FAIL:` 이 나오면 YAML 이 없다. 원인(테이프 위치, 센서 높이, 조명, 배선)을 고치고 해당 단계만 다시 `capture` 한다.

## 4. 좌·우 부호 손 확인 (필수)

```bash
python3 tools/device/ir_line_calibrate.py check --session ~/rosy-ir/session.json --seconds 20
```

20 초 동안 표본마다 `left / centre / right / none` 을 찍는다. 테이프를 왼쪽 → 가운데 → 오른쪽 IR 밑으로 옮기며 **표시가 테이프를 둔 쪽과 같은지** 본다. `left` 일 때 CORE 감시는 오른쪽으로 비킨다(REP-103 음의 각속도). 한 번이라도 반대로 나오면 멈추고 배선·채널 순서(`ir_adc_node` 가 좌·중·우로 내는지)를 조사한다.

## 5. 설정 적용 (사람이 붙인다)

도구가 찍은 두 블록을 쓴다. `revision` 은 두 곳에 같은 값이어야 한다.

1. `/etc/rosy/ir_calibration.yaml` — `rosy-camera` 의 `line_observer_node` 가 읽는 IR 교정 전용 덮어쓰기 파일이다(없으면 만든다, root 소유 0644). **도구가 찍은 첫 블록(`/**/line_observer_node`)만** 붙인다 — 다른 노드 블록이나 IR 교정 밖의 키가 있으면 launch 가 파일 전체를 건너뛰고 로그에 이유를 남긴다(IR_LINE 은 fail-closed 로 남는다). `/etc/rosy/line_follow.yaml` 은 내비게이션 그래프용 전체 설정이라 여기에 쓰지 않는다.
   ```yaml
   /**/line_observer_node:
     ros__parameters:
       ir_calibration_enabled: true
       ir_black: [....0, ....0, ....0]
       ir_white: [....0, ....0, ....0]
       ir_min_span: 100.0
   ```
   값은 반드시 소수점이 있는 실수로 둔다(정수면 ROS 파라미터 형이 달라 노드가 뜨지 않는다).
   A/B OS 이미지에서는 첫 블록을 `~/rosy-ir/ir_calibration.yaml`에 저장한 뒤 다음 명령으로 적용한다. 공통 설정에 기록하므로 다음 OS와 이전 슬롯으로 돌아온 OS가 같은 보정 파일을 읽는다. `/etc/rosy` 파일만 직접 바꾸면 다음 부팅의 공통 설정 투영 때 그 변경이 사라질 수 있다.
   ```bash
   sudo /usr/bin/python3 -I -B /opt/rosy/native-runtime/os_state_config.py \
     --file ir_calibration.yaml --input "$HOME/rosy-ir/ir_calibration.yaml"
   ```
   A/B 이미지에서 제거할 때도 같은 명령의 `--input ...` 대신 `--clear`를 쓴다. 기존 단일 루트 이미지는 위의 root 소유 0644 파일 적용 절차를 따른다. 이 명령은 보정 파일과 NOMINAL 참조 프로필을 공통 설정에 기록하며, 노드 설정 검증과 재시작은 아래 절차대로 확인한다. `line_observer_overrides apply/clear`와 대시보드의 차선 인식 설정은 A/B 공통 설정을 자동으로 갱신한다. NOMINAL 프로필은 `apply --profile ...` 때 overlay와 함께 보존되어 `/etc/rosy/camera_nominal.yaml`로 참조되므로, 이전 릴리스나 홈 디렉터리의 원본이 없어져도 같은 값을 읽는다. `clear`는 이 복사본도 제거한다.
2. CORE 설정 `line_follow.ir_calibration_revision: <64자리 해시>` — 네이티브 CORE 의 로컬 설정은 `/var/lib/rosy/core/.rosy/rosy.yaml`(`HOME=/var/lib/rosy/core`)이다. 기존 `line_follow:` 블록이 있으면 그 안에 한 줄만 넣는다.
3. `sudo systemctl restart rosy-camera rosy-core`.
4. `journalctl -u rosy-camera -b | grep "IR calibration overlay"` 가 `... loaded` 여야 한다. `skipped: <이유>` 면 파일을 고치고 다시 시작한다.

## 6. 적용 확인 (읽기 전용)

- `ros2 topic echo --once line/observation` 을 몇 번 해서 `"source": "IR_LINE"` 인 것이 `"ir_calibrated": true` 이고 `calibration_revision` 이 도구가 찍은 해시와 같아야 한다. 테이프를 IR 밑에 두면 `visible: true` 가 된다.
- `journalctl -u rosy-camera -b | grep "IR line calibration disabled"` 가 재시작 뒤로는 없어야 한다.
- `PUT /api/v1/line-follow/mode` 로 IR_LINE 을 고르는 것은 주행이므로 이 확인에 쓰지 않는다. 그 준비 판정(`IR_CALIBRATION_REVISION_MISMATCH` 등)은 주행 승인이 따로 있는 세션에서 본다.

## 7. 감시 켜기 (별도 결정)

차선 자동 자체가 수동 한도 L1(`safety.manual_angular` ≥ 0.30) 이상에서만 돈다(D-344 §13) — L0 에서는 `limit_level_too_low` 로 멈춘다.
`line_follow.ir_guard_enabled: true` 는 4 단계 손 확인과 6 단계 확인을 모두 녹화로 남긴 뒤, 자동 주행 녹화 루프(D-344 §12)에서 켠다. 기본값은 꺼짐이다.

## 기록

세션 JSON(`~/rosy-ir/session.json`)과 도구 출력은 세션 기록에 첨부한다. 끝점·해시는 공개 저장소에 넣지 않아도 된다 — 모듈 logs 에 경로와 요약만 남긴다.
