## D-295 네이티브 Pinky의 주행·맵핑 능력은 실행 모드와 검증 기록에 맞춰 공개한다

**Status:** Accepted (2026-09-27).

**Context:** 실제 Pinky의 네이티브 릴리스는 `ROSY_RUNTIME_MODE=motor`,
`ROSY_IO_DRIVE_ENABLED=true`로 실행 중이었다. CORE와 I/O는 정상이었고 최종
`cmd_vel` 발행자는 CORE 하나였다. 하지만 `rosy-navigation`은 꺼져 있고
`slam_toolbox`·Nav2 노드는 없었다. `/etc/rosy/approvals/`와 G4 기록 디렉터리도
없었다. 그럼에도 CORE는 제품의 정적 `capabilities.yaml`을 명령 게이트에 그대로
적용하여 `slam: true`와 navigation 기능을 광고했다. `core` 모드에서도 I/O가
오도메트리를 보고하면 기존 화면 게이트가 이 정적 능력을 다시 광고할 수 있었다.
이 상태의 `/slam/start` 성공 응답은 실제 SLAM 실행이나 지도 생성의 증거가 아니다.

**Decision:**

1. CORE 서비스 생성 시 제품 프로필을 복사해 현재 실행 스택의 유효 능력을 만든다.
   네이티브 `core`는 I/O가 오도메트리를 보고해도 teleop·navigation·SLAM·swarm을
   명령 게이트와 CAP-001에서 끈다. `motor`는 저속 수동 운전만 남기고
   navigation·SLAM·swarm을 끈다. `hardware`의 기본 `localization` backend는
   navigation을 남기되 SLAM을 끈다. `hardware` + `slam`에서만 SLAM을 광고한다.
   정적 제품 프로필은 변경하지 않는다. API 응답과 실제 명령 허용은 같은
   `Capability` 인스턴스를 사용한다.
2. 네이티브 장치에서 `motor` 구동 시험은 바퀴를 들어 올린 상태의 G4 절차로만
   수행한다. 한 번의 전진 시험, CORE의 0 명령 응답, 작업자의 정상 방향 관찰은
   진단 근거지만 8개 방향·정지 시험 및 독립 전원 차단 검증을 대신하지 않는다.
3. 바닥 맵핑은 G4 수용 기록, 하드웨어·내비게이션 승인, `hardware` + `slam`
   설정, 실행 중인 SLAM/Nav2, 최신 LiDAR·오도메트리·안전 근거와 단일 최종
   `cmd_vel` 발행자를 모두 확인한 뒤 시작한다. 승인 파일을 비어 있는 채로
   만들거나 모드만 바꾸어 빠진 시험을 우회하지 않는다. G5는 실제 지도
   YAML/PGM, 원시 telemetry, 정지·무충돌 결과를 별도로 검증한다.
4. 네이티브 systemd 장치의 실행 절차는
   [`pinky-native-mapping-recovery.md`](../deployment/pinky-native-mapping-recovery.md)에
   기록한다. 기존 Docker Compose G4/G5 예시는 네이티브 장치 명령으로 사용하지 않는다.

**Alternatives:** 정적 `capabilities.yaml`을 영구적으로 `slam: false`로 만드는
방법은 검증된 hardware SLAM 구성까지 숨기므로 기각했다. 화면의 응답만 숨기는
방법은 `/slam/start`와 goal 명령이 계속 허용되므로 기각했다. 승인 파일을 즉시
생성해 navigation 서비스를 켜는 방법은 G4 결손을 숨기므로 기각했다.

**Consequences:** 소스와 로컬 테스트의 유효 능력 수정은 설치된 네이티브
릴리스에 자동 반영되지 않는다. 서명된 새 릴리스의 장치 readback 전까지 실기
CAP-001 수정은 미검증이다. 2026-09-27 KST(2026-09-26 UTC)의 바퀴를 든 전진 1회는 약 0.53초 명령,
0 명령 수락 후 API의 0 속도 관찰까지 약 0.43초, 약 0.026m의 오도메트리 변화와
현장 작업자의 정상 방향 관찰을 얻었다. 이 결과는 G4 완료나 바닥 주행·맵핑
승인이 아니며 장치의 G4·G5 상태는 HOLD다.

**References:** D-2, D-32, D-51, D-144, D-161, D-192, D-213, D-291,
`docs/deployment/pinky-pro-first-device-runbook.md`.

---
