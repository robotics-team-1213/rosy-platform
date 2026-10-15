# Gazebo default robot profile closure

**Goal:** `colcon build --packages-up-to gz_sim`의 설치 묶음만으로 CORE가 기본
로봇 프로파일을 읽어 부팅할 수 있게 한다. 기존 구성 패키지 의존성을 고친다.

## 실제 실패

사용자 승인 후 실제 비현장 Gazebo 편대/HOLD 벤치를 실행했다. `4a45239a5f`의
빌드는 끝났지만 3개 CORE가 모두 `robot package 'pinky_pro' not found`로
종료됐다. `gz_sim/package.xml`이 core/control/description은 선언하지만
CORE의 기본 로봇 구성인 `pinky_pro`를 포함하지 않아 colcon closure에 빠졌다.
프로파일 패키지의 기존 CMake는 config를 ament share에 설치한다.

원시 증거: X: `pipeline-resources--0c429d/logs/swarm-hold/out/launch.txt`.
벤치의 exit 1과 헤더뿐인 CSV를 편대 수용으로 처리하지 않는다.

## 최소 수정과 검증

1. 기존 `test_gz_package_contract.py`에서 CORE의 실제 `DEFAULT_ROBOT`이
   runtime dependency에 포함되는지 검사하고 committed HEAD의 원격 RED를 얻는다.
2. `integrations/simulation/gazebo/package.xml`에 해당 exec_depend를 선언한다.
   CORE를 특정 로봇에 묶거나 임의 source fallback을 만들지 않는다.
3. 원격 Gazebo 계약·구조 검사를 실행하고 실제 SIM을 재빌드한다.
   CORE startup 성공과 편대 무장/HOLD 결과는 구분해 기록한다.
4. package.xml 변경은 FULL 선택 대상이다. 사용자 승인된 main 착지는
   `tools/land.py --tests auto`의 실험실 FULL과 NEW 0을 통과해야 한다.
   별도 push/배포/장치 실행은 하지 않는다.

## 범위

기존 패키지의 누락된 연결 한 줄이다. 새 API·프로파일·시뮬레이터·모델 권한·
command writer를 만들지 않는다. map_v2_fleet와 STL lineage를 바꾸지 않는다.
이 편대 벤치의 공장 월드 결과를 현장 지도 또는 실물 주행 수용으로 쓰지 않는다.
