# D-870 군집 자세의 원본 측정 시각과 수신측 단조 시계 만료

**Status:** Accepted for implementation (2026-10-25, 사용자의 통신 개선 구현 승인). 계약·소스·시험·배포·실물 수용은 별도다.

## Context

현재 pose 스트림은 원본 자세가 멎어도 새 seq로 같은 좌표를 전송할 수 있다. 수신 시각만으로 stream timeout을 갱신하면 오래된 표본이나 지연된 backlog가 정상처럼 보인다. StateManager는 원본 pose의 wall/monotonic capture를 이미 보존하지만 stream이 그 근거를 전달하지 않는다.

로봇 간 UTC 차이를 모르면 원본 UTC에서 실제 전달 지연을 보장할 수 없다. 이 결정은 D-859의 별도 운영 수용을 전제로 하며 그 검사를 시간 동기 boolean이나 기능 광고로 대체하지 않는다.

## Decision

1. PoseSample에 선택 필드 `sampled_at`을 추가한다. 원본 자세가 실제 갱신된 UTC epoch 초이며 양수·finite 숫자만 허용하고 bool·문자열을 강제 변환하지 않는다. legacy payload의 모델 값은 None이다. Envelope.ts는 기존 송신 시각 의미를 유지한다. 원본 capture가 없으면 현재 시각을 대신 넣지 않는다.
2. 리더는 좌표·frame·map_id·원본 capture와 monotonic age를 같은 StateManager 잠금 안에서 읽는다. 기존 pose_sample의5개 tuple 계약은 유지한다. 미수신·음수·비유한·만료 age는 새 유효 pose를 발행하지 않는다. 동일 TF를 다시 읽어도 원본 capture를 갱신하지 않는다. 정상 정지 로봇이 새로 측정한 동일 좌표는 새 표본이다.
3. Fleet 일반 relay와 D-581 anchor 변환은 sampled_at을 그대로 보존한다. 좌표 변환이나 재접속 시각으로 다시 찍지 않는다. 무장 전에는 연결만 열린 상태가 아니라 유효한 원본 표본을 실제 받았고 아직 만료하지 않았음을 확인한다.
4. 공유 leaf helper `remaining_reference_s(sampled_at, now, timeout_s)`는 두 endpoint가 각각 D-859의 UTC 오차 상한50ms를 통과했다는 운영 전제 아래 최대 시계 차이100ms를 보수적으로 더한다. `age=max(0,now-sampled_at)+0.1`, `remaining=timeout_s-age`이고 remaining이 양수일 때만 반환한다. sampled_at이 now보다0.1초 넘게 미래거나 시각/기한이 잘못되면 사용 불가다. timeout≤0.1초에서 양수 예산이 없으면 사용 불가다.
5. 팔로워는 새 원본 표본을 수용할 때 remaining을 로컬 monotonic deadline으로 한 번 바꾼다. 같은/이전 sampled_at은 수명을 연장하거나 자취를 추가하지 않는다. pending 목표도 이 deadline이 만료하면 보내지 않는다. 소켓 재연결로 watermark를 지우지 않으며 새 follow 때만 상태를 초기화하고 최초 age 검사를 다시 한다. clock step 뒤에는 새 표본이 이전 watermark를 넘을 때까지 HOLD할 수 있다.
6. sampled_at이 없거나 잘못된 구형 producer는 수신 시각으로 보완하지 않고 유효 표본으로 쓰지 않는다. 한 프레임 때문에 소켓을 닫지 않고 기존 만료/HOLD 경로를 사용한다. anchor_hold도 원본 신선도 검증을 통과해야 생존 근거가 된다.
7. 구현한 로봇은 기존 capabilities의 `swarm.reference_freshness`를 실제 설치된 서비스의 지원 속성으로 광고한다. 이 값은 소프트웨어 지원이며 관측 시계 품질이나 현재 이동 가능 상태가 아니다. Fleet은 기존 lead/follow와 함께 이 지원을 전원에서 확인하고 구형/누락/불명은 무장 전에 거절한다. 설정 YAML의 boolean으로 구현 지원이나 UTC 품질을 만들어내지 않는다.

## 계약과 운영 경계

API reference v1.316의 additive payload/기능 광고이며 envelope1.0을 유지한다. 구형 모델 payload는 계속 파싱할 수 있지만 새 freshness-required 추종의 이동 근거로는 쓸 수 없다. CORE 최종 Base 명령·Safety·mode/lease/session과 독립 OMX 권한은 유지한다.

D-859 check가 실패하거나 품질을 확인하지 못한 실물에서는 이100ms 전제를 수용하지 않고 시간 의존 군집 운용/재개를 보류한다. 현재의 운영자 수용 절차를 명시하며, 이번 계약이 NTP 품질을 자동 측정하거나 모든 애플리케이션의 admission gate를 구현했다고 주장하지 않는다. 기능 광고·단순 NTPSynchronized·송신/수신 시각 자체는 오차 상한 증거가 아니다.

## 검증

공유 모델의 legacy None·strict epoch·잘못된 숫자, helper의100ms 경계·미래/만료·양쪽±50ms 보수성을 확인한다. consumer는 frozen producer+건강한 WS, 지연 backlog·중복/역순·재접속·pending 만료·시계 step·원본 TF capture 보존·동일 좌표 새 표본을 시험한다. Fleet은 구 peer 사전 거절과 원본 stamp의 anchor/pass-through 보존을 확인한다. 큰 기존 manager는 의미 보존 추출을 먼저 독립 착지하며 경계 시험은 추출된 파일도 검사한다.

호스트/시뮬레이션은 실물 radio·센서 timestamp·정지 거리·UTC50ms·재부팅 수용을 대신하지 않는다. NTP 품질이 미해결이면 FIELD는 계속 HOLD다.
