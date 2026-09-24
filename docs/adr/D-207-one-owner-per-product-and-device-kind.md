## D-207 제품과 장치 종류는 주인이 하나다

**Status:** Proposed (2026-09-24). 폴더를 이 문서에서 옮기지 않는다. 옮기는 순서를 고정한다.
잇는 결정:

- D-2, D-38: 최종 `cmd_vel` 은 `core` 하나다. 이 ADR 이 두 번째 명령 스택을 만들지 않는다.
- D-12: 미션은 fleet, 로봇은 원자 액션.
- D-168: 패키지는 `src/<영역>/<패키지>/`. 영역은 `core`, `devices`, `products`, `face`, `navigation`, `sim`, `site`.
- D-186: 스크립트와 수집은 주인 폴더만. 맵도 그 규칙을 따른다.
- D-196(예약, PR #36), D-206: `src/robots/pinky_pro/config/` 는 지금 만들지 않는다.
- D-169: `rosylib.LED` 는 벤치 전용이고 제품 버스에 없다. `SetLed` 와 `SetLamp` 는 다른 서비스다.
- D-205: `control` 을 나누는 시점은 인식 재작업(P1–P3)이다. 이 ADR 이 그 순서를 앞당기지 않는다.

**Context:**

1. **디렉터리 재배치는 끝났다.** `control` 은 `src/core/control`, 칩 패키지는 `src/devices`, `omx_adapter` 는 `src/products`, `emotion` 은 `src/face`, `games` 는 `src/site/games` 다. 패키지 이름은 그대로다. `src/apps` 에는 패키지가 없다.
2. **Pinky 몸통의 기록이 세 곳이다.** `devices/bringup/config/adapter.manifest.yaml` 은 `mobile_base` 와 `drive`, `battery`, `lidar`, `local_safety` 를 말한다. 차체 숫자(`robot.yaml`)는 `core/control/config` 다. URDF 는 `sim/description` 이다. 두 번째 모바일 베이스가 오면 복사할 단위가 종류가 아니라 bringup 전체다.
3. **조명이 두 서비스다.** CORE 브리지는 `set_led`(`SetLed`)를 부른다. 그 구현이 기대는 `rosylib.LED` 는 `bringup/rosylib` 에서 ImportError 다(D-169). 제품 스트립은 `lamp_control` 의 `SetLamp`, GPIO 19, WS2811 8픽셀이다. 한 스트립이 아니다.
4. **`control` 은 감지보다 크다.** 카메라·차선·보정은 여기가 맞다. 계획, 배회, 레거시 안전 노드, 미로 맵, 진단 웹이 같이 있다. Nav2 와 SLAM 은 `navigation` 이다. 최종 속도는 `core` 다.
5. **맵이 쓰임새로 이미 갈라져 있다.** 차선 월드 묶음은 `package://control/map/map_v2_fleet` 이고 gz 가 그 경로로 띄운다. 점유 맵은 `navigation/map` 이다. 그 밖 월드와 플러그인은 `sim/gz_sim` 이다.
6. **현장 펌웨어는 `src/` 밖이 맞다.** `signal/` 의 클라이언트는 `site/fleet` 이다. `dock/` 의 클라이언트는 `core_features` 도킹이다. 신호등은 관제 표시이고 도크는 몸통이 읽는 충전기다.
7. **대형 표와 코드가 한 줄 어긋난다.** 리더가 죽으면 관제가 `next_leader` 로 다시 연다. 죽은 팔로워만 빼고 리더를 유지하는 줄은 아직 없다.

**Decision:**

1. **제품 기록의 자리는 `src/products/<제품>/` 하나다.** Pinky Pro 는 `mobile_base`, OMX 는 `manipulator` 다. 기록은 매니페스트, 그 제품의 차체 숫자, URDF 다. `src/robots/` 는 만들지 않는다. D-196 이 머지되면 그 config 는 `src/products/pinky_pro` 로 옮기고, 세 번째 루트로 두지 않는다. 빈 폴더는 이 결정의 증거가 아니므로 파일을 옮기는 커밋에서만 만든다.
2. **장치 패키지는 종류로 닫고, 칩 이름은 구현이다.** 같은 종류의 두 번째 구현이 생기기 전에는 `imu_bno055`, `sensor_adc`, `lamp_control` 디렉터리 이름을 바꾸지 않는다. 그 구현이 생기면 디렉터리는 종류 이름이고 칩은 그 안의 파일이다. 새 칩으로 `src/devices/<칩>` 패키지를 추가하지 않는다. `bringup` 은 Pinky 구동·라이다·배터리·데드맨의 현재 패키지 이름이다. 제품 기록(결정 1)과 버스 코드는 다른 주인이고, 버스 코드를 제품 폴더로 복사하지 않는다.
3. **`SetLed` 와 `SetLamp` 는 합치지 않는다.** 상태 표시 서비스는 `led` 와 `SetLed` 다. 제품 스트립은 `lamp_control` 과 `SetLamp` 다. 셋 번째 조명 패키지는 만들지 않는다. `rosylib` 는 `bringup` 이 설치하는 배터리 대용이고 LED 구현이 아니다.
4. **감지의 자리는 `src/core/control` 이다.** 카메라, 차선, 보정, `road/observation` 은 여기 남는다. 최종 `cmd_vel` 은 `core` 다. 데스크 미로 맵은 control 묶음에 남는다. Nav2 맵은 `navigation` 에 남는다. Gazebo 월드 중 control 묶음이 아닌 것은 `sim/gz_sim` 에 남는다. 맵 폴더를 새로 만들지 않는다. `control` 의 계획·배회·레거시 안전 노드를 패키지로 떼는 일은 D-205 P1–P3 안에서만 한다.
5. **펌웨어는 `src/` 밖에 두고, 클라이언트는 부르는 쪽에 둔다.** `signal/` 과 `dock/` 을 colcon 패키지로 넣지 않는다. ESP 패키지를 만들지 않는다. 신호 클라이언트는 `site/fleet`, 도크 클라이언트는 `core` 도킹이다.
6. **대형의 멤버십 주인은 fleet 하나다.** 죽은 팔로워는 그 멤버만 빼고 리더는 유지한다. 죽은 리더는 기존 `next_leader` 절차다. 팔로워가 서로 다른 리더를 뽑지 않는다. 이 줄을 새 패키지로 만들지 않는다.
7. **학습 패키지를 만들지 않는다.** 커밋된 영상은 `data/teleop/learning/`, 재생 도구는 `tools/perception/`, 몸통의 인식은 D-205 의 자리다.

**순서:** 이 문서 다음의 첫 코드 변경은 결정 6(죽은 팔로워)이거나, 제품 숫자를 고칠 때의 결정 1이다. 결정 2의 디렉터리 개명은 두 번째 구현이 생기기 전에 하지 않는다. 안내 파일의 `hardware/`·`apps/` 경로는 그 파일을 다음에 고칠 때 현재 트리로 맞춘다. 경로만 고치려고 패키지를 옮기지 않는다.

**Consequences:**

- `src/AGENTS.md` 의 현재 트리가 이 결정과 충돌하면, 이 ADR 이 Accepted 되기 전에는 트리가 이긴다. Accepted 된 뒤에는 새 패키지의 자리가 이 결정이다.
- 이미지의 유닛 이름(`control`, `bringup`, `lamp_control`, `imu_bno055`, `sensor_adc`, `led`)은 결정 2의 개명 커밋 전까지 유지한다.
- 빈 `learning/`, `src/robots/`, ESP 패키지는 여전히 만들지 않는다.

**Validation:** 문서 결정이다. 패키지 이동과 죽은 팔로워 구현은 각각의 커밋에서 기존 경로 시험과 대형 시험으로 증명한다.
