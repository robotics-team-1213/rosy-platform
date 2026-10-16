# OMX 실제 stationary Action 수용·취소 — 2026-10-16

[D-770](../../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)의 작은 단계 측정을 위한
실제 명령 경로 검증이다. 모든 모터 토크를 OFF로 유지한 채 현재 관측 위치만 목표로
보냈다. 실제 구동·물리 정지·자동 시연 수집은 아직 수행하지 않았다.

## 소스와 실행 경계

- owner/ROS adapter와 core_common은 committed `3b95fcab7`에서 archive했다.
  직전 문서 착지 `5c876425a`에는 이 코드의 변경이 없다.
- 앞선 [실제 feedback 검증](../omx-native-controller-feedback-2026-10-16/result.md)의
  8-patch driver, 실제 controller manager 6.10.1 및 controller plugin 6.9.0을 재사용했다.
  현장 실제 실행 환경은 Lyrical/Python 3.14다. 공개 Jazzy 지원 수용으로 확대하지 않는다.
- private domain/namespace와 명시적인 hardware UNCONFIGURED 시작을 유지했다.
  실제 loaded driver·JSB·6관절 JTC의 경로를 maps로 검증했다.
- 고정 by-id 장치, 실제 device identity, unprivileged exclusive-open guard를 사용했다.
  원본 source/artifact 124개와 probe/guard source·parent receipt의 hash를 결합했다.
- 여섯 Torque Enable/Reboot 선택은 모두 0이다. 실제 native 상태가 fresh OFF/error0이
  아니거나 fault/deadline이 있으면 controller service를 진행하지 않았다.
- 모터별 PWM raw20, profile velocity/acceleration 각1, XL330 current raw50을 전후
  읽었다. 이는 기존 측정 시작용 제한이며 실측한 작업 범위·하중 수용값이 아니다.
- 자식 독립 40초 TTL과 소유 process-group 정리를 유지했다. service/수용/종료 대기는
  유한하다. 운영 service나 camera producer를 교체하지 않았다.

## 실제 owner → JTC → 취소 결과

실제 JSB 관절 상태 10개를 owner가 받았다. 단일 publisher의 node/namespace/GID를
기록하고 실제 Action server ready를 확인했다. 최신 상태의 여섯 위치 전체를 그대로
목표로 삼았으며 offset은 없다. duration은 1초, expected start와 허용 차이를 포함한다.
이 nominal coordinate 설정은 powered 측정용 보정·안전 profile이 아니다.

| 경로 | 실제 결과 |
|---|---|
| `runtime.submit` | accepted=true, state=active, reason=submitted |
| 실제 Action 수용 | `GOAL_ACCEPTED`, 실제 goal identity |
| owner 취소 요청 | state=hold, reason=cancel_requested, call_returned |
| 실제 cancel 응답 | `CANCEL_ACK`, acknowledged=true |
| 실제 result | `TERMINAL_RESULT`, status=5/CANCELED, result_code=0 |
| HOLD 재요청 | accepted=false, state=hold, reason=hold_latched |
| controller/hardware 비활성화 | 두 controller deactivate 성공, hardware inactive |
| native 종료 | CM exit_group(0), wrapper 0, 강제 종료 없음 |

event sequence는 1–3이고 모두 같은 command/goal identity를 갖는다. 각 event를
flush/fsync한 JSONL과 receipt의 event 목록을 대조했다. 별도 실제 기록 함수 검사에서
두 event가 두 줄로 재독출되는 것도 확인했다. 별도 RUNNING_FEEDBACK event는 없다.

수용 event로부터 cancel ACK까지 약5.4ms, CANCELED result까지 약50.9ms였다.
이는 한 번 실행의 local observer 시각 차이다. 물리 정지 시간·최대 지연·반복 성능
수용값이 아니다. 취소 result의 SUCCESSFUL error_code를 목표 도달 성공으로
집계하지 않는다. action status는 CANCELED이며 handle.succeeded()는 false다.

## 실제 송신과 상태

저장 strace의 unfinished/resumed syscall과 nested char FD를 복원해 분석했다.
모든 serial write는 완전 송신 byte count를 확인했다. 총172 packet이다.

| 종류 | 수량 | 검사 |
|---|---:|---|
| PING | 6 | 읽기 계열 |
| READ | 12 | 읽기 계열 |
| indirect mapping write | 84 | 여섯 ID의 정확한 기존 command/read mapping |
| FastBulkRead | 35 | 실제 상태 읽기 |
| goal SyncWrite | 35 | 주소224/폭4, IDs11–16 순서 |

모든 목표의 pre raw position 대비 최대 차이는1틱이다. 허용2틱 검사는 저장 송신의
사후 분석이며 transport에서 목표를 차단한 것은 아니다. 실제 Action1건과 주기적
goal write35회를 구분한다. torque/reboot/mode/offset 쓰기는 없었다.

실제 native torque/error 상태34개는 모두 여섯 OFF/error0이며 stamp가 진행했다.
관절 상태의 pre nominal 좌표 대비 최대 차이는 약0.001534rad(1틱)였다.
전후 cap/mode/offset 등 고정 설정은 같고 cleanup error는 없다. 현재/목표 위치 등
동적 register는 고정 설정 비교에서 별도 취급했다. 앞선 보존 실패 기록은 그대로다.

## 보존 위치와 해석 한계

Fleet private `~/rosy-test/omx-native-action-3b95fcab7/`에 source archive·expected hash·
probe·guard/parent receipt·before/after·description/YAML·maps·loader·stdout/stderr·
trace·action-events.jsonl·controller-receipt.json·wire-analysis.json을 보존했다.
full hash와 장치 identity는 private receipt에 남겼다. 원본 receipt의 checks_passed=false는
저장 분석 대기값으로 유지했고, 별도 wire-analysis의 all_checks_passed=true로 판정했다.

첫 saved-only 분석기는 Windows CRLF 때문에 shell 경로가 잘못 해석되어 실패했다.
원본을 보존하고 LF의 v2 분석기만 추가했다. 장치 실행을 반복하지 않았고 v2 결과는
저장 자료만 읽어 생성했다. 두 카메라의 advancing/fresh frame을 별도 확인·보존했으나
이번 Action과 동기화한 demonstration bag은 아니다.

이 결과는 실제 명령 수용·cancel terminal·HOLD latch·토크 OFF lifecycle 비활성화를
증명한다. powered stop, 독립 물리 정지, 단절 시 부하 유지, 운영 owner 재시작 수용,
관절/그리퍼의 실측 이동 범위는 미완료다. powered 미세 이동을 수행하기 전에 이 정지
경로를 검증해야 한다. 실제 시연·IL eligible dataset·실데이터 학습은 계속0회다.
