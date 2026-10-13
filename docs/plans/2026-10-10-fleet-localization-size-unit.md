# Fleet localization size unit (2026-10-10)

**목적.** `fleet` 패키지 판정(51,324, critic 동의)은 "다음 `lane_compliance` 증가는 `fleet/fleet/localization`을 자기 크기 단위로 등록한다"고 적었다. D-511 개정 2–6(경로 안내, 회전 자리, 한 바퀴 맥락)이 그 증가다. 이 계획은 그 등록이다. 코드를 옮기지 않는다.

**단위.** 이미 독립 Python 하위 패키지인 `operations/fleet/fleet/localization/`을 `SIZE_UNITS`에 더한다. 세는 파일은 그 안의 모듈 전부다.
- D-395 판정기: `arbiter.py`, `cues.py`, `trust.py`, `service_logic.py`, `pose_request.py`
- D-494 3 지도 자세: `map_pose.py`
- D-511 차로 판정: `lane_compliance.py`
- D-511 개정 6 한 바퀴 맥락: `lap_context.py`(새 순수 모듈)

로컬 main(D-607 P0 `fleet/fleet/stuck` 이동 뒤)과 합친 실측은 1,707줄이다.

**한 도메인인 이유.** 모두 "로봇이 지도 어디에 있고, 차로에 대해 어떤가"를 계산하는 순수 판단이다.
- 전송, asyncio, 로봇 호출이 없다. `test_boundaries.py`가 httpx, websockets, rclpy, asyncio, fastapi, `fleet.swarm`, `fleet.server` import를 막는다.
- 서비스 루프와 로봇 전송은 `fleet/server`에 남는다(`map_pose_service.py`, `lane_compliance_service.py`).

**부모 재판정.** `fleet` 패키지 실측은 49,802줄이다.
- 51,324 판정에 D-511 개정 3–6(+179)을 더하고 이 단위의 1,707줄을 뺀 값이다.
- 같은 변경에서 부모 판정을 49,802로 다시 정한다.
- 이후 각 단위는 기존 +150 규칙을 따른다. 파일별 600/1,000줄 판정은 그대로 검사한다.

**판정 상태.** 새 단위와 부모 재판정의 독립 검토를 요청했다(coordinator 경유). 검증은 `test/architecture/test_module_structure.py`의 실측이다. 크기 단위 등록은 SOURCE 구조 증거이며 SIM·DEVICE·FIELD 수용을 뜻하지 않는다.
