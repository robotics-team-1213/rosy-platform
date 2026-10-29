---
title: 가짜 협력 객체가 진짜에 없는 메서드를 가지면, 시험은 가짜를 증명할 뿐이다
date: 2026-10-01
category: workflow-issues
module: src/runtime/services/core_features/fleet_agent (FleetAgent ↔ core_events EventBus)
problem_type: test_failure
component: development_workflow
symptoms:
  - "FleetAgent가 종료 때 EventBus에 없는 unsubscribe()를 불렀지만 관련 시험이 모두 녹색이었다"
  - "시험용 가짜 버스 세 개(DummyEventBus, _EventBus, Events)가 모두 unsubscribe()를 정의하고 있었다"
  - "에이전트가 버스가 보관하는 EventMessage의 seq를 직접 덮어써 /api/v1/events 이력의 번호가 바뀌었다"
root_cause: wrong_api
resolution_type: code_fix
severity: high
related_components:
  - testing_framework
tags: [fakes, test-doubles, surface-parity, event-bus, fleet-agent, d-382, powershell, parameter-sets, sd-writer]
last_updated: 2026-10-29
---

# 가짜 협력 객체가 진짜에 없는 메서드를 가지면, 시험은 가짜를 증명할 뿐이다

## Problem

`FleetAgent`가 종료할 때 `EventBus`에 없는 `unsubscribe()` 메서드를 불렀다. 시험용 가짜 버스 세 개가 그 메서드를 정의하고 있어서 시험은 전부 녹색이었다. 같은 콜백은 버스가 보관하는 이벤트 객체의 `seq`도 덮어쓰고 있었다.

## Symptoms

- `agent.py`의 `_run`은 `finally`에서 `self.events.unsubscribe(on_event)`를 불렀다. 실제 `EventBus`(`src/runtime/events/core_events/events/bus.py:59`)에는 `unsubscribe` 메서드가 없고, `subscribe()`가 해제용 callable을 돌려준다(`bus.py:63-68`).
- `_run`의 `finally`는 `unsubscribe()`를 가진 가짜로만 실행됐다(한 시험은 `_run`을 통째로 바꿔 끼웠다). 실제 종료는 `stop()`의 태스크 취소로 `finally`에 닿는데, 거기서 난 `AttributeError`는 아무도 await하지 않는 태스크 안에 남아 겉으로 드러나지 않는다. 구독도 풀리지 않는다.
- 같은 콜백이 `ev.seq = self._event_seq`로 버스가 링 버퍼에 보관한 바로 그 `EventMessage`를 고쳤다. 버스는 같은 객체를 `history()`(`bus.py:70`), `/api/v1/events`, 감사 기록에 돌려주므로 로봇 자기 이벤트의 `seq`가 Fleet 전송용 번호로 바뀌었다.
- 발견은 시험이 아니라 로봇↔사이트 프로토콜 적합성 읽기 전용 리뷰였다([D-382](../../adr/D-382-robot-site-console-protocol-conformance.md) 발견 10, 2026-09-29). `seq` 덮어쓰기는 같은 ADR의 즉시 처리 항목 I4다.

## What Didn't Work

- **기존 시험:** 단위 시험과 통합 시험이 모두 녹색이었다. 통합 시험(`src/site/fleet/test/test_console_hub_integration.py`)은 실제 uvicorn Fleet과 실제 `FleetAgent`를 띄우는데도 버스만은 손으로 만든 가짜였다. 가짜가 `unsubscribe()`를 갖고 있으니 잘못된 호출이 통과했다.
  - `DummyEventBus` (`src/runtime/gateway/test/test_fleet_agent.py`)
  - `_EventBus` (`src/site/fleet/test/test_console_hub_integration.py`)
  - `Events` (`src/runtime/gateway/test/test_fleet_agent_mdns.py`)
- **가짜가 어긋난 방식은 하나가 아니었다:** 수정 뒤 통합 시험이 `TypeError: 'NoneType' object is not callable`로 실패했다. 그 가짜의 `subscribe`가 아무것도 돌려주지 않았기 때문이다. 가짜는 메서드 유무와 반환값, 두 군데서 실제와 달랐다.

## Solution

`FleetAgent._run`은 `subscribe()`가 돌려준 callable을 잡아 두었다가 종료 때 부른다. 콜백은 버스 객체를 고치지 않고 복사본의 `seq`만 바꾼다. 커밋 ff7da33f(2026-10-01), c86f5c10을 거쳐 `origin/main`에 반영.

이전:

```python
def on_event(ev):
    self._event_seq += 1
    ev.seq = self._event_seq          # 버스가 보관하는 객체를 직접 수정
    self._event_buffer.append(ev)
self.events.subscribe(on_event)
...
finally:
    self.events.unsubscribe(on_event)  # EventBus에 없는 메서드
```

이후(`src/runtime/services/core_features/fleet_agent/agent.py`):

```python
unsubscribe = self.events.subscribe(self._buffer_event)
...
finally:
    unsubscribe()

def _buffer_event(self, ev) -> None:
    self._event_seq += 1
    self._event_buffer.append(ev.model_copy(update={"seq": self._event_seq}))
```

가짜 세 개도 실제 표면에 맞췄다. `subscribe`는 해제 callable을 돌려주고 `unsubscribe` 메서드는 없다.

```python
class DummyEventBus:
    # Same surface as core_events EventBus: subscribe returns the unsubscribe callable.
    def subscribe(self, cb):
        return lambda: None
```

새 시험 두 개는 가짜가 아니라 실제 `EventBus`를 쓴다(`test_fleet_agent.py`). 수정 전 코드로 되돌려 돌리면 실패하고 수정 후 통과함을 직접 돌려 확인했다.

- `test_agent_run_unsubscribes_from_the_real_event_bus`: `_run`이 끝난 뒤 버스에 구독자가 남지 않는다.
- `test_agent_renumbers_a_copy_not_the_bus_event`: 에이전트 버퍼의 번호는 `[41]`, 버스 `history()`의 번호는 `[1, 2]` 그대로다.

## Why This Works

실제 `EventBus`의 구독 해제 창구는 `subscribe()`의 반환값 하나뿐이다. 그 값을 쓰면 호출이 실제 표면과 일치한다. 복사본에 번호를 매기면 버스의 객체는 처음 정해진 `seq`를 유지하고, Fleet 전송용 번호는 에이전트 버퍼에만 있다. 새 시험이 실제 버스를 쓰므로, 버스 API가 바뀌거나 에이전트가 다시 없는 메서드를 부르면 가짜와 상관없이 실패한다.

가짜는 그것을 쓰는 코드와 같은 사람이 같은 가정으로 만든다. 그래서 둘은 처음부터 서로 맞는다([A fixture written from the same model as the code is one belief, not two](a-fixture-from-the-same-model-is-one-belief-not-two.md)). 실제 클래스가 끼어야 가정 밖의 증거가 된다.

## Prevention

- **실제 협력 객체가 싸면 그것을 쓴다.** `EventBus`는 프로세스 안에서만 돌고 I/O가 없다. 가짜를 쓸 이유가 없었다.
- **가짜가 필요하면 표면을 묶는다.** `unittest.mock.create_autospec(EventBus, instance=True)`는 실제에 없는 메서드를 부르면 바로 `AttributeError`를 낸다. autospec의 `subscribe()` 반환값은 `MagicMock`이므로 callable 계약은 따로 지정한다.
- **손으로 쓴 가짜에는 표면 일치 시험을 붙인다.**

```python
import inspect
from core_events.events.bus import EventBus

def _public(cls):
    return {n for n in dir(cls) if not n.startswith("_") and callable(getattr(cls, n))}

def test_fake_bus_matches_real_surface():
    assert _public(DummyEventBus) <= _public(EventBus)   # 가짜에만 있는 메서드 금지
    for name in _public(DummyEventBus):
        assert (inspect.signature(getattr(DummyEventBus, name)).parameters.keys()
                == inspect.signature(getattr(EventBus, name)).parameters.keys())
```

- **클래스 API를 바꾸거나 호출을 추가할 때는 그 클래스의 가짜를 찾아본다.** 예: `grep -rn "def subscribe" src --include="test_*.py"`.
- **리뷰에서 볼 것:** 가짜에만 있는 메서드, 가짜와 실제의 반환값이 다른 메서드. 그 메서드를 부르는 프로덕션 코드는 거짓 안전 위에 있다.
- **구독자 콜백은 받은 객체를 고치지 않는다.** 버스는 같은 객체를 모든 구독자와 기록에 공유한다. 바꿔야 하면 `model_copy(update=...)`로 복사한다.

## Related Issues

- [두 도구가 주고받는 모양은 한 곳에 정의하고, 실제 생산자 출력을 실제 소비자에 넣는 시험을 하나 둔다](../logic-errors/producer-consumer-fixtures-hide-contract-drift-2026-09-30.md) — 같은 계열: 손으로 만든 fixture가 계약 어긋남을 가렸다.
- [A fixture written from the same model as the code is one belief, not two](a-fixture-from-the-same-model-is-one-belief-not-two.md)
- [test/conftest.py silently repaired PATH, so signing tests stayed green while the real writer failed](conftest-openssl-path-masked-a-production-defect-2026-09-24.md) — 시험 뼈대가 운영에 없는 것을 대신 채워 준 경우.
- [D-382](../../adr/D-382-robot-site-console-protocol-conformance.md) 발견 10, 즉시 처리 I4.

## 2026-10-29 재발: PowerShell fake는 parameter set도 일치해야 한다

Pinky SD의 full readback 뒤 bundle mount 단계에서 `Add-PartitionAccessPath`가 `AmbiguousParameterSet`으로 실패했다. legacy `prepare-rosy-sd.ps1`과 GPT `media-layout.ps1` 두 호출이 `-DiskNumber -PartitionNumber -DriveLetter`를 함께 넘겼고, 기존 fake도 그 세 인자를 허용했다. 실제 native `Get-Command` metadata에서는 ByNumber가 DiskNumber/PartitionNumber/**AccessPath**를 받고 DriveLetter는 별도 ByDriveLetter set이었다. 이름·인자 목록만 확인하는 이전 표면 검사는 서로 함께 쓸 수 없는 인자 조합까지 보장하지 않는다.

두 호출을 `-AccessPath "${letter}:\"`로 수정했다(소스 commit `0ab037ed493086cc116567084e40fc72c4799d99`). 기존 storage-cmdlet 회귀에 native와 같은 parameter set을 가진 advanced-function fake를 넣고 GPT/legacy, partition 1/2, 기존 letter 유무를 실제 binder로 검사한다. native metadata를 조회할 수 있으면 ByNumber 표면도 확인한다. **native module의 metadata/autoload를 먼저 끝낸 뒤 모든 fake를 정의해야 한다.** 뒤에서 Storage를 auto-import하면 native 명령이 fake를 덮어써 실제 CIM 접근을 시도할 수 있다. 최초 그 fixture 오류는 제품 binding 결함의 RED로 세지 않았다.

증거: tests-only commit `9db54285411f7b9d81c3172fdc017470f2f29c54` 원격 SD profile은 no-letter 네 사례가 실패하고 기존 mount 네 사례가 통과했다. metadata 순서를 고친 tests-only `64fa4f33fa`의 명시 승인된 Windows PowerShell fixture도 같은 causal RED였고, 두 행을 고친 뒤 같은 8개 fixture가 disk/partition/AccessPath assertion까지 통과했다. 이 Windows 검사는 실제 Storage 호출을 fake로 대체한 binding 검사이며 laptop pytest가 아니다. 수정 소스의 공식 원격 GREEN과 착지 증거는 해당 완료 기록에서 별도로 확인한다.

실제 복구는 새 소스와 별개다. frozen commit `1d8166cf59551f9669dd9ae5be120ef550ad1aec` 경로에서 운영자가 올바른 AccessPath로 먼저 mount한 뒤 공식 ResumeAfterWrite를 실행해 31,138,512,896 bytes의 GPT/FAT-aware image-prefix readback과 wrapper exit 0을 확인했다. resume receipt의 writer_exit_code는 null이 맞다. 이 기록은 재flash 없이 끝낸 MEDIA 복구이며 `0ab037ed49`를 카드에서 수용한 근거가 아니다. 원문은 Git 밖 `Rosy/artifacts/receipts/2026-10-29-image-001-fast/sd-001-recovery-attempt3/`와 `2026-10-29-sd-access-path/`에 보존한다.

다음 적용 조건: Storage 등 overload/parameter-set API를 fake로 바꿀 때는 native metadata와 허용 조합을 묶고, 실제 parameter binder가 잘못된 조합을 거부하는 RED를 남긴다. 장치가 없어도 같은 함수와 binding을 안전하게 실행할 수 있다. 단순 `param(...)`에 원하는 인자를 모두 나열하는 fake로 되돌리지 않는다.
