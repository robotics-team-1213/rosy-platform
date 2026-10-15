# OMX 실제 관절 피드백 관측

2026-10-15, `fix/omx-native-initialization`, 실행 코드 `7e83db760`.
사용자는 현재 상부 카메라만으로 진행하도록 지정했다. 측면 카메라 추가는 선행 조건이 아니다.
이 기록은 [register 확인](../omx-follower-registers-2026-10-15/result.md)의 후속이며 실물 구동 수용이 아니다.

## 실행

확인된 우측 follower에 `hardware_observer.py --domain-id <workcell-domain> --duration 120
--device /dev/serial/by-id/<confirmed-follower>`를 현장 native Lyrical에서 실행했다.
고정 SDK와 기존 `register_probe.py`의 PING/READ whitelist·독점 포트를 재사용했다.
별도 프로세스에서 `/omx_commissioning/joint_states`를 30초간 구독했다.
새 서비스 자동 시작, Action server, controller activation, 모터 설정·torque·목표 쓰기는 없다.

| 확인 | 결과 |
|---|---|
| 관측 프로세스 | 120초, 1,197개 완전한 register snapshot, exit 0 |
| 독립 ROS 수신 | 30초, 301개, 최대 age 0.020568초 |
| 수신 오류 | joint 순서·stale·nonadvancing 0 |
| publisher | `rosy_omx_readonly_observer` 1개 |
| 각 snapshot | 6개 모두 torque 0, hardware error 0 |
| 동시 포트 접근 | 두 번째 reader가 첫 패킷 전 busy로 거절됨 |
| 종료 뒤 접근 | 포트 재획득·register 재독출 성공 |
| 전후 설정 대조 | ID/model/firmware/mode/drive/homing offset/position limits/velocity limit 동일 |

일정 기간이 끝나면 프로세스는 종료한다. 지금 계속 운용 중인 제어 서버로 표현하지 않는다.
raw position은 현장에서 수동으로 자세를 바꾸면 달라질 수 있고, 실제로 앞선 snapshot과 달랐다.
사용자가 움직인 자세 변화를 자동 명령 결과로 기록하지 않는다.

## 코드와 실패 경계

- 여섯 ID와 model을 확인하고 읽기 시간이 250 ms를 넘으면 해당 snapshot은 발행하지 않고 실패 종료한다.
- torque on 또는 hardware error도 실패 종료한다. torque off를 명령하지 않는다.
- 수신 시작 시각을 stamp로 사용한다. 실제 register를 nominal vendor rad로 환산하며 Homing Offset을 이중 적용하지 않는다.
- 관측 topic은 기존 synthetic `/joint_states`와 분리했다. 물리 영점·jaw·TCP는 미검증이며 운영 owner 입력으로 사용하지 않는다.
- Fast DDS와 localhost discovery를 고정하고 static peers를 비운다. 외부 DDS override는 거절한다. 로컬/privileged 프로세스에 대한 보안 격리 인증은 아니다.
- 독립 검토의 discovery 상속·cleanup 예외 지적을 보완했다. 실패 종료에서도 마지막 JSON 요약을 보존한다.
- 원격 RED→GREEN, 관련 33시험 통과·known_failures NEW 0. freshness guard를 메모리에서 완화한 mutation은 stale snapshot 검사에서 RED, 원본은 GREEN이었다.

## 증거 위치와 남은 범위

비공개 X: 세션 `2026-10-15--042252--inference-integration--f27cbc`의
`evidence/omx-observer-7e83db760/{observer.jsonl,subscriber.json,exclusive.json,after.json,result.json}`,
`logs/observer-*`에 원문을 보관한다.
실행 파일 SHA-256:

- hardware_observer.py: `4231823a939dc90b04cfe5d22d2222b27d9719aac42b40946f4f04b45fc9edd0`
- register_probe.py: `a9fd080addf0bd1ed12aa54cb873a32b7472b748e498ddd92484271cb9357110`

관측은 준비됐으나 실제 trajectory controller/owner 연결은 아직 없다. 기존 vendor 초기화에는
설정 쓰기·torque·reboot 경로가 있어 이 observer로 대체했다고 주장하지 않는다.
현재 환경에서 다음 순서는 설정을 보존하는 초기화, 측정한 좁은 시험 범위와 독립 정지 확인,
명령/feedback/terminal을 묶은 감독 시험이다. 시야 밖 높이·간섭·기구 한계는 상부 영상만으로 확정하지 않는다.
