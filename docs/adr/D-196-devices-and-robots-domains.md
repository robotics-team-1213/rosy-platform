## D-196 로봇은 장치의 조합이다 — `src/devices/<계열>/`과 `src/robots/<robot>/`을 두고, 로봇 지식은 그 안에만 둔다

**Status:** Proposed (2026-09-24). D-147 §1·§2 일부와 D-168 P4 방향표를 대체한다. D-11/HWA-003, D-57,
D-44, D-163, D-169, D-171, D-192를 유지하고 확장한다. 설계와 재평가: `docs/plans/2026-09-24-multi-robot-structure-draft.md`.
실행: `docs/plans/2026-09-24-multi-robot-structure.md`.

**Context:** Rosy OS는 Pinky Pro, Pinky+OMX, 단독 OMX, 다른 주행 베이스(TurtleBot3, 메카넘)를 같은
CORE API로 돌려야 한다. `src/`는 역할 기준 6개 도메인(D-147)이고 로봇 축이 없다. 그래서 Pinky 지식이
6개 도메인에 흩어져 있다. core의 `profile.pinky_pro.yaml`, 사실상 Pinky 전용인 `hardware/bringup`,
sim 안의 URDF, nav2 반경, control의 `robot.yaml`과 센싱 기하, fleet의 반지름 상수가 그렇다. 또
`apps/omx_adapter`는 장치 어댑터인데 apps에 있다. 2026-09-24 기준 src 안에서 `pinky`를 말하는 제품 파일은 72개다.

**Decision:**

1. **도메인.** `src/devices/<계열>/<패키지>/`를 둔다. 계열은 `pinky_pro`, `omx`, `common`이고, 보드에
   딸린 부품은 그 계열 안에 함께 둔다. `src/robots/<robot>/`은 코드 없이 설정·URDF 조립·launch만 담는
   패키지다. `hardware` 도메인은 이동이 끝나면 없앤다. `devices/<계열>/` 안의 패키지에는 계열 접두
   이름을 허용한다. 이것이 D-147 §2를 대체하는 부분이다.
2. **P4 방향표 추가 행.** `devices` → core 계약, 같은 계열, `devices/common`. `robots` → core 계약,
   `devices`. `navigation` → core 계약, `devices`(전 `hardware`).
3. **거주지 규칙.** src 제품 파일의 `pinky` 리터럴은 `devices/pinky_pro/`와 `robots/pinky_pro*` 안에만
   둔다. 현재 위반은 `test/robot_literal_backlog.txt`에 집합 동일성으로 묶는다(D-168 P5).
4. **로봇 선택.** CORE는 프로필과 capabilities를 `robot.model`(환경 변수 `ROSY_ROBOT`, 기본
   `pinky_pro`) 패키지의 `share/<model>/config/`에서 읽는다. 절대 경로 오버레이(`/etc/rosy/*.yaml`)는
   그대로 우선한다. core는 로봇 패키지를 선언 의존하지 않는다. 동적 조회는 D-126 `sensor_provider`와
   같은 종류의 결합이다. 이미지는 `required-ros-packages.txt`로 로봇 패키지를 싣는다.
5. **계약(후속 단계).** 베이스 경계는 `ros2_control`이다(D-57). 최종 `cmd_vel`은 drive capability가 있을
   때만 CORE가 소유한다. 정적 층은 Profile v2의 장치 조합이고, 런타임 층은 US-010 `withhold_hardware_flags`이다.
   팔 동작은 CORE가 MoveIt 액션을 대행한다. 카메라는 `devices/common/camera`가 캡처하고, apps는 역할 이름으로 구독한다.
   센싱 코드의 배치 규칙: 로봇을 바꿨을 때 코드가 바뀌면 devices, 숫자만 바뀌면 apps에 두고 값은 프로필/TF에서 읽는다.

**Alternatives:** 최소 재편(`robots/`만 추가), `devices` 종류별 구분(bases/arms/sensors), 로봇별 최상위
폴더. 모두 기각했다. 근거는 초안 §Alternatives에 있다.

**Consequences:** 도메인 이동은 도메인당 1커밋으로 하고 동작 변경을 섞지 않는다. 이동은 이미지 릴리스
사이에 하고, 이동 뒤 첫 이미지는 D-191 평가표를 다시 통과해야 한다. `apps/control`의 장치 코드 분리는
D-171 트랙 3(control 분할)과 한 계획으로 묶는다.

**Validation / Transition:** P1 `test_module_structure.py`와 `test_robot_literals.py`가 녹색이어야 한다. P2
`robots/pinky_pro` 패키지와 core 시험이 녹색이어야 한다. P3에서는 이동마다 host 전체 시험, colcon build(WSL Jazzy),
2대 gz 벤치 결과가 이동 전과 같아야 한다. 백로그가 비고 두 번째 로봇 프로필(sim)이 같은 CORE API로 뜨면 Accepted로 올린다.
