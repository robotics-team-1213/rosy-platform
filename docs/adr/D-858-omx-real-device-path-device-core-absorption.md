## D-858 OMX 실물 팔 경로: device-core를 은퇴시키고 기존 OMX owner에 흡수한다

**Status:** Accepted (2026-10-24, 사용자 결정 「device-core는 지금 은퇴, 플랫폼으로 흡수」). 방향과 단계의 결정이며, 각 단계의 구현·시험·장치 수용은 아직 없다.

### Context

- 팀 앱이 실물 OMX 팔에 기술 단위 작업을 맡기던 유일한 경로는 비공개 저장소 rosy-vault의 `device_core/`였다. 앱이 HTTP `POST /tasks`로 기술 이름을 보내고, 서비스가 Dynamixel 버스에 직접 쓴다. 가짜 드라이버 시험만 통과했고 실물 팔을 움직인 기록은 없다. rosy-vault는 2026-10-24 은퇴해 archived되었다. 보존 기준 커밋은 `9a744a3`이다.
- 플랫폼 쪽 실물 팔 실행은 닫혀 있다. `omx_hardware_owner.py`는 동작 port를 `enabled=False`로 두고 `goals_enabled: False`를 보고한다(D-785). `step_action_kinds.py`의 `CELL_TRANSFER`는 `open_profiles={"simulation"}`이다. `pose_plan.py`는 simulation이 아닌 profile을 거부한다.
- 실물 하달 설계는 D-797(Proposed, 2026-10-18)에 있다. 팔은 새 배포 프로필 `device_trial`에서 장치 증거로만 연다. 이 문서는 main에 착지하지 않았고 archive 브랜치 커밋 `4d218631f5`에만 있다.
- D-856(Accepted 2026-10-24)은 외부 앱에 raw servo·장치 owner 호출을 열지 않고, 앱이 장치를 직접 제어하는 방식을 채택하지 않았다. D-282 §5는 계약 없는 OMX 원격 작업 API를 두지 않는다.
- device-core를 플랫폼에 그대로 옮기면 같은 팔을 두 갈래 코드가 제어한다. 정지 · 래치 · 관절 한계 · 작업 하나 원칙이 두 번 구현되고, 버스 writer가 둘이 된다.

### Decision

#### 1. device-core는 옮기지 않고 은퇴시킨다

플랫폼에 앱용 장치 HTTP 서비스를 새로 두지 않는다. 실물 팔 동작은 Fleet이 승인한 작업 → 같은 호스트의 OMX owner → owner의 실행 port 한 경로로만 간다(D-336, D-856 §2).

#### 2. 플랫폼에 없는 기능만 owner 쪽으로 흡수한다

| device-core 기능 (9a744a3) | 흡수 위치 | 이미 있어 가져오지 않는 것 |
|---|---|---|
| Dynamixel 운영 드라이버: 시작 HOLD, 정지 시 현 위치 버팀, 정지 래치, EEPROM 쓰지 않음 (`drivers/dynamixel.py`) | `omx_adapter` `LocalActionPort`의 실물 구현 | 정지 래치 · 복구(`local_stop.py`, D-442) |
| 추종 오차 · 하드웨어 오류 · 목표 자세 미도달 · 빈손 파지 HOLD (`safety.py`, `service.py`) | 같은 실물 port | 관절 한계(`command_owner.py`) |
| teach 포즈 재생 (`backends/teach.py`) | 실물용 포즈 계획. `pose_plan.py`의 simulation 전용 조건은 그대로 두고 별도 경로로 둔다 | 작업 하나 · 모호한 ACK HOLD(`pick_place_runner.py`, D-336 §3) |
| 실측 보정 저장(원자적 쓰기, 기록, 저장 뒤 HOLD) (`calibration.py`) | 커미셔닝(D-496) | 같은 호스트 인증(UDS) |
| 정지 시험 기록과 `auto_ready` | 커미셔닝 수용 관문 | |
| 측정 · 티칭 · 정지 시험 콘솔 | 커미셔닝 화면 (`commissioning_view.py` 확장) | |

앱이 부르던 기술 이름 API와 호출자 lease는 가져오지 않는다. 앱 쪽 요청 계약은 D-856 P1이 정한다.

#### 3. 버스 하나에 writer 하나

실물 port는 같은 시리얼 포트를 쓰는 owner · 수집 · guarded_native 파이프라인(D-846 · D-847) · observer와 동시에 열리지 않는다. 검사는 팔 인스턴스별로 한다. device-core `lock.py:64`처럼 다른 팔의 owner 소켓까지 와일드카드로 보지 않는다. 그렇게 하면 한 호스트 두 팔(D-773)에서 잘못 거부한다.

#### 4. 실물 동작의 관문

다음이 모두 만족되기 전에는 실물 port가 동작 목표를 받지 않는다.

- 측정한 관절 한계
- 그리퍼 실측값
- 통과한 정지 시험 기록. 기준은 device-core V-016의 사용자 확정값(정지 500 ms 이하, joint1 ±0.1 rad · 0.1 rad/s)을 출발점으로 쓴다.

D-793이 정해지기 전에는 학습 정책 기술을 실물에서 거부한다. D-404 · D-785의 기존 닫힘은 이 결정으로 풀리지 않는다. 각 단계의 개방은 아래 순서의 해당 단계에서만 한다.

#### 5. 단계

| 단계 | 산출물 | 열리는 것 |
|---|---|---|
| S1 | Dynamixel 실물 port와 가짜 버스 시험. owner는 계속 `enabled=False` | 없음 |
| S2 | 실물용 teach 포즈 계획과 시험 | 없음 |
| S3 | 커미셔닝 보정 저장 · 정지 시험 관문 · 콘솔 | 측정 모드만 |
| S4 | D-797 §2 · §3: `device_trial` 프로필과 실물 identity 계약. D-797 문서를 main에 복원해 함께 결정한다 | `device_trial`에서 단일 팔 |
| S5 | 실물 수용: D-797 §8 · D-403 §7 항목과 KAN-30 정지 확인 | 시연 범위 |

각 단계는 safety 경로를 바꾸므로 `Safety-Review:` trailer와 독립 검토가 필요하다(D-430 §5).

#### 6. 공개 저장소로 옮길 때

rosy-vault의 git 이력은 가져오지 않는다. 파일을 옮기고 출처 커밋 `9a744a3`을 커밋 메시지에 적는다. 원본 시험에 있는 실물 보드 시리얼은 가짜 값으로 바꾼다.

### 기존 ADR과의 관계

| ADR | 관계 |
|---|---|
| D-427 · D-429 · D-430 | 새 최상위 폴더 없음. 흡수 코드는 `middleware/devices/omx/` 기존 모듈 안에 둔다. safety 경로 변경은 D-430 §5를 따른다 |
| D-282 §5 | 유지. 앱용 OMX 원격 작업 API를 만들지 않는다 |
| D-336 · D-442 | 유지. owner 한 경로, 정지 · 복구 경계 |
| D-404 · D-785 | 유지. 이 결정만으로는 실물 동작이 열리지 않는다 |
| D-797 (Proposed, 미착지) | 팔 실물 하달 설계의 근거. S4에서 main에 복원해 결정한다 |
| D-793 | 정책 실물 실행 관문. 그 전에는 거부 |
| D-856 | 앱과 동작의 경계. 흡수는 그 실물 수용 계획의 입력이다 |

### Consequences

- S5 전까지 앱이 부를 수 있는 실물 팔 pick/place 경로가 없다. 2026-11-21 실물 팔 시연은 S1~S5가 그 전에 끝나야 가능하다. 시연 범위는 팀이 다시 정한다(KAN-47).
- 같은 팔의 제어 코드가 하나로 유지된다. 대가는 흡수가 D-797 구현 전체를 요구한다는 점이다.

### 되돌리기

rosy-vault는 `gh repo unarchive`로 되살릴 수 있다. 그래도 device-core를 다시 쓰려면 이 ADR을 대체하는 새 ADR이 필요하다.
