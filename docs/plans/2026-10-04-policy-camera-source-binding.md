# 추론 원카메라 프레임과 수신 시각 보존

현재 candidate는 RGB SHA만 전달하고 session은 최신 camera snapshot과 비교한다.
추론 중 새 frame이 도착하면 유효한 원frame도 거절한다. 동일 RGB인 두 capture는 SHA만으로
구별할 수 없으므로 원 수신 시각을 함께 전달해야 한다.

로컬 Python candidate에 순서가 고정된 camera_received_at_ns tuple을 추가한다.
ACTInference는 immutable 원관측의 SHA와 실제 수신 시각을 그대로 내보낸다.
이는 공개 wire/API, 권한/승격 issuer가 아니다.

- capture_observation()은 기존 guard를 거쳐 frozen joint snapshot과 trusted provider camera snapshot을 반환한다.
- 기존 guard가 검증한 camera snapshot 집합만 bounded history에 기록한다. 관절 history와 같은 capacity를 사용한다.
- timestamp가 있는 candidate는 (ordered SHA, ordered receive ns)로 실제 검증된 원frame을 찾는다.
  원frame binding/나이/produced 시각 인과성을 final fence와 owner 제출 직전에 재검사한다.
- timestamp가 없는 기존 candidate는 최신 frame hash/causality 검사를 그대로 유지한다.
- 알려지지 않은·evicted·오래된·미래·시각 위조·count mismatch frame은 HOLD로 거절한다.
- 최신 입력 freshness/lease/epoch/generation/설치 pin/owner envelope/timing과 최종 writer는 유지한다.

카메라 공급자는 여전히 별도 trusted local capture가 필요하다. frozen metadata는 raw RGB를
직접 반환하거나 추론 소비 자체를 증명하지 않으며 실제 composition은 해당 SHA의 immutable pixels를 제공해야 한다.
원관측을 freeze할 때 capture_observation을 호출하거나 실제 poll로 해당 frame을 기록해야 한다.
이전 SIM 실험의50ms 실패를 완화하지 않으며 실제 SIM 실행/DEVICE/FIELD 증거는 별도로 필요하다.

검증: 새 frame/동일 RGB 새 capture가 inference 동안 도착해도 원frame 보존; unknown/evicted/stale/
spoofed/count 입력과 final fence 갱신 검증, ACT queue가 원 SHA/수신 시각 유지. 독립 D-430 리뷰 후 commit.
