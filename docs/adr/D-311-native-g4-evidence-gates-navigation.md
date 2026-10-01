## D-311 네이티브 G4 실측 증거를 내비게이션 기동 조건으로 검증한다

**Status:** Accepted (2026-09-27, 소스 결정). 장치 적용과 실물 G4/G5 수용은 별도 HOLD.

## Context

네이티브 `rosy-navigation.service`는 `hardware.approved`와
`navigation.approved`의 파일 존재만 확인했다. 빈 파일이나 현재 장치·릴리스와
무관한 파일도 조건을 통과할 수 있었다. Docker 개발 경로의
`commission-pinky.py`는 네이티브 G4의 8개 방향·정지 실측을 검증하거나
systemd 기동 조건과 연결하지 않는다. D-295의 수용 조건을 실행 가능한 경계로
만들어야 한다.

## Decision

1. G4는 바퀴를 든 `motor` 모드에서 전진·후진·좌회전·우회전 각각에 대해
   버튼 해제와 명령 소실 정지를 한 번씩 기록한다. 두 작업자, 독립 검토자,
   물리 차단 가능 여부와 모터 ID 1·2의 토크 해제 사전 점검을 기록한다.
   원시 JSON에는 요청 속도, 시각순 odom 속도·위치·yaw, 정지 요청 시각을 둔다.
2. `mapping_approval.py approve`는 장치 번호·활성 릴리스·소스 revision,
   각 원시 파일 SHA-256, 방향과 측정 속도 한계(선속도 0.03 m/s, 각속도
   0.10 rad/s), 오도메트리 방향, 지속 0 속도 및 0.65초 이내 정지를 검증한다.
   검토자가 두 작업자와 다를 때만 원시 파일·번들·승인 기록을
   `/etc/rosy/approvals`에 봉인한다. 실장치 승인 명령은 root만 실행한다.
3. `rosy-navigation.service`의 `ExecCondition`은 매 기동마다 두 승인 기록의
   동일 검토와 번들 해시, 봉인된 원시 파일 및 현재 장치·릴리스를 다시 검증한다.
   `hardware` 모드와 활성 구동 플래그도 요구한다. 실패하면 내비게이션을
   시작하지 않는다. CORE가 최종 `cmd_vel` 단일 발행자인지, ROS graph 및
   센서가 준비됐는지는 별도 장치 readback으로 확인한다.
4. 이 도구는 모터 명령을 보내거나 원시 자료를 채집하지 않는다. 입력 파일의
   측정 출처와 현장 서명은 자동 인증되지 않는다. 물리 G4 판정과 G5의 실제 지도,
   MCAP, 정지·무충돌 증거는 담당자가 확인한다. 이 소스 변경은 새 서명 이미지에
   포함되고 SD를 갱신하기 전에는 기존 장치의 systemd 조건을 바꾸지 않는다.

## Verification and rollout

- 호스트에서 정상 번들, 누락·변조·과속·정지 지연·역방향 odom·다른 검토자·
  오래된 릴리스·구동 플래그 불일치를 테스트한다. 네이티브 payload와 systemd
  경로가 같은 도구를 참조하는지 확인한다.
- 이미지 빌드·서명·SD 설치 후 장치에서 빈 마커 차단, 정상 G4 봉인,
  `systemctl` 결과, CORE 단일 발행자, SLAM/Nav2/센서 readback을 검증한다.
  그 뒤 현장 G5를 수행한다. 호스트 테스트는 이미지·장치·현장 수용을 대신하지 않는다.

## Recovery

내비게이션을 중지하고 원래 `runtime.env`와 `motor` 벤치 구성으로 되돌린다.
새 원시 기록이 필요한 경우 새 G4를 검토해 다시 봉인한다. 승인 파일만 편집하거나
빈 마커를 만들어 우회하지 않는다. SD 이미지에 포함된 unit 변경은 서명된 이전
이미지로 되돌린다.

**Related:** [D-291](D-291-pinky-io-first-boot-and-signed-card-release.md),
[D-295](D-295-native-pinky-mapping-promotion-and-capability-truth.md),
[네이티브 맵핑 절차](../deployment/pinky-native-mapping-recovery.md).

## Addendum 2026-10-01: first real G4 run (9dfk) and two calibrations of the gate

The first schema-2 G4 run on rosy-pinky-9dfk (release 2026.10.01-019, floor, 0.025 m/s and
0.08 rad/s commands) showed two gaps between this gate and the robot. All raw trials, passes
and failures, are kept in the operator's evidence folder.

1. **Command-loss stop vs SAF-002.** CORE's teleop watchdog was hard-coded to 500 ms although
   SAF-002 says "default 500 ms, configurable" and rosy_default.yaml carried
   `safety.teleop_timeout_ms`. With ~0.1-0.2 s of wheel deceleration after the watchdog fires,
   the forward command-loss trial measured 0.674 / 0.613 / 0.719 s against the 0.65 s limit.
   CORE now reads `safety.teleop_timeout_ms` (100-2000 ms, validated), and the Pinky Pro robot
   package core.yaml sets 300 ms. The 0.65 s limit itself is unchanged.
2. **Stop threshold vs encoder quantization.** At rest the Pinky reports +-0.0134 rad/s for one
   encoder tick and 0.027 rad/s for two. `MEASURED_ANGULAR_EPSILON` was 0.02, so a stationary
   robot intermittently failed "sustained zero velocity" (cw 2/2, forward 1/3). It is now 0.03,
   above two ticks; real residual rotation (e.g. 0.05 rad/s) still fails.

Device application is a hotfix with backup on 9dfk until the next payload carries this change;
the G4 approval must be re-recorded after it and sealed only if all five trials pass as recorded.

