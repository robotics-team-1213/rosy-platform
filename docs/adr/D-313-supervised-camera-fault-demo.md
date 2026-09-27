## D-313 전면 카메라 고장 시 관제 영상과 로컬 센서로 제한된 시연을 선택한다

**Status:** Accepted (2026-09-28, 구조·작업 선택 결정). 구현, 장치 설치, G4/G5 및 현장 수용은 HOLD.

**Context:** Pinky 전면 카메라 없이도 시연해야 할 수 있다. 관제 PC는 천장 카메라로 현장 전체를 보면서 작업을 지시해야 한다. 현재 `overhead`는 폰 JPEG를 최신 1장으로 수신하고 ArUco 위치를 Fleet `sightings`에 보낸다. Fleet 화면의 지도·목표·정지와 CORE의 `IR_LINE`/`CAMERA_LINE`, Teleop watchdog은 존재하지만 관제 라이브 영상, 카메라 고장별 작업 적격성, 중단부터 물리 정지까지의 통합 결과는 없다. `deploy/robot/config/line_follow.yaml`은 IR 흑·백 보정이 꺼져 있고, D-295/311/312에 따른 실기 G4/G5는 HOLD다. 현재 API 접수나 합성 프레임은 시연 주행 승인 근거가 아니다.

**Decision:**

1. **관제 영상과 명령 경로를 분리한다.** 고정 천장 카메라의 최신 JPEG는 현장 Vision 서비스가 인증된 관제 브라우저에 직접 제공한다. Fleet 콘솔은 이 화면과 로봇·작업 상태를 함께 표시하되 Fleet 서버와 CORE에는 영상 바이트를 통과시키지 않는다(D-118/D-136). Vision은 프레임 `source_id`, 원본 캡처 시각, 수신 시각, sequence와 현재 지연을 같이 제공한다. 오래된 마지막 프레임은 라이브처럼 표시하지 않는다. 한 카메라가 현장 전체를 덮지 못하면 구역별 카메라와 시야·보정 정보를 등록한다. 관제 화면의 `전체 시야`는 실제 카메라 구역의 합집합만 뜻한다.
2. **카메라 고장과 표시 고장을 구분한다.** CORE의 전면 카메라 캡처·관측 상태, Vision preview 상태, 관제 천장 카메라 상태는 별도 필드다. 전면 카메라가 고장 나도 로컬 LiDAR·IR·오도메트리/TF·정지 경로의 적격성을 독립 판단한다. 단, 그 카메라에 의존하는 현재 작업은 즉시 HOLD/취소하고 이전 명령·프레임을 폐기한다. 단순 브라우저 preview 오류를 로봇 센서 고장으로 오인하지 않는다.
3. **폴백은 자동 소스 교체가 아니라 새 작업 선택이다.** 먼저 CORE가 카메라 의존 작업을 멈추고 정지 결과를 확인한다. Fleet의 작업자는 보이는 현장과 로봇 readback을 확인한 뒤 `IR 선 추종`, `짧은 Nav2 목표`, `입회 Teleop`, `현장 회수` 중 적격한 작업만 새로 요청한다. 이전 카메라 미션을 자동 재개하지 않는다. Fleet `QUEUED`, CORE `ACCEPTED`, 명령 0 송신, 물리 정지는 각각 다른 상태로 보고한다(D-307). 중복 요청은 기존 task/idempotency 계약을 사용하고 불확실한 디스패치는 재시도하지 않는다.
4. **로컬 안전 조건은 관제보다 우선한다.** IR 선 추종은 실제 흰 선과 장치별 흑·백 보정, fresh IR 관측이 있을 때만 가능하다. 바닥 IR의 낙하 감지는 선 추종과 별개로 유지한다. 일반 지도 이동은 live LiDAR/근접 감지, 낙하 IR, 오도메트리, 지도·TF, localization/Nav2 readiness와 G4/G5 수용을 요구한다. IR만으로 미지 공간을 주행시키지 않는다. Teleop은 별도 실기 수용과 deadman/500 ms watchdog, 현장 입회가 필요하다. 기존 Control policy에서 camera tracking을 필수로 묶었다면 정지 뒤 검증된 카메라 비의존 정책과 새 보정 revision으로 교체한다. 운전 중 센서 필수 목록이나 latch를 풀지 않는다. CORE의 기존 단일 최종 `cmd_vel`, E-stop, sensor age/geometry gate를 우회하는 Fleet 명령은 만들지 않는다.
5. **천장 영상은 사람이 보는 시야이자 외부 위치 대조다.** `sighting`은 로봇 pose와 대조하고 불일치·마커 누락·시야 가림·영상 stale 때 관제 지원 작업을 HOLD하는 데 사용한다. `sighting`을 로봇 localization, 최종 속도, 자동 충돌 회피 입력으로 사용하지 않는다(D-257). 별도 정책 적격 영상 증거와 DEVICE/FIELD 시험을 마치기 전에는 D-268의 자동 작업 트리거도 열지 않는다.
6. **권한과 자원 예산을 분리한다.** 카메라 업로드 token은 보기/목표/정지 권한이 없다. Fleet viewer/operator 권한으로 짧은 수명의 source 한정 영상 보기 lease를 발급하고 Vision이 검증한다. 브라우저는 폰 업로드 token과 로봇 REST token을 받지 않는다. Vision은 최신 프레임 1장, 크기·FPS·동시 시청자 상한과 과부하 시 전송 중단을 둔다. 안전·heartbeat 지연이 영상 때문에 늘어나면 영상부터 중단한다. 정확한 대역·지연 상한은 현장 측정으로 확정한다.

**상태 전이:** `NORMAL → CAMERA_HOLD → DEGRADED_READY → DEGRADED_RUNNING`. 추가 센서·영상·네트워크·정지 readback 이상은 `CAMERA_HOLD` 또는 `RECOVERY_HOLD`로 돌아간다. 카메라 복구만으로 `NORMAL`이나 이전 임무로 자동 복귀하지 않는다. 상태별 이유·필수 증거·작업자·시각·task ID를 보관한다.

**Alternatives:** Fleet 서버로 JPEG를 중계하면 상태/명령 처리와 영상 부하가 결합돼 D-118/D-136 경계를 깬다. 카메라 상실 즉시 `IR_LINE`으로 자동 전환하면 선·보정·안전 수용이 없는 바닥에서 움직일 수 있다. 천장 좌표를 Pinky localization에 바로 주입하면 카메라 시야·평면 오차·지연이 로봇의 안전 판단으로 승격된다. 세 안 모두 채택하지 않는다.

**Consequences:** 관제 영상은 별도 Vision endpoint와 브라우저 표면이 필요하고, Fleet은 카메라 상태와 작업 적격성을 읽어야 한다. 새 route/필드를 정할 때 API Reference와 `core_common.protocol` schema를 같은 변경 단위로 갱신한다(D-18). 미디어 보기 lease가 별도 보안 계약과 부하 시험을 만든다. 기존 D-257의 Fleet sighting 표시·대조 방향은 유지하며, D-257의 Proposed 상태나 D-268의 자동 정책 적격성을 이 ADR만으로 승격시키지 않는다.

**Implementation:** [2026-09-28 실행 계획](../plans/2026-09-28-camera-fault-supervised-demo.md)의 T1–T6. 실제 파일 경계, red/green 시험, 시뮬레이션·장치·현장 승격과 rollback을 그 계획에 둔다. [설계 근거](../plans/2026-09-28-camera-fault-supervised-demo-design.md).

**Verification/stop condition:** 카메라 프레임 단절·stale·잘못된 source, IR 선 소실, LiDAR/IR/TF 누락, 지도 불일치, Vision 과부하, 관제 PC 단절, 중복 goal 및 정지 지연을 각각 주입한다. 로컬 시험은 로직만 증명한다. 실기 G4/IR 보정/G5·물리 E-stop/제동거리/현장 시야 시험 전에는 무카메라 바닥 시연을 승인하지 않는다. 어떤 단계에서든 실제 정지 결과가 불명확하면 `RECOVERY_HOLD`와 현장 회수다.

**References:** D-2, D-12, D-18, D-118, D-136, D-143, D-257, D-268, D-295, D-307, D-311, D-312.
