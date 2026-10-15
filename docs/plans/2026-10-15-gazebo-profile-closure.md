# Gazebo default robot profile closure

**Goal:** remote SIM 실행 구성에 CORE가 선택하는 기본 로봇 프로파일과 공통
계약 wheel을 포함해 부팅할 수 있게 한다. 로봇 선택은 실행기의 빌드 구성에 둔다.

## 실제 실패

사용자 승인 후 실제 비현장 Gazebo 편대/HOLD 벤치를 실행했다. `4a45239a5f`의
빌드는 끝났지만 3개 CORE가 모두 `robot package 'pinky_pro' not found`로
종료됐다. `gz_sim/package.xml`이 core/control/description은 선언하지만
CORE의 기본 로봇 구성인 `pinky_pro`를 포함하지 않아 colcon closure에 빠졌다.
프로파일 패키지의 기존 CMake는 config를 ament share에 설치한다.

원시 증거: X: `pipeline-resources--0c429d/logs/swarm-hold/out/launch.txt`.
벤치의 exit 1과 헤더뿐인 CSV를 편대 수용으로 처리하지 않는다.

## 최소 수정과 검증

1. 실행기의 빌드 선택 회귀가 임의 `DEFAULT_ROBOT`을 가짜 colcon에 전달하는지
   검사한다. committed HEAD에서 원격 RED 2건을 확인했다.
2. 빌드 시 checkout의 기존 `core_common.profile.DEFAULT_ROBOT`을 읽어
   `--packages-up-to gz_sim "$DEFAULT_ROBOT"`에 함께 넣는다. 이 build-time
   import에만 foundation 경로를 주며 runtime source fallback은 만들지 않는다.
3. 원격 Gazebo 계약·구조 검사를 실행하고 실제 SIM을 재빌드한다.
   CORE startup 성공과 편대 무장/HOLD 결과는 구분해 기록한다.
4. 최초 package.xml 수정안은 FULL을 실행했으나 제품 literal 경계 검사에
   거절됐다. 선언을 원복한 최종 변경은 착지 도구가 다시 선택한 관련 검사와
   NEW 0을 통과해야 한다. 최초 FULL을 통과한 것으로 처리하지 않는다.
   별도 push/배포/장치 실행은 하지 않는다.

## 범위

기존 패키지와 설치 도구의 누락된 연결을 고친다. 새 API·프로파일·시뮬레이터·모델 권한·
command writer를 만들지 않는다. map_v2_fleet와 STL lineage를 바꾸지 않는다.
이 편대 벤치의 공장 월드 결과를 현장 지도 또는 실물 주행 수용으로 쓰지 않는다.

## 실제 재실행에서 발견한 설치 관문

- `422c7c41e`: 17개 패키지 빌드와 기본 프로파일 로딩은 성공했지만 CORE가
  `ModuleNotFoundError: rosy.contracts`로 종료됐다. ROS-free wheel은 의도적으로
  colcon 대상이 아니며, remote SIM이 별도 설치를 빠뜨렸다.
- 기존 `deploy/robot/pinky_pro/image/install-motion-contracts.sh`를 colcon setup
  뒤 재사용한다. 실제 wheel을 실행별 install 아래 설치하고 그 site-packages를
  Python 경로에 넣는다. helper의 충돌 거절과 설치 경로 검증은 그대로 쓴다.
- wiring 회귀는 원격 RED 2 NEW 뒤 `4548a9d7aa`에서 33 passed, exit 0,
  NEW 0이다. 설치 실패 시 벤치를 시작하지 않는 경우도 포함한다.
- 실제 다음 실행은 `bdist_wheel` 부재로 설치 단계에서 거절됐다. 기존 scope 내
  의존성 캐시에 wheel/setuptools 빌드 도구를 포함하고 요구사항과 설치 recipe를
  함께 해시한다. 시스템 Python과 공용 pytest 환경에는 설치하지 않는다.
- 실제 SIM은 실행별 포트 예약과 CORE robot_id readback을 먼저 확인한 뒤에만
  편대 벤치로 진입한다. 기본 8080대 포트의 다른 서비스 응답을 부팅으로 세지 않는다.

원시 로그는 X: 관리 세션 `2026-10-15--111910--gazebo-profile--7ab1db/logs/`의
`swarm-hold-fixed`, `swarm-contracts-fixed`, `swarm-build-deps-fixed`에 보존한다.
`cbf3ab55bd`의 실제 wheel 설치와 helper import smoke가 성공했고, 3개 CORE의
`robot_id`를 직접 확인했다. 편대 벤치는 이어 `swarm.lead is not advertised`로
무장을 거절했다. identity 준비만으로 센서/capability 준비를 보장하지 않는다.
capability readback까지 기다리는 재실행은 당시 두 비현장 시험 PC의 SIM 가용
자원이 부족해 시작하지 않았다. startup 복구를 편대/HOLD 수용으로 합산하지 않는다.

## 전체 회귀에서 수정한 제품 경계

`93efce1d78`의 최초 FULL 18묶음은 25,944 passed, 1,848 skipped, 1 failed다.
신규 실패는 `test_robot_literals_stay_in_their_family` 한 건으로, generic Gazebo
패키지에 새 Pinky 이름을 고정한 점을 거절했다. D-196 §3·§4와 D-310을 다시
읽고 의존 선택을 remote 실행기로 옮겼다. backlog·known_failures·guard는
바꾸지 않았다. 독립 검토도 실행 구성에서 동적 선택하는 방식을 권고했다.

최종 `271f923283`의 원격 profile 선택·설치 성공/실패·제품 literal·Gazebo
계약 회귀는 36 passed, exit 0이다. 각 로그를 known_failures와 비교한다.
최초 FULL 원시 결과는 같은 X: 세션의 `logs/full-initial`에 보존한다.

## 검수 자료 검색 · 현재 읽기 전용 확인

사용자가 기존 검수 자료와 운영 승인 기록을 직접 찾도록 지시했다. 관리 세션과
가리킨 원격 저장소를 제한 검색했다. 실제 사람 검수 drivable 2,769장의 이미지와
마스크 총 5,538개 SHA가 모두 일치하며, lane v13 승인 표시 857장도 확인했다.
이 자료는 차선 내부 연결 바닥 의미이며 `road_surface/1` 독립 정답이 아니다.

현재 운영 review owner는 generation 324, 53프레임 중 excluded 23/pending 30/
approved 0이다. authority는 정상 갱신 중이며 `no_approved_masks`로 HOLD한다.
원본 proof는 한 capture group만 확인됐고 eval companion도 아직 없다.
실제 `ReviewPipeline`·`IndexedReview` 및 incident reasoning loader 소스는 존재한다.
입력 부재를 구현 누락으로 처리하거나 기존 검수 의미를 바꾸지 않는다.

조사한 실제 store/config/세션에서는 독립 signed 운영 수용 receipt를 찾지 못했다.
대화 semantic admission, 합성 GPU→READY와 offline export는 다른 증거다.
검색의 전역 완전성이나 운영 수용을 주장하지 않는다. 원격 경로·해시·현재 시각과
명령 범위는 X: 같은 관리 세션의 `evidence/acceptance-search.md`에 보존했다.
