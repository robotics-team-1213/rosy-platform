# OMX ROS feedback 원본 시각 보존 — 2026-10-16

D-770의 실제 feedback 연결 준비에서 발견한 runtime 오류를 수정했다.
실물 profile·controller 활성화 수용은 이 기록의 범위가 아니다.

## 재현과 수정

기존 `RosArmCommandRuntime._on_joint_state`는 source header를 읽지 않고 매 수신마다
sequence와 monotonic 수신 시각을 새로 만들었다. 따라서 같은 메시지의 재전송으로
오래된 관절 위치를 최신 관측처럼 사용할 수 있었다. 이름/위치 배열의 `zip`과 dict
변환도 불완전한 배열·중복 이름을 먼저 검사하지 않았다.

`219ccd1bb`를 모델 PC의 실제 Jazzy/Python 3.12 환경에서 실행해 **1실패·7통과**를
확인했다. 새 회귀는 재전송으로 owner snapshot이 교체되는 지점에서 실패했다.
앞선 첫 시도는 ROS pytest plugin의 선택 의존성 누락으로 시작에 실패했으며, 오류
재현 증거로 세지 않는다. 필요 없는 plugin 자동 적재를 끄고 위 재현을 진행했다.

`joint_state_intake.py`는 다음 조건을 통과한 message만 runtime에 전달한다.

- 원본 timestamp가 양수이고 이전 수용 값보다 증가하며 미래/age 초과가 아님
- 이름·위치 배열 길이 일치, 중복 이름 없음, 필요한 관절 모두 존재, 유한한 위치
- source age를 owner snapshot 수신 시각에서 차감해 전송 지연을 freshness에 반영

거절된 message는 원본 시각 watermark·sequence·snapshot·watchdog을 갱신하지 않는다.
유효한 message가 끊기면 활성 goal은 기존 owner의 `joint_state_stale` HOLD/cancel로
들어간다. ready 상태에서 새 명령이 들어올 때도 기존 freshness admission이 적용된다.
같은 위치라도 새로운 원본 시각으로 온 실제 정지 관측은 수용할 수 있다.

## 실행 증거

`0e7cfbfba` 원격 검사 **11통과**, NEW 0:

- 원본 시각·전송 지연·재전송·역행·미래·오래된 값·배열 오류 등의 순수 검사 10개
- 실제 native ROS 시험 8개를 별도 process에서 실행하는 검사 1개

native 회귀는 실제 ROS node/runtime의 intake callback을 사용한다. 활성 명령의
pending action port만 경계 대역이며, stale HOLD와 취소 호출을 확인한다. 나머지 기존
native 시험에는 실제 DDS JointState 수신과 in-process ActionServer가 포함된다.
테스트 publisher도 실제 clock의 source stamp를 넣도록 수정했다.

원격 runner의 커밋된 worktree 안에서 같은 격리 Python 3.12 interpreter에
`/opt/ros/jazzy/setup.bash`를 적용한다. domain 113, localhost discovery, FastDDS를
사용한다. vendor launch·serial·모터·카메라를 사용하지 않는다. wrapper는 실제 ROS
시험이 skip되거나 실행되지 않으면 통과로 인정하지 않는다.

개발 PC 외부 로그 `rosy-il-python312/state-replay-red-native/run-1.txt`와
`rosy-il-python312/state-replay-green/run-1.txt`에 원격 결과를 보존했다.

## 남은 조건

source timestamp 검사는 publisher의 물리 출처를 인증하지 않는다. 합성 publisher도
새 시각을 낼 수 있다. 실제 owner의 graph/bus 배타성·실측 profile·보정·그리퍼 관측과
독립 정지 수용은 계속 필요하다. 실제 자동 시연 **0회**이며, observation-only bag을
demonstration으로 바꾸거나 모델 학습에 넣지 않았다.
