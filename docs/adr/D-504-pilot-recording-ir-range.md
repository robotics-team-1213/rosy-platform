## D-504 Pilot 녹화는 바닥 IR 원시값을 라이다와 같은 증거로 남긴다

**Status:** Proposed (2026-10-07, 사용자 지시: Pilot 녹화에 IR 센서값을 함께 넣고 초음파는 빼 둔다). D-411 A의 녹화 토픽에 하나를 더한다. D-411의 나머지(시작·정지·수신·조작부)는 그대로다. 실기에서 가방을 열어 확인하는 일은 별도다.

### Context

- Pilot이 켜는 녹화(`PILOT_TOPICS`)는 이미 `camera/front/compressed`, `cmd_vel`, `odom`, `scan`(라이다), `line/observation`, `teleop/intent`, `line/keep_debug`를 mcap에 넣는다. 제어 경로는 이 토픽을 읽지 않는다(D-2, D-411).
- 바닥 IR의 원시값은 `ir_sensor/range`다. `std_msgs/UInt16MultiArray` 세 칸이고 순서는 로봇 기준 좌·중·우, 12비트 ADC(0–4095)다. `ir_adc_node`가 약 20 Hz로 낸다. 헤더 시각은 없다.
- `line/observation`의 `IR_LINE`은 그 세기에서 만든 이탈이다. 원시 카운트는 없다.
- 전방 초음파는 다른 토픽 `us_sensor/range`(`sensor_msgs/Range`)다. 이번 녹화에 넣지 않는다.

### Decision

1. Pilot 녹화 토픽에 `ir_sensor/range`만 더한다. raw와 annotated가 같다. `us_sensor/range`는 목록에 없다.
2. PC가 가방을 프레임으로 풀 때(`bag_to_video`, `extract`) 각 프레임은 자기 로그 시각 이전의 최신 세 칸을 `side["ir_sensor/range"] = {left, centre, right}`로 붙인다. 칸이 셋이 아니거나 0–4095 밖이면 그 메시지는 버린다. 영상 스탬프에 묶는 증거(`STAMPED`)로 다루지 않는다.
3. Pinky 원본 대조(`raw_messages`)도 같은 모양으로 읽는다. 스냅샷 수확 목록(`RECORD_TOPICS`, `SIDE_TOPICS`, D-356)은 바꾸지 않는다.

### Consequences

- 발행자가 없으면 가방에 IR 메시지는 없고, session.json이 요청한 토픽 이름에는 남는다. `scan`과 같다.
- 20 Hz의 세 정수라 600초 상한·4 GiB 쿼터에 비하면 작다.
- 이미 받은 녹화본에는 이 토픽이 없다. 이 변경 뒤에 시작한 녹화부터 있다.
