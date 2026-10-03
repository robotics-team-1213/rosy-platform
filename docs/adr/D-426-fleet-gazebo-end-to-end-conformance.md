## D-426 Fleet–Gazebo 연동은 실제 공개 통신 경로와 독립 운동 관측을 함께 통과해야 수용한다

**Status:** Proposed (2026-10-03, 사용자 요청에 따라 재검토한 ADR·구현 계획. 실제 시뮬 실행·실물 수용은 아직 하지 않았다).

### Context

우리는 실제로 동작하는 관제와 로봇을 필요로 한다. HTTP 200, WS 연결, 화면의 이동 표시, 가짜 생산자 시험 각각은 실제 로봇의 명령 실행과 임무 완료를 증명하지 않는다. 다중 운행에서는 공유 구간의 진입·점유·이탈, 장애 시 정지, 재시작 후 상태 대조까지 이어져야 한다.

현재 source 기준은 main `7c60571cd`다. Fleet navigation Task와 CORE 결과 상관(D-316), 통신 적합성(D-382), 위치 확정(D-395), 링크 상실(D-419)을 재사용한다. D-420의 다단계 Device Action은 Proposed이며 이번 v1의 선행 의존성이 아니다. D-421의 취소 의미도 구현과 대조한다.

`src/site/fleet/fleet/server/traffic.py`에는 경로 근접 판정이 있지만 빈 경로는 충돌로 보지 않는다. 이 계산을 공유 구간의 진입 허가로 사용해서는 안 된다. `docs/validation/map-v2-fleet-real-profile-2026-09-30/result.md`는 렌더 외형 비교이고 주행 합격이 아니다. 기존 `tools/run_fleet_sim.sh`는 전체 프로세스를 killall하므로 공유 PC의 새 검증 runner로 그대로 쓰지 않는다.

### Decision

1. **두 로봇·한 Fleet·한 지도부터 검증한다.** 교차로와 좁은 통로를 갖는 폐쇄 시뮬 코스에서 실제 Fleet/CORE/ROS/Gazebo 프로세스를 실행한다. 외부 클라이언트는 CORE REST/WS만 사용한다. ROS/Gazebo 관측기는 검증 전용이며 운행 명령을 내지 않는다. 현재 model-pose 기반 ideal odometry는 시뮬 전제로 명시하고 observer의 추가 truth 주입을 금지한다. 로봇별 CORE의 최종 cmd_vel writer 권한을 유지한다.
2. **통신과 운동을 별도로 증명한다.** identity/판/지도 일치→WS WELCOME/heartbeat→Task/attempt 하달→CORE 수락→실제 이동→CORE 종단 이벤트→Fleet 결과 투영→독립 도착 관측을 하나의 run 기록으로 묶는다. 수락은 완료가 아니고 취소 응답은 실제 정지가 아니다. fake producer는 LOCAL 증거다. observer의 ground truth는 Fleet/CORE 판단 입력으로 주입하지 않는다. 현재 Gazebo ideal odometry 사용은 제한사항으로 기록한다.
3. **진입은 허가, 점유는 사실로 다룬다.** 구간 ID/지도 revision/진입·출구/대기점을 명시하고 FREE→RESERVED→OCCUPIED→RELEASING→FREE로 기록한다. 불명은 UNKNOWN이다. Fleet 한 writer만 기존 Task DB 트랜잭션과 admission을 확장한다. 빈/낡은 경로·위치 미확정·다른 지도·출구 막힘은 진입 금지다. 시간 만료나 링크 상실은 물리적 이탈 증거가 아니므로 점유를 자동 해제하지 않는다. grant 만료는 실제 진입 시한이며 진입 경계에서 재검사한다. RESERVED도 이전 실행이 밖에서 비활성·정지했음을 확인하기 전 재할당하지 않는다.
4. **경로 분할만으로 진입 gate를 주장하지 않는다.** 먼저 대기점까지 goal을 보내고 허가 후 출구 goal을 보낸다. 그러나 Nav2가 corridor 밖으로 재계획할 수 있으므로 실제 실행 경로 제약과 robot-side 허가 검사를 구현·반증 시험해야 한다. 이를 보장하지 못하면 공유 구간 기능은 HOLD다. grant는 robot/Task/attempt/구간/지도 revision/만료/현재 dispatch generation에 결속하며 로봇 수락 측에서 검증한다. 필요한 wire 변경은 D-18에 따라 API Reference·공유 schema·생산자/소비자 시험과 함께 확정한다. 이번 문서는 새 REST 경로나 필드를 현재 계약처럼 선언하지 않는다.
5. **장애와 재접속도 수용 시험이다.** REST-only/WS-only/전체 blackhole, 반개방 연결, 결과 유실·중복·역순, Fleet/CORE 재시작, 위치 상실, 교차로 내 정지, 취소와 발행 경합을 분리한다. D-419는 FleetAgent 설정 및 WELCOME/heartbeat가 확인된 구성에서만 검증한다. 기본 STOP 정책 적용 시한과 실제 감속 완료 시간을 따로 측정한다. 시뮬 첫 profile은 최대 0.15 m/s·0.5 rad/s, 정책 적용 뒤 정지 ≤0.50 sim s·이동 ≤0.05 m·회전 ≤0.25 rad다. CORE와 독립인 base 명령 만료 bridge(0.30 monotonic s)를 구현하고 CORE kill을 검증한다. 현재 존재한다고 가정하지 않으며 bridge 사망 정지는 별도 한계다. 복구는 위치·Task·attempt·점유 조회 후 대조하며 이전 부작용 명령을 자동 재생하지 않는다. 재개 전 옛 세대를 차단하고 CORE 활성 correlation과 실행을 조회/취소해 비활성·신선한 정지를 확인한다. 확인 못 하면 새 하달은 금지한다. 재개는 대조와 명시적 재승인에 따른 새 실행이다.
6. **판정기는 독립 관측과 음성 대조를 갖는다.** Gazebo model pose/contact를 수집하고 의도적 접촉·잘못된 로봇 이동·성공 이벤트만 있는 정지 상태가 FAIL을 만드는지 먼저 시험한다. contact 계측이 없거나 원본 관측이 끊기면 충돌 없음으로 합격시키지 않는다. 위치/도착은 sim time, 통신 단절은 monotonic으로 잰다. pause/reset은 새 epoch로 처리한다.
7. **수치·반복·원본이 수용의 조건이다.** 시뮬 목표치는 도착 오차 0.10 m/10°, 정지 |v|≤0.01 m/s·|w|≤0.03 rad/s 1 s, footprint 경계 여유 0.10 m, contact 0건이다. 20 Hz 이상의 관측과 샘플 사이 이동 여유를 사용하며 빈 구간 >0.15 s는 INCONCLUSIVE다. 상세 M01–M08을 각각 seed 3개×3회 실행한다. 시나리오 검증 단언은 매 회차 PASS여야 한다. M08의 예상 관측 누락은 주행 INCONCLUSIVE와 시나리오 PASS를 구분하여 주행 불명을 합격으로 바꾸지 않는다. 평균/영상/정상 health로 실패를 상쇄하지 않는다. 임계값 변경은 새 판과 재실행으로 남긴다.
8. **실행과 원본 증거를 격리한다.** run별 포트/domain/namespace/GZ_PARTITION/프로세스·DB·설정/hash를 기록한다. 모든 Gazebo 참여 프로세스의 partition 일치와 두 회차 간 transport 차단을 검증한다. 남의 프로세스를 종료하지 않는다. 캐시·로그·rosbag·DB·영상·세션·build/install은 `X:/DevTemp/fleet-gazebo/<run_id>/`에 둔다. 시뮬에서 실제 로봇 설정/토큰을 쓰지 않는다. 공개 보고서는 secret 검사를 통과한 판정·hash·재현 입력 요약만 기록한다.

### Alternatives and Discussion

| 대안 | 장점 | 이번 판단 |
|---|---|---|
| 경로 전체 잠금 | 첫 두 대 검증이 단순 | 불필요한 대기가 커 공유 구간 예약을 선택; 비교 기준선으로 남김 |
| 구간 예약과 실제 진입 gate | 운영자가 대기 이유·점유를 추적 가능 | v1 권고. gate 미구현을 데모로 숨기지 않음 |
| 시간 기반 경로 예약/여러 Fleet/Open-RMF | 규모·다른 로봇군 연동에 유리 | 위치·통신·기본 실행 증거를 먼저 확보한 뒤 별도 ADR |

재검토의 핵심은 세 가지다. (a) 통신 timeout은 공간이 비었다는 증명이 아니다. (b) 목표 지점을 나눠도 실행 경로가 자동으로 제약되지는 않는다. (c) Fleet이 성공이라고 말한 것만으로 observer가 성공을 판정하면 독립 검증이 아니다. 따라서 통행권은 실제 수락·주행 gate와 연결하고, 점유 해제는 신선한 이탈 증거를 요구하며, 관측기는 별도 운동 증거를 사용한다.

### Implementation and Acceptance

구체 파일·의존·명령·실패 시험·M01–M08은 [구현 계획](../plans/2026-10-03-fleet-gazebo-conformance.md)에 있다. 기존 launch의 Agent 설정/manifest 부재와 contact 계측 부재를 선행 구현한다. 순서는 실행 격리→실제 통신/상관→독립 관측→진입/점유→장애/복구→반복 회차다. Vision은 추가 증거 경로로 별도 시험하고 미설정은 NOT_RUN. OMX·Isaac Sim은 장치별 실제 수락·운동/접촉·결과 계약을 갖춘 후 동일 증거 원칙으로 별도 수용한다.

이번 변경의 완료는 문서 검토와 계약/harness 검사다. T1–T6 구현, 실제 Gazebo 회차, ROS-SIM GO, ARM64 artifact, DEVICE, FIELD는 아직 미완료다. 실제 실행 전 모듈 gate를 승격하지 않는다. 실물 안전 거리를 위 시뮬 목표치에서 추정하지 않는다.

**Related:** D-2, D-12, D-18, D-79, D-316, D-382, D-395, D-407, D-419, D-420, D-421.