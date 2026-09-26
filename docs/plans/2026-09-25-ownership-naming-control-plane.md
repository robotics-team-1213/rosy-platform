---
module: docs
---

# 소유·이름·관제 평면 (D-227)

**Status:** 초안 (2026-09-25). 결정: [D-227](../adr/D-227-ownership-names-stay-on-the-current-tree.md). 이 계획은 파일을 옮기지 않는다. 판단 라이브러리의 실행은 [2026-09-25-decision-lane-recovery.md](2026-09-25-decision-lane-recovery.md) (D-228) 다.

입력은 [2026-09-25-ownership-naming-input-v0.2.md](2026-09-25-ownership-naming-input-v0.2.md) 다. v0.2 의 "소유 먼저, 이동은 나중"은 받는다. v0.2 §5 와 §47 의 목표 트리는 다음 작업이 아니다. D-227 이 Accepted 되기 전에는 `src/AGENTS.md` 의 현재 트리가 이긴다.

## 이 계획이 열지 않는 일

- `src/foundation`, `src/runtime`, `src/hmi`, `src/ai`
- `src/runtime/rosy_runtime` 로의 `core` 개명, `face` → `hmi`, `omx_adapter` → `omx`, `interfaces` → `rosy_interfaces`
- `site/control_plane`, `site/ai_worker`, `site/operations_ui`
- `products/pinky_pro/launch`, 제품 폴더의 두 번째 capability·profile 파일
- `FollowLane` / `PickObject` / `PlaceObject` / `Dock` ROS 액션
- 로봇 ack 에 `TIMEOUT` 추가 (D-215)
- 사이트 경유의 로컬 텔레옵, 사이트 API 로의 `core_api_web` 흡수
- Pi 명령 경로의 decision provider, `DEGRADED` / `ESTOP` / `FAULT` 모드
- gRPC, MQTT, ROS 2 WAN
- 에피소드·MCAP·챔피언 모델 매니페스트로 `data/teleop` · `data/drive` 를 교체
- D-171 트랙 1·2 와 D-205 P0–P3 보다 앞선 `control` 분할

## 1. 지금 트리에 읽는 소유

| 지금 | 여섯 이름 | 정본이 하는 일 | 다음 변경 |
|---|---|---|---|
| `core_common`, `core_events` | Foundation | 스키마, 신원, 프로파일, capability, intent, 이벤트. 다른 워크스페이스 패키지를 import 하지 않는다 | 유지. 필드를 더하려면 D-18 계약 결정 |
| `interfaces` | Foundation | `Emotion`, `SetBrightness`, `SetLamp`, `SetLed` | 유지. 액션 추가는 별도 ADR |
| `core` + `core.bridge` | Robot Runtime + Command Plane | 단일 프로세스, 최종 `cmd_vel` | 유지 |
| `core_features/command` 와 나머지 매니저 | Command Plane + Runtime | 명령 선택, 모드, 안전, 도킹, 전력 | 유지. 패키지로 승격하지 않는다 |
| `core_api_web`, `web_common` | Experience (로봇) | `/api/v1`, 대시보드, 공유 브라우저 부품 | 유지. 사이트 API 와 합치지 않는다 |
| `face/emotion` | Experience (로봇) | LCD | 유지 |
| `control` / `sensing` | Robot Runtime | 카메라, 차선, 라이다, 미로 `robot.yaml` | D-205 P1–P3 과 D-209 의 `sensing/perception` 만 |
| `control` 의 계획·배회·레거시 안전 | Robot Runtime | 미로 스택. `profile:=full` 만 단독 최종 발행 예외 (D-208) | core 옆에서 최종 속도를 내지 않는다 |
| `devices/bringup` `command_deadman` | Robot Runtime | 드라이버 영속도. core 와 독립 | 유지 |
| `navigation` | Robot Runtime | Nav2, 점유 맵 | 유지. `runtime/mobility/nav2` 로 옮기지 않는다 |
| `products/omx_adapter` | Robot Runtime | 꺼진 팔 계약 | 이름 유지 |
| Pinky 숫자 세 곳 | 제품 기록은 아직 흩어짐 | 천장 `profile.pinky_pro.yaml`, 매니페스트 `bringup`, URDF `sim/description`, 미로 한계 `robot.yaml` | D-207 Accepted 뒤에 매니페스트·천장·URDF 만 |
| `site/fleet` | Site Control Plane | 생존, 작업 이름, 대형, 신호등. 바퀴 속도를 계산하지 않는다 | 그 자리에서 키운다 |
| `site/games` | Site (노트북) | 경기 호스트. fleet 통로 | 유지 |
| `deploy/` | 설치 | 이미지, SD, 제품 유닛, 서명 | 관제 서비스로 옮기지 않는다 |
| `tools/perception`, `data/teleop/learning` | AI / Learning | 재생·채점, 추적 클립 7개 | `src` 패키지로 올리지 않는다 |
| `tools/run_data.py` | 수집 | teleop / drive 세션 | D-186 유지. 에피소드 포맷은 별도 ADR |
| `src/apps/control` | 없음 | `.pytest_cache` 만 | 경로 시험과 함께 지우는 별도 정리 |

## 2. 순서

각 단계는 앞 단계의 게이트가 열린 뒤에만 시작한다. 빈 디렉터리는 완료가 아니다.

### 단계 0 — 이 기록

D-227 과 이 계획. 코드 변경 없음.

완료: ADR 본문과 색인 행이 있고, 하네스 ADR 검사가 빈 오류다.

### 단계 1 — 새 코드를 넣을 때의 이름

패키지를 추가하는 커밋은 D-227 결정 2와 결정 9를 커밋 메시지에 한 줄로 답한다. 기존 패키지 개명은 하지 않는다.

완료: 그 커밋의 D-168 구조 시험이 통과한다. 이 단계만의 선행 커밋은 없다.

### 단계 2 — Pinky 제품 기록

조건: D-207 이 Accepted 이고, 그 숫자 파일을 실제로 고친다.

옮기는 파일은 매니페스트, 제품 천장, URDF 뿐이다. `robot.yaml` 의 미로 한계, bringup 버스, launch 는 남긴다.

완료: `test/test_folder_layout.py` 와 bringup·description 계약 시험. 제품 폴더의 launch 파일이 0개.

### 단계 3 — 인식 자리

조건: D-205 P0 실측이 통과하고 P1 이 디렉터리를 만든다.

자리는 `src/core/control/control/sensing/perception/` 하나다 (D-209). `runtime/perception/lane/providers` 트리를 만들지 않는다. 학습 출력은 evidence 이고 `cmd_vel` 이 아니다.

완료: D-199 계약 시험과 기존 차선 시험. D-209 가 이미 완료 조건을 적었다.

### 단계 4 — 명령 계약이 부족할 때

조건: 닫힌 `/do` 동사로 표현되지 않는 요구 ID 가 있다.

그때의 ADR 이 스키마 필드를 더할 수 있다. 그 ADR 은 로봇 ack 네 값을 유지하고, 사이트가 raw control 을 보내지 못하게 하며, ROS 액션 파일을 추가하지 않는다.

완료: `src/core/core/test/test_protocol_schemas.py` 와 intent 시험. `AckStatus` 에 `TIMEOUT` 이 없다.

### 단계 5 — fleet 를 그 자리에서

조건: B1–B3 과 요구 ID. 미션은 D-12 대로 fleet 이다.

incident, projection, registry 를 패키지로 나누는 일은 그 조건이 성립한 뒤의 별도 ADR 이다. 설치 책임은 `deploy/` 에 남긴다.

완료: fleet 시험. 로봇 패키지가 그 새 모듈을 import 하지 않는다.

### 단계 6 — 사이트 쪽 학습

조건: D-205 재생 게이트를 통과한 모델이 있고, 실측 로그가 있다.

자리는 `src/` 밖이다. `tools/perception/` 을 키우거나, colcon 이미지에 들어가지 않는 기계의 작업으로 둔다. `src/site/ai_worker` 는 만들지 않는다. 모델 제품 이름을 패키지 이름으로 쓰지 않는다.

완료: 로봇 이미지 패키지 목록에 학습 패키지가 없고, 그 모델은 evidence 만 낸다.

### 단계 7 — 폴더 이동과 개명

조건: 단계 2–6 중 실제로 착지한 것이 있고, D-171 트랙 1·2 가 그 모듈에서 끝났고, 이미지 한 세대를 다시 통과한다.

폴더 이동과 패키지 개명은 서로 다른 커밋이다. 이 계획의 단계 7 을 먼저 실행하지 않는다.

완료: 경로 시험, D-168 시험, 그 세대의 하드웨어 평가 재통과.

## 3. 다음에 패키지를 열기 전에

D-227 결정 9의 열 가지와 B1–B3 을 계획 문단에 적는다. 하나라도 "새 루트가 필요하다"이면 D-227 을 대체하는 ADR 을 먼저 쓴다.
