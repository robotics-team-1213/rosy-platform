# D-630 perception·Drive·World·Situation 소스 이전 검토

검토자: `/root/safety_structure_review`, 2026-10-11. 판정: **APPROVE — 소스 범위**.

Perception에서 옮긴 172개 파일을 Git 기준으로 줄바꿈을 정규화해 독립 대조했다. 170개는 동일하며, sensing 초기화의 vision 경로와 PaintMap 리소스 경로 두 변경만 검토했다. SafetyNode·Drive 알고리즘은 동일하고, 활성 센서 제공자의 `sensor_only` 구성도 유지한다. 기존 `control` import·ROS 배포 식별자와 `rosy.sensor_provider` 진입점을 유지한다.

Pinky 개발 이미지의 다섯 Drive 원본 COPY, Docker 문맥, 모델 코드 서명·해시·필수 원본 검사, 모델 PC 검토 release와 Safety manifest의 실제 원본 namespace를 함께 검토했다. 설치 목적지는 기존 경로를 유지한다. sdist는 선언한 Drive 원본만 포함하고 wheel은 기존 namespace에 한 벌을 설치한다.

World의 MapPose와 Situation의 traffic/context/vision 구현은 이전 원본과 동일하다. stuck analyzer는 이동한 협력자에 대한 import만 바꿨다. 기존 Fleet·Situation module alias는 객체와 monkeypatch 식별자를 유지한다. World 상태 계산에는 표준 라이브러리만 필요하며, 최종 명령·Fleet admission 권한을 추가하지 않는다.

이 승인은 원격 source suite, 분리한 sdist→wheel 설치 증명, Docker 이미지·ROS 실행·장치 수용을 대신하지 않는다. `map_v2_fleet`와 `260919 MAP FILE.STL`의 계보를 유지한다. 행동 조건부 미래 예측은 별도의 계약·구현·수용이 필요한 후속 계획이다.

Control 크기 기준도 독립적으로 재검토했다. 선언된 perception과 Drive holder의 고유 production 파일은 233개, 34,855줄이며 Nav2와 별도 vision unit은 제외한다. 기존 34,619줄에서 늘어난 236줄은 package/source facade의 실제 설치·호환 overhead다. 기존 package 분리 의무와 추가 150줄 상한을 유지하며, 크기 기준을 바꿔 새 동작이나 별도 코드 유입을 숨기지 않았다.
