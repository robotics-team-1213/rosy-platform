## D-537 현장 일회성 기체 몸체 대조는 인증된 장치 시험과 연속 영상으로 판정한다

**Status:** Accepted (2026-10-09, 사용자 기체 ID 확인 요청; 운영 추적과 이동 수용은 별도)

### Context

두 Pinky의 `robot_id`와 호스트 ID는 장치에서 읽을 수 있지만, 현장 Rosy Cam 영상 속 어느 몸체가 어느 ID인지는 별개의 사실이다. D-472는 Fleet 운영 추적용 신원 LED 시퀀스를 정의하며 기존 하드웨어 자가 시험을 운영 신호로 재해석하지 않도록 한다. 현장에 아직 그 전용 신원 경로와 신선한 named track이 없을 때에도 설치·점검 담당자는 한 번의 물리 대조가 필요하다. D-529는 이 DEVICE/FIELD 확인을 로봇과 현장 PC에 배치한다.

### Decision

1. **일회성 대조.** 관리자가 각 로봇의 인증된 Web 장치 진단에서 램프 자가 시험을 한 대씩 요청한다. 요청 직전의 장치 `robot_id`·호스트 ID·설치 릴리스, 요청 ID와 완료 상태를 읽고, 같은 시간의 신선한 Rosy Cam 연속 영상에서 정확히 한 몸체의 램프 변화를 확인한다. 다른 몸체가 변하지 않은 대조 프레임도 보존한다. 요청 수락이나 장치의 `done`만으로 몸체 ID를 확정하지 않는다.
2. **증거와 수명.** 카메라 source, 영상 시각·순서, 설치 버전, 요청 ID, 관측된 몸체 위치, 원본 파일 해시를 함께 기록한다. 로봇 또는 카메라가 옮겨지거나 영상이 끊기면 이 몸체 위치 대조는 만료된다. 실패·가림·복수 후보는 `unknown`으로 남기고 다른 한 대의 ID를 소거법으로 채우지 않는다.
3. **권한 경계.** 이 자가 시험은 설치 점검의 수동 몸체 대조에만 쓴다. D-472의 Fleet 운영용 전용 점멸 신호, 신선한 확인 트랙, D-457의 지도 관측을 대신하지 않는다. 일회성 대조를 Fleet의 지속 `robot_id` 바인딩, `initialpose`, 지도 위치, 주행 허가로 자동 승격하지 않는다. 이동은 D-522의 별도 현장·CORE 조건을 다시 확인한다.
4. **시험 위치.** 장치 명령·읽기는 해당 Pinky, 영상·Fleet 확인은 현장 PC, 증거 비교와 기록은 개발 PC에서 한다(D-529). 브라우저나 호스트 pytest는 DEVICE/FIELD 판정으로 세지 않는다.

### Consequences

- 현장 운용자는 전용 D-472 경로가 설치되기 전에도 현재 주차된 두 몸체를 각각 식별할 수 있다. 이 결과의 유효 범위는 그 촬영 회차와 배치 상태다.
- 램프 자가 시험이 다른 상태 표시를 잠시 바꾸므로 시험은 정지 상태에서 한 대씩 수행한다. `ROSY_LAMP_ENABLED=false` 같은 평상시 절전 설정을 영구 변경하지 않는다.
- 현장 기록은 [2026-10-09 몸체 대조](../validation/pinky-physical-id-2026-10-09/result.md)에 남긴다. LCD의 실제 픽셀, Fleet named track, Web 이동은 그 기록의 완료 항목이 아니다.

**References:** [D-33](D-33-.md), [D-457](D-457-overhead-marker-priority-and-markerless-fallback.md), [D-472](D-472-rosy-cam-map-and-lamp-identity.md), [D-529](D-529-role-based-test-execution.md), [D-522](D-522-development-remote-motion-operator-authority.md).
