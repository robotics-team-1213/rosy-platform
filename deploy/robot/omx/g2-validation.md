# G2 실행 하네스

`g2_runner.py`는 승인된 박스 전용 16회 시뮬레이션을 canonical Cell app 문서 저장·컴파일·서비스 제안, 별도 명명 운영자 승인, Fleet 발급 grant, UDS, 장치 owner, Gazebo 순서로 실행한다. `host-preflight`와 `preflight`는 제안·승인·grant·움직임을 만들지 않는다. `run`에는 `--approve-isolated-simulation`이 필요하다.

원본 레시피는 별도 영수증에 보존한다. 박스 전용 파생 레시피에서만 간지를 제외하며 원본 간지 계약과 작업자 간지 확인 기능은 `NOT_RUN`이다. 측정 프로세스가 실제 Gazebo 모델 위치, clock, ROS 그리퍼 관측을 읽는다. DetachableJoint는 `SIM AID`, 그리퍼 판정은 `SIM GRIPPER`로 표시하며 물리 파지 또는 실제 장비 수락으로 해석하지 않는다.

각 grant는 실제 Fleet dispatcher만 발급한다. staging은 grant를 변경하거나 재발급하지 않고 같은 객체를 UDS로 한 번 전달한다. owner의 기존 workflow 및 최종 stop/fence 잠금 안에서만 보조 joint를 붙이고 분리한다. 보조 실패, 만료, 불명확한 제출, 오래된 관측은 실패하며 자동 재제출하지 않는다.

격리 컨테이너는 network-none, 장치 비노출, read-only root 및 `/repo`, 별도 `/evidence` 쓰기 마운트, loopback DDS domain 137을 사용한다. Fleet HTTP는 컨테이너 loopback에만 열린다. 임시 인증정보는 0600 영수증 디렉터리에 저장하며 HTTP 증거에는 넣지 않는다. 부모 실행기는 컨테이너 label 소유권, 종료·삭제, daemon 접근 및 실제 부재를 확인해야 한다. 내부 실행기는 생성한 프로세스 그룹만 종료하고 부재를 확인한 뒤 결과를 저장한다.

예시(검토된 이미지와 빈 증거 디렉터리를 먼저 준비):

```sh
python /repo/deploy/robot/omx/g2_runner.py --mode preflight --evidence /evidence/preflight
python /repo/deploy/robot/omx/g2_runner.py --mode run --approve-isolated-simulation --evidence /evidence/run
```

박스 전용 성공은 `HAPPY_PATH_PASS`이다. 중단·fence 변경, seat 배타, 제출 응답 유실, owner/Fleet 재시작, 지연 성공 fault matrix는 별도 실행 증거가 있어야 하며 현재 runner는 `full_g2=false`, `fault_matrix=NOT_RUN`을 고정한다. SDK 이미지 폐쇄성 및 실제 실행은 호스트 preflight 결과로 수락하지 않는다.

이 구성은 읽기 전용 후보 소스의 import와 SHA 목록으로 SOURCE / ROS-SIM 증거를 만든다. 설치 wheel의 ARTIFACT 폐쇄성은 `installed_wheel_artifact_closure=NOT_RUN`으로 따로 표시한다. Dockerfile의 정확한 Fleet Python dependency pins도 제품 wheel 수락을 대신하지 않는다.
