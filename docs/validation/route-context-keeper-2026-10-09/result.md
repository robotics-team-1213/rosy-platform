# D-531 P2 경로 문맥 입력 SOURCE 점검

- 후보 커밋: `a903e8ef462b` (`feat/route-context-keeper-input`). 공유 `main` 착지 전 후보이다.
- 실행: 모델 PC 원격 pytest `middleware/perception/test/test_route_context_input.py middleware/perception/test/test_lane_keep_bend.py middleware/perception/test/test_line_observer_wiring.py test/architecture/test_module_structure.py`.
- 결과: **107 passed, 2 skipped**, `known_failures.py` **NEW 0**. 원시 로그 `X:/DevTemp/route-context-keeper/run-1.txt`, SHA-256 `f2c96b54cceb2e4dba91566dccd613c111254707e6b9ca18341941b484bebbc8`.
- 확인한 것: 스키마 거부, clear·시계 역행·0.5초 경과·만료 시 문맥 폐기, 기대 굽이 창만 B9 입력, 기록된 SIM 굽이 클립의 입력 경로, ROS 노드 구독·관측/디버그 seq 배선, 구조 검사.
- **미확인:** 실물 라벨 434프레임의 기본 규칙 parity와 문맥 켬 HOLD→주행 집계. 원본 라벨 이미지가 원격 pytest 트리에 없어 해당 두 시험이 skip됐다. 이 집계와 독립 경계 검수 전에는 `route_context_enabled`를 켜는 주행 수용 근거가 없다. 폐루프 SIM, ARM64 실행, DEVICE, FIELD도 이 점검에 포함되지 않았다.
- 독립 안전 검토: 기본 꺼짐 SOURCE 착지는 가능하나 P2 수용은 HOLD. 굽이 `bending`·`reacquiring` 상태가 P1 스키마에 없어 접근 창을 지난 재획득에는 B9를 줄 수 없다. 오래되거나 순서가 뒤바뀐 영상 한 장이 현재 문맥을 폐기하는 동작은 정지 쪽으로 치우친다. 이 두 성질을 장치 활성 전 계약·재생에서 다시 판단해야 한다.
- 추가 로컬 노드 콜백 테스트: 프레임 10.1 s의 유효 문맥 `seq=7`이 `line/observation`과 `line/keep_debug` 양쪽에 실리고, 10.6 s의 만료 프레임에는 둘 다 null/부재이며 B9가 꺼짐을 확인했다. 이 테스트는 위 원격 107 passed에 포함되지 않는다.
