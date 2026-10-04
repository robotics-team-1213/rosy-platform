---
module: deploy
---

# 모델 PC Gazebo 준비와 pytest 수집 실패

2026-10-04 실제 모델 PC 관측이다. 운영 관제나 실제 로봇에 연결하지 않았다.

## 완료된 준비

Gazebo·Nav2 외에 Docker, joint trajectory controller와 CycloneDDS 설치를 확인했다. 잠긴 vendor source의 ROS 패키지 8개 컴파일과 workstation/pilot/probe 이미지 3개 빌드가 완료됐다. CPU·메모리를 제한한 순차 빌드였다.

격리 컨테이너에서 Python import 사전 검사가 통과했고, Gazebo world와 로봇 entity 생성이 확인됐다. 그러나 시험 수집이 실패해 Fleet→UDS→ROS fault 시험 자체는 실행되지 않았다. 첫 결과는 exit 1, cleanup exit 0이며 컨테이너 부재 검증은 true다. 이것은 G2 적재 수용 증거가 아니다.

## 원인과 수정

ROS의 자동 등록된 launch_testing pytest hook이 지정한 파일 외의 HTTP 시험을 import했다. Pilot 이미지의 HTTP 시험용 httpx 부재로 collection이 중단됐다. 선택한 module의 직접 import만 통과한 사실은 실제 pytest collection을 보장하지 못했다.

이 vendor probe는 자체 rclpy executor를 가진 동기 pytest이며 launch_testing fixture를 사용하지 않는다. 해당 probe에서만 외부 plugin autoload와 명시 plugin/addopts를 차단하고, generation-change의 정확한 단일 node를 collect-only로 확인한다. 1개 시험 수집이 확인된 뒤에만 Gazebo를 시작하고 같은 node를 실행한다. CORE나 장치의 운용 guard는 바꾸지 않았다.

관측된 collection failure를 RED로 삼았다. 수정된 실제 shell collection block의 일회성 제어 흐름 시험은 error/skip/zero collection을 거절하고 one collection만 통과하는 4개 경우를 확인했다. Linux shell syntax와 diff 검사 및 독립 source/retry 검토도 통과했다. 관련 source/harness 시험은 89 passed/13 existing warnings였다.

수정 retry는 기존 이미지를 사용하고 고유 컨테이너 이름·증거 디렉터리로 첫 결과를 보존한다. network none, 장치 grant 없음, source/root filesystem read-only, 소유 label 확인 후 bounded cleanup을 유지한다. 원본과 retry 로그는 `X:/DevTemp/rosy-cell-isaac-20261004/`의 private evidence로 보관한다.

## 실제 retry 결과

사용자의 모델 PC terminal 실행 후 결과를 직접 확인했다. 정확한 generation-change node 1개가 수집됐고 실제 vendor Gazebo 시험은 1 passed in 6.62s였다. 로그에 arm controller 활성화, action goal 접수·승인, cancel 요청과 취소 callback 처리까지 기록됐다. outer result exit 0, cleanup exit 0이고 소유 컨테이너 부재 검증은 true다. 실제 실행한 probe의 SHA-256은 로컬 수정 source와 일치했다.

이는 Fleet→UDS→실제 simulated ROS Action의 generation 변경 fault 경로에 대한 증거다. 16-box recipe의 실행, 독립 block-pose 증거, 두 팔레트·두 층 전체 Job 완료 또는 실제 장치 수용을 뜻하지 않는다. 전체 G2와 Isaac 주행 수용은 HOLD를 유지한다. Raw evidence는 private `gazebo-retry-run1` 폴더에 보관했다.

## 교훈

의존성 준비 gate는 실제 시험 도구의 collection까지 실행해야 한다. 직접 module import를 확인한 뒤 simulation을 먼저 시작하면 외부 pytest plugin의 부수 import로 시험이 시작되지 않을 수 있다. image build, simulation spawn, test execution, semantic task acceptance와 cleanup을 각각 판정한다.
