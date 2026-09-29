## D-342 실기 수동 한도는 녹화 증거로 한 계단씩만 올린다

**Status:** Accepted (2026-09-29, 절차 결정). 계단 값은 기기마다 기록으로 남기고, 이미지 기본값
(`rosy_default.yaml` `safety.manual_*`)은 이 결정으로 바꾸지 않는다.

### Context

실물 로봇 rosy-pinky-8kcn 의 수동 한도는 커미셔닝 값 **0.03 m/s · 0.1 rad/s** 다. 이 값에서
pilot 의 "중" 프리셋은 0.021 m/s · 약 4°/s 라 움직임이 거의 보이지 않고, 사용자는 반응이
느리다고 느꼈다. 한도를 한 번에 크게 올리면 모터·배선·정지 거리를 검증하지 않은 채 달린다.
CORE 는 이미 관리자 `PUT /api/v1/safety/limits` 로 기기별 한도를 바꿀 수 있다.

### Decision

1. 계단은 셋이다.

   | 계단 | manual_linear | manual_angular | 올라가는 조건 |
   |---|---|---|---|
   | L0 커미셔닝 | 0.03 m/s | 0.10 rad/s | 첫 부팅 기본 |
   | L1 | 0.06 m/s | 0.30 rad/s | L0 녹화에서 방향·놓으면 정지 확인 |
   | L2 | 0.10 m/s | 0.60 rad/s | L1 녹화에서 정지 거리 ≤ 3 cm, 명령 공백 < 500 ms |

   `max_linear`·`max_angular`(내비게이션 상한 0.2·0.8)는 넘지 않는다. CORE 가 둘 중 작은 값으로
   자른다.
2. **한 계단 올릴 때마다** 태블릿 실주행을 녹화하고(D-341 이후엔 영상 fps 도), 명령·오도메트리
   로그와 함께 증거로 남긴다. 사람이 로봇 곁에 있고 주변 30 cm 이상이 비어 있을 때만 한다.
3. 값은 관리자 API 로 바꾸며 기기 설정에 남는다. 내릴 때는 증거가 필요 없다(언제든 L0).
4. pilot 프리셋은 한도의 비율(저 0.4·중 0.7·고 1.0)이므로 계단이 오르면 자동으로 따라간다
   (설계 §10.1).

### Consequences

- 조작감 개선이 증거 없이 속도만 올리는 일이 되지 않는다.
- 증거 영상은 공개 저장소에 넣지 않는다(D-226). 경로와 요약만 모듈 logs 에 남긴다.

### Validation

- L1 적용 전후 `GET /api/v1/safety/state` limits 값과 녹화 요약(방향·정지 거리·공백)을 기록한다.

**Related:** [D-58](D-58-hardware-motion-requires-an-authoritative-readiness-gate.md), [D-323](D-323-rosy-pilot-teleop-app.md), [D-341](D-341-pilot-live-driver-video.md).
