## D-903 cmd_vel 정지 시 50Hz 영(zero) 발행 억제 — 안전 검토 요건

**Status:** Proposed

**Date:** 2026-10-28

### Context

CORE의 `ros_bridge.py:198`이 50Hz 타이머로 `cmd_vel_cycle`을 호출하고, 매 주기
`_send_twist(Twist())`를 발행한다. 로봇이 정지 중이고 명령이 0인 상황에서도
매초 50개의 `geometry_msgs/Twist` 메시지가 DDS에 발행된다.

이는 CPU(직렬화·발행)와 네트워크(DDS multicast)에 상시 부하를 주며, 로봇 수가
늘어나면 DDS 도메인의 배경 트래픽이 선형으로 증가한다. 2026-10-28 시스템 전체
자원 조사에서 발견되었다(계획 2026-10-28-fleet-resource-bounds).

그러나 `cmd_vel`은 **D-430 안전 태그** 경로다. CORE가 `/cmd_vel`의 유일한
발행자(D-2)이며, 정지 신호의 지속적 전달이 물리적 정지 유지의 일부일 수 있다.

### Decision (Proposed)

정지 상태에서 **연속 zero 발행을 억제**한다. 단, 다음 안전 조건을 만족하는
경우에만:

1. **첫 zero는 반드시 발행**: nonzero → zero 전환 시 최소 1회 zero를 보내
   물리적 정지를 확정한다.
2. **zero 유지 확인 기간**: 안전 요구사항에 따라, 일정 주기(예: 1Hz)로
   "keep-alive zero"를 발행해 정지 상태가 유지되고 있음을 보장한다.
   Nav2·실물 모터 드라이버의 timeout 요구사항을 확인해야 한다.
3. **비상정지(e-stop) 경로는 절대 억제하지 않는다**: e-stop 시에는
   기존 50Hz를 유지하거나 즉시 zero를 발행한다.
4. **watchdog**: zero 발행을 건너뛴 시간이 일정 임계(예: 2초)를 넘으면
   강제로 zero를 발행하고 경고 로그를 남긴다.

구현 후보:
```python
def _publish_cmd_vel(self):
    cmd_vel_cycle(...)
    # 억제 로직 (개념):
    # if current.is_zero() and self._last_sent_was_zero:
    #     self._zero_skip_count += 1
    #     if self._zero_skip_count < KEEPALIVE_SKIP:
    #         return  # 발행 건너뛰기
    #     self._zero_skip_count = 0
    # self._last_sent_was_zero = current.is_zero()
    # self.cmd_vel_pub.publish(msg)
```

### Consequences

- **긍정**: 정지 중 DDS 트래픽 50Hz→1Hz(98% 감소), CPU 부하 감소
- **리스크**: 모터 드라이버·Nav2가 zero 타임아웃으로 "명령 상실"로 판단할 수 있음
- **완화**: keep-alive 주기를 실물 테스트로 확인, watchdog 임계값 안전 여유

### Safety-Review 요건

D-430 §5에 따라 이 변경은 다음을 필요로 한다:
- 실물 Pinky Pro에서 모터 드라이버의 zero timeout 동작 확인
- Nav2의 velocity timeout 파라미터 확인
- e-stop 경로가 억제에 영향받지 않는지 독립 검토
- `Safety-Review:` 트레일러 + 독립 안전 검토

### 관련

- 계획: `Rosy/docs/superpowers/plans/2026-10-28-fleet-resource-bounds.md` 항목 C(연기됨)
- D-2: CORE가 유일한 cmd_vel 발행자
- D-430: 안전 태그 경로 변경 절차
- 조사: 2026-10-28 시스템 전체 자원 누적 조사 (계획 v3)
