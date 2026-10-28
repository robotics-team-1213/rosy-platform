## D-788 OMX SIM의 단일 시계 수신을 전용 실행기로 분리

**Status:** Proposed

### Context

D-786 native 실행에서 관절 메시지와 ROS 시계의 표본이 어긋났다. run nonce
`11f524e3823e`의 결정 기록은 16.780초 packet을 local source clock 16.140초로
검사해 거절한 것과, owner_now 16.828초에서 관절 나이 0.720초로 HOLD한 것을 보존했다.
관절 callback 자체는 약 47µs였다. owner_now의 기존 읽기에는 steady bracket이 없으므로
시계 갱신 순서나 backward update를 이 기록만으로 확정하지 않는다.

고정 SDK와 기동 로그는 Gazebo 하나, 고유 partition, 단방향 GZ→ROS `/clock` bridge
하나를 보였다. 실제 publisher GID와 callback에서 관측한 역행은 아직 기록되지 않았다.
현재 TimeSource는 owner의 기본 callback group으로 시계를 받고, 다른 owner group과
같은 MultiThreadedExecutor를 쓴다. 별도 group과 다섯 thread만으로 최대 지연을 보장할 수 없다.

### Decision

격리된 OMX G2 SIM 구성에서 시계 node를 전용 SingleThreadedExecutor와 thread로 실행한다.
owner는 같은 ROSClock 객체와 기존 시계 기반 검사를 유지하며 state/watchdog/action/workflow
네 group을 별도 MultiThreadedExecutor에서 실행한다. 시각을 다시 찍거나 packet을
미래 시각인 채 수락하지 않고, source-age·wall-age·timeout·HOLD 기준도 바꾸지 않는다.

handoff는 owner runtime 생성·feedback 수락·executor 시작·Goal 전에 끝낸다.
owner와 clock node의 자동 TimeSource를 detach하고 parameter callback을 제거한 뒤
기존 clock 연결을 비운다. 하나의 명시적 TimeSource만 같은 owner ROSClock을 갱신한다.
`attach_clock`이 cached time을 즉시 적용하므로 실행 중 handoff는 허용하지 않는다.
두 node의 `use_sim_time=true`를 고정한다.

설치된 Jazzy Node는 공개 TimeSource accessor가 없고, detach_node는 parameter callback과
associated clocks를 지우지 않는다. 따라서 이 SIM helper의 private SDK 접점은
Node/TimeSource/Clock source hash와 구조를 확인하며, 예상한 node clock 하나만
연결됐는지 검사한다. 불일치·부분 초기화 실패는 Goal 전에 거절한다. SDK update 시
이 결합을 다시 검토해야 하며 일반 장치 runtime으로 확장하지 않는다.

시작 전 실제 `/clock` publisher가 하나인지, 타입·GID·offered QoS, 진행·수신 나이,
clock thread 생존과 고정 parameter를 기록한다. callback의 forward/backward 변화와
수신 시각은 고정 크기 scalar 관측으로 남긴다. callback에는 파일·네트워크 I/O나
owner lock을 넣지 않고, 관측 실패도 원래 clock callback 전달을 막지 않는다.
역행 clock frame을 조용히 걸러 정상 시계처럼 보이게 만들지 않는다.

owner.poll의 원래 owner_now 읽기 전후에 best-effort builtin steady 표본만 추가해
watchdog 기록과 묶는다. 원래 provider 읽기는 한 번이며 분기·예외·취소를 유지한다.
종료할 때 owner UDS/콜백을 먼저 멈추고 시계 실행기를 그다음 정리한다.

### 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-427 | SIM 기동 helper는 deploy, owner의 읽기·guard는 기존 adapter에 둔다. 새 최상위 holder가 없다. |
| D-429 | 같은 owner ROSClock과 승인된 SDK를 사용한다. CORE/Fleet/World/Decision의 책임을 옮기지 않는다. |
| D-430 | owner 시각 bracket은 관측 변경으로 독립 Safety-Review와 trailer를 받는다. 명령 권한이나 guard를 완화하지 않는다. |
| D-402 / D-403 | 기존 OMX owner·SIM 계획/목표 검증을 유지한다. 실제 장치와 full collision 수용을 부여하지 않는다. |
| D-786 | 동일 SSH release·격리·one-shot intent·정리 경로 안의 SIM 구성 수정이다. |

### Alternatives

미래 packet을 보관했다가 재검사하는 방법은 원래 steady arrival 보존과 intake/owner
전달 직렬화가 필요하다. watchdog에서 재검사하면 기존 단일 intake writer도 바뀐다.
그 별도 안전 계약을 추가하기 전에 시계 scheduling을 분리해 측정한다.
future/age 한계나 timeout을 늘리는 방법과 불명 Goal 재전송은 선택하지 않는다.

### Consequences and verification

이 결정은 scheduling 경로를 분리하는 실험이다. 동일 process의 GIL·OS 지연이나
DDS 역행/중복 발행을 해결했다고 가정하지 않는다. 한 owner clock, 단일 publisher,
clock 진행·역행 기록과 thread 수명을 실제 native 실행에서 확인해야 한다.

원격 회귀는 기존 source·guard/provider 읽기·HOLD 보존, 이전 TimeSource의 추가 갱신
불가, parameter 고정, 초기화 순서, 막힌 owner 작업 중 독립 시계 진행과 종료를 검증한다.
실제 box-only16 목표 확인과 프로세스 정리는 별도 수용이다. full G2 fault matrix,
실물 수용·적격 episode·학습 완료로 승격하지 않는다.
