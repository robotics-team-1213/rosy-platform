## D-227 여섯 책임은 지금 트리 위의 이름이다 — 새 루트와 명령 봉투와 AI 워커는 만들지 않는다

**Status:** Proposed (2026-09-25). 폴더를 옮기지 않는다. 패키지 이름도 바꾸지 않는다.
입력은 저장소 밖 `ROSY_Ownership_Naming_AI_ControlPlane_Refactoring_v0.2.md`(2026-09-25)다.
잇는 결정:

- D-2, D-38, D-208: 최종 `cmd_vel` 은 `core` 하나다. 감지 프로파일은 속도를 내지 않는다.
- D-5, D-18, D-120: 로봇과 사이트의 애플리케이션 계약은 HTTP JSON 과 WS 다. DDS 는 로컬이다.
- D-12: 미션은 fleet 이고, 로봇은 원자 동작이다.
- D-168, D-207: 영역은 `core`, `devices`, `products`, `face`, `navigation`, `sim`, `site` 다. 제품 기록과 장치 종류는 주인이 하나다.
- D-171: control 구조 순서는 ROS 경계, 판단 추출, 그다음 패키지 분리다. 폴더 이동은 그 비율을 바꾸지 않는다.
- D-186: 스크립트·수집·설치의 주인은 `tools/`, `data/teleop`·`data/drive`, `deploy/` 다.
- D-205, D-209: 인식 재작업 전엔 `control` 을 나누지 않는다. 학습 백엔드는 `sensing/perception` 의 `backend_learned` 이고 증거만 낸다. `src/` 안에 학습 패키지를 만들지 않는다.
- D-215: `TIMEOUT` 은 Fleet 추적 기록이다. 로봇 ack 는 `ACCEPTED|STARTED|COMPLETED|FAILED` 네 개다.

**Context:**

1. **이미 있는 구현을 다시 짜는 그림이다.** v0.2 는 rewrite 를 금지하고, 소유를 먼저 정하고, 폴더 이동과 패키지 개명을 서로 다른 변경으로 미룬다. 그 순서는 D-171, D-186, D-207 과 같다.
2. **목표 트리는 세 번째 재배치다.** `src/foundation`, `src/runtime`, `src/hmi`, `site/control_plane`, `site/ai_worker`, `site/operations_ui` 는 D-168 이 시험으로 고정한 영역을 바꾼다. `src/core/core` 를 `src/runtime/rosy_runtime` 으로 보내는 이름도 같은 변경에 속한다.
3. **명령 봉투가 닫힌 `/do` 를 연다.** v0.2 의 `ADMIN|MISSION|INTENT|SKILL|CONTROL` 과 `FollowLane`·`PickObject`·`PlaceObject` 액션은 로봇 명령 면을 새로 만든다. 지금의 문은 `POST /api/v1/do` 와 `POST /api/fleet/do` 의 닫힌 동사다. 사이트는 정상 운용에서 바퀴 속도를 만들지 않는다.
4. **관제 화면을 사이트로 모으면 로컬 화면이 죽는다.** 로봇 화면은 관제 PC 가 없어도 `/api/v1` 로 남는다. 사이트 화면은 fleet 다. 둘을 Site API 하나로 합치면 얼굴이 사이트의 필수 홉이 된다.
5. **AI 워커를 `src/site` 에 두면 학습이 colcon 안으로 들어온다.** D-209 는 재생·채점·정답 라벨을 `tools/perception/`, 영상을 `data/teleop/learning/` 에 둔다. 원격 결정 패키지를 Pi 명령 경로에 두면 사이트가 안전 정지 조건이 된다.
6. **안전 상태 이름이 하나 더 늘어난다.** 제품 모드 집합은 `IDLE|MANUAL|NAVIGATION|DOCKING|EMERGENCY` 다. 장치 정지는 `SAFE_STOP` 이다. v0.2 의 `DEGRADED|ESTOP|FAULT` 를 그 옆에 두면 정지 경로가 둘이 된다.
7. **Pinky 제품 폴더가 launch 까지 삼킨다.** D-207 의 제품 기록은 매니페스트, 천장, URDF 다. bringup 버스와 `robot.launch` 를 `products/pinky_pro/launch` 로 복사하면 구동 주인이 둘이다.

**Decision:**

1. **여섯 이름은 지금 폴더를 읽는 말이다.** 새 영역 루트를 만들지 않는다.

   | 이름 | 지금 자리 |
   |---|---|
   | Foundation | `core_common`, `core_events`, `interfaces` |
   | Robot Runtime | `core` 프로세스, `core_features`, `control`, `devices`, `navigation`, 꺼진 `omx_adapter` |
   | Command Plane | `core_features/command`, `core.bridge` 의 최종 `cmd_vel`, `/api/v1/do` |
   | Site Control Plane | `site/fleet`. 설치·서명·갱신은 `deploy/` |
   | Experience | 로봇 화면 `core_api_web`·`web_common`·`face/emotion`. 사이트 화면은 fleet 콘솔 |
   | AI / Learning | 몸통은 D-209 `backend_learned`. 재생과 데이터는 `tools/perception/`, `data/teleop/learning/` |

2. **이름 규칙은 새로 여는 패키지에만 적용한다.** 기존 `core`, `core_common`, `core_features`, `control`, `interfaces`, `face`, `omx_adapter` 는 유지한다. 새 패키지 이름에 `core`, `common`, `features`, `utils`, `helpers`, `misc`, `apps`, `manager` 를 쓰지 않는다. 새 패키지를 열 때는 `runtime`, `adapter`, `bridge`, `provider`, `controller`, `planner`, `supervisor`, `registry`, `gateway`, `service` 가운데 역할을 드러내는 접미를 쓴다. 폴더 이동과 ROS 패키지 개명은 서로 다른 변경이며, 이 결정은 어느 쪽도 허가하지 않는다.
3. **명령은 지금 문을 통과한다.** 사이트와 화면은 `cmd_vel` 을 발행하지 않는다. 로컬 텔레옵은 로봇의 `/api/v1/teleop` 에 남고, 사이트가 그 경로의 필수 홉이 아니다. 로봇 ack 에 `TIMEOUT` 을 넣지 않는다(D-215). `FollowLane`, `PickObject`, `PlaceObject`, `Dock` ROS 액션을 추가하지 않는다. 스킬은 기존 TaskKind 이름이다. 명령 봉투의 `command_id`·`trace_id` 같은 필드를 스키마에 더하는 일은 별도 계약 결정이다.
4. **사이트와 AI 는 안전 정지의 조건이 아니다.** AI 출력은 `perception/evidence` 이거나, `/do` 가 이미 받는 intent 다. 최종 속도의 주인이 아니다. Pi 명령 경로에 decision provider 패키지를 두지 않는다. 원격 모델이 없어도 지금 규칙 경로가 로봇을 멈춘다. `DEGRADED`, `ESTOP`, `FAULT` 모드를 추가하지 않는다.
5. **로봇 화면과 사이트 화면은 갈라진 채로 둔다.** 로봇 화면은 `/api/v1` 이다. 사이트 화면은 fleet 의 HTTP·WS 다. 둘 다 ROS 그래프에 직접 속도를 내지 않는다. `core_api_web` 을 사이트 API 로 옮기지 않는다.
6. **제품 구성은 D-207 의 범위다.** Pinky 기록을 옮기는 시점과 내용(매니페스트, 천장, URDF)은 D-207 을 따른다. `products/pinky_pro/launch` 와 두 번째 `capabilities.yaml`, `runtime.profile.yaml` 을 만들지 않는다. `omx_adapter` 를 `omx` 로 개명하지 않는다. 버스 코드를 제품 폴더로 복사하지 않는다.
7. **학습 패키지와 관제 서비스 묶음을 만들지 않는다.** `src/ai`, `src/site/ai_worker`, `src/site/control_plane`, `src/site/operations_ui` 는 없다. 모델 제품 이름(YOLO, SAM2 를 포함한 목록)은 구조가 아니다. 학습 모델은 D-209 의 `backend_learned` 다. 에피소드·MCAP·챔피언 매니페스트는 이 결정의 일이 아니다. 세션 파일은 D-186 의 `data/teleop` 과 `data/drive` 다.
8. **로봇 링크의 전송은 지금 계약이다.** gRPC, MQTT, ROS 2 WAN 을 사이트에서 로봇으로 가는 명령 길로 열지 않는다. 센서·상태·정지의 QoS 는 기존 세 프로파일이다. 관제는 이미지를 받지 않는다.
9. **패키지를 새로 열기 전에 아래를 기록한다.** 주인이 누구인지, 그 상태의 정본이 누구인지, 최종 명령 주인이 누구인지, 로봇 로컬인지 사이트인지, 사이트나 AI 가 죽어도 정지가 되는지, AI 가 제공자인지, 화면이 기존 API 를 쓰는지, 전송이 도메인 계약 안에 들어왔는지, 기존 코드를 감싸서 되는지, 폴더를 옮기지 않고 소유를 말할 수 있는지. 답이 새 루트이면 이 결정을 대체하는 ADR 이 먼저다. 모듈을 나누는 조건은 `docs/plans/2026-09-06-module-split-criteria.md` 의 B1–B3 이다.

**Consequences:** v0.2 의 목표 트리는 스케치로 남는다. 다음 코드 변경이 그 트리를 만들면 이 결정을 어긴다. D-168 의 영역과 D-207 의 제품 범위와 D-209 의 학습 자리는 그대로다. `src/apps/control` 은 빈 남은 폴더이고, 지우는 일은 경로 시험과 함께 하는 별도 정리이다. 실행 순서는 [2026-09-25-ownership-naming-control-plane.md](../plans/2026-09-25-ownership-naming-control-plane.md) 다.

**Validation:** 문서 결정이다. 패키지를 추가하거나 옮기는 커밋은 이 결정이 Accepted 된 뒤에도 그 커밋의 경로 시험과 D-168 구조 시험을 통과해야 한다. 빈 디렉터리는 증거가 아니다.
