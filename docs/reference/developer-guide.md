# ROSY 개발 가이드 — 구조·빌드·시뮬·테스트·배포

- **대상:** 코드를 빌드하고 시험하고 로봇·현장에 올리는 사람
- **갱신:** 2026-10-05 (README에서 옮김)
- 처음 합류했다면 [팀 가이드](team-guide.md)부터 본다. 계약은 [README 「핵심 계약」](../../README.md#핵심-계약)과 SRS·ADR이 우선한다.

## 구조

폴더는 **소스 책임 분류**일 뿐이다. 디렉터리 경로만으로 최종 명령 writer, 설치 호스트, 이미지 묶음을 판단하지 않는다([D-315](../adr/D-315-source-folder-responsibility-and-runtime-authority.md)). 소스 루트와 소유 영역의 정본은 [`tools/harness/platform_parts.yaml`](../../tools/harness/platform_parts.yaml)이다 (D-427).

| 폴더 | 무엇 |
|---|---|
| `contracts/` | 공유 계약: `foundation`(core_common 타입·프로토콜·설정), `ros_idl`(ROS 인터페이스), `motion`, `skill`, `learning`. 계약은 동작을 실행하지 않는다 |
| `middleware/` | 로봇 위에서 도는 것: `core`(CORE 게이트웨이·서비스·이벤트·API·내비게이션), `perception`(패키지 `control`), `apps/device`(Pinky·OMX 프로필·bringup·adapter), `drivers`, `skills`, `execution`, `ui`(대시보드·Pilot·face) |
| `operations/` | 현장 서버 쪽: `fleet`(미션·작업 원장·콘솔), `vision`(천장 카메라), `processes`, `execution`, `world`, `apps`, `ui/cam`(Rosy Cam 앱), `site_devices`(도크·신호등 펌웨어) |
| `learning/` | 데이터 정리·학습·모델 등록(`curation`, `training`, `registry`), `envs/isaac`(Isaac Sim) |
| `integrations/` | 로봇·시뮬레이션 adapter (`robots`, `simulation` — Gazebo 월드·다로봇 시뮬) |
| `shared/web/` | 공용 웹 자산 (패키지 `web_common`) |
| `deploy/` | 설치·이미지·서명 릴리스: `robot/pinky_pro`, `robot/omx`, `site` |
| `profiles/` | 설치 프로필 |
| `tools/` | 개발 도구(harness, hooks, release, sim, calibration …). 로봇에 설치되지 않는다 |
| `test/` | 저장소 단위 계약 시험, `known_failures` |
| `docs/` | SRS, API reference, ADR, 계획, 검증 기록 |
| `data/` | 로컬 주행 기록. 세션 파일은 커밋하지 않는다 (`data/README.md`) |
| `reference/` | 동결된 upstream pinky_pro 사본 |

폴더 이름과 ROS 패키지 이름은 항상 같지 않다(예: `middleware/core/gateway`는 `core`, `middleware/perception`은 `control`). site 앱은 폴더 끝 이름이 `<word>`, 패키지가 `rosy_<word>`다(D-377). Pinky의 최종 `cmd_vel`은 CORE가 발행하고, 제품 adapter는 ROS/vendor 표현 변환만 한다 ([D-317](../adr/D-317-control-and-shared-contract-source-boundaries.md)).

## 빌드 및 시뮬레이션

```bash
source env.sh
colcon --log-base log build --symlink-install --base-paths $(python3 tools/harness/colcon_roots.py) --build-base build --install-base install

# 시뮬레이션 2대
ros2 launch gz_sim gz_multi.launch.py robots:=2

# core 게이트웨이
ros2 launch core rosy_core.launch.py

# 다로봇 시뮬과 Fleet 콘솔을 한 번에
bash tools/run_fleet_sim.sh
```

새 Python ament 패키지를 추가하거나 옮긴 뒤 resource marker가 빠졌다면
`bash tools/fix_ament_resource.sh`로 `resource/<package>` marker를 다시 만든다.
이 스크립트는 패키지 manifest나 colcon build를 대신하지 않는다. 로컬 수동주행
메모와 주행 세션은 소스나 설치물이 아니라 `data/teleop` 및 `data/drive`에 둔다.
세션 파일은 커밋하지 않으며, 예외는 `data/README.md`를 따른다.

## 테스트와 CI

테스트는 세 단계다 ([D-436](../adr/D-436-change-scoped-test-tiers.md)).

```mermaid
flowchart LR
    a["affected<br/>작업 중 · 로컬<br/>바꾼 범위만"] --> q["quick<br/>push 직전 · pre-push 훅<br/>약 3분"] --> f["full<br/>GitHub CI<br/>main · PR · 야간 · 릴리스"]
```

| 단계 | 언제 | 명령 |
|---|---|---|
| affected | 작업하는 동안 | `python tools/harness/rosy_harness.py affected --base origin/main --run` — 바꾼 파일에 연결된 시험과 가드만 |
| quick (pre-push) | push 직전, 훅이 자동 실행 (~3분) | `bash tools/hooks/install.sh`로 설치한 `pre-push` |
| full | GitHub CI (main push, PR, 야간, 릴리스) | 로컬에서 돌리지 않는다 (Windows 40–60분, 일부 wheel 없음) |

결과는 기존 실패와 비교한다. `NEW`가 나오면 그 브랜치의 실패다.

```bash
python -m pytest <paths> -q -rfE -p no:cacheprovider > ../run.txt
python test/known_failures.py ../run.txt
```

pre-push가 돌리는 quick 묶음을 손으로 돌릴 때:

```bash
python -m pytest test/test_harness_contracts.py test/architecture/test_module_structure.py   test/test_io_image_closure.py test/test_line_follow_contract_docs.py   test/test_behavior_test_ownership.py test/test_module_scorecard.py   test/test_release_boundary_guards.py test/test_robot_literals.py   middleware/core/gateway/test/test_protocol_version_alignment.py   middleware/core/gateway/test/test_event_catalogue.py   middleware/core/gateway/test/test_console_layout.py   middleware/core/gateway/test/test_host_cards.py   middleware/core/gateway/test/test_host_hardware.py   middleware/core/gateway/test/test_triage_contract.py   middleware/core/gateway/test/test_host_status_summary.py -q
python tools/harness/rosy_harness.py lint   # ADR 중복·mojibake·append-only·staleness
```

CI(`.github/workflows/ci.yml`)는 `ros:jazzy-ros-base` 이미지에서 colcon 빌드, pytest, 부트 스모크(slam_toolbox 없이 기동), SaveMap 타입 가드를 돌린다. 호스트 pytest가 통과해도 장치·ARM64 이미지·현장 수용 증거를 대신하지 않는다.

## 관제 배치

현장 Ubuntu PC가 Fleet·Vision·Caddy 서비스를 실행하고, 관제 PC는 HTTPS로 Fleet의
`/console`을 여는 브라우저 단말이다. 두 역할은 한 물리 PC에 함께 놓을 수도 있다.
Pinky의 화면과 최종 주행·정지 판단은 각 로봇의 CORE에 남는다. OMX-AI 작업대 제어는
별도 로컬 인스턴스의 수용 절차가 필요하다. 현재 화면은 Fleet 콘솔이며,
`ROSY Console`은 사람의 화면·대화 접점에 쓰는 제품 이름이다. 자연어 명령과
OMX 원격 작업은 아직 수용된 기능이 아니다.

배치 결정은 [D-275](../adr/D-275-web-surface-and-video-runtime-ownership.md)와
[D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md),
현장 접속 절차는 [사이트 배포 설명](../../deploy/site/README.md)을 따른다.

## Raspberry Pi 5 런타임

**로봇은 네이티브로 돈다.** 제품 런타임은 Docker가 아니라 Ubuntu Server 24.04
arm64 위의 ROS 2 Jazzy + systemd다 (D-161). `rosy-runtime.target`이 CORE를 기본
기동하고, I/O와 navigation은 승인 후 명시적으로 켠다. Docker/Compose는 개발·CI
전용이며 제품 이미지에는 설치하지 않는다. 장치마다 컨테이너를 켜고 끄는 옵션은
없고, 유연성은 프로필/slice로만 표현한다 — 컨테이너는 안전 계획 밖 비전·AI 같은
선언된 사이드카 워크로드에만 허용된다 (D-197, D-246).

런타임 슬라이스는 단계별로 나뉜다. `rosy-core`는 FastAPI/rclpy만 소유하고,
`rosy-motor`는 LiDAR 없는 벤치 커미셔닝, `rosy-io`는 승인된 모터·LiDAR 통합
운용에 사용한다.

```bash
cd deploy/robot/pinky_pro
sudo ROSY_ROBOT_NUMBER=1 bash ./install-pi.sh
# 신원은 로봇 번호 하나에서 나온다 (ADR D-33). Device installer가 .env를
# 관리하고 두 값을 함께 유도하므로 수동으로 identity를 덮어쓰지 않는다.
# stationary core와 readback gate를 통과하기 전에는 motor/hardware mode를 켜지 않는다.
sudo ./runtime-mode.sh up
```

기동 후 같은 네트워크의 브라우저에서 `http://<raspberry-pi-ip>:8080/dashboard`
를 연다. Rosy API viewer/operator/administrator 토큰으로 로그인하면 로봇 상태,
비상정지, 기능 계약과 Raspberry Pi OS의 CPU·메모리·디스크·온도를 한 화면에서
확인할 수 있다. 화면은 FastAPI에 내장되어 별도 Node.js 서버가 필요 없다.

모터 명령은 ROS와 분리된 `MotorController` 함수 계층에서 유효성 검사,
차동구동 변환, 선속도·각속도·바퀴 RPM 제한을 거친다. 결과는
`APPLIED / LIMITED / REJECTED / DRIVER_ERROR`로 명확히 남으며, 잘못된 입력이나
UART 오류에는 즉시 zero-RPM 정지를 시도한다. DYNAMIXEL 드라이버도 동일한
RPM 상한을 독립적으로 검사하고 엔코더 32비트 롤오버를 안전하게 처리한다.

유선 LAN 없는 SD 카드 굽기, Wi-Fi·SSH 설정, Windows 배포 및 첫 접속은
[`docs/deployment/raspberry-pi-wifi-image.md`](../deployment/raspberry-pi-wifi-image.md)를
따른다. 장치 권한과 물리 인수시험은
[`docs/deployment/raspberry-pi-runtime.md`](../deployment/raspberry-pi-runtime.md)에
정리되어 있다. ARM64 빌드 경계와 컨테이너 포함 범위는
[`docs/deployment/arm64-build-notes.md`](../deployment/arm64-build-notes.md)를 따른다.

## 로드맵

Phase 0 리네임·멀티로봇 리팩토링 → **Phase 1 core** → Phase 2 웹 대시보드 →
Phase 3 2대 검증 → Phase 4 fleet → Phase 5 Formation → Phase 6 확장.
상세: [`docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md`](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md)

