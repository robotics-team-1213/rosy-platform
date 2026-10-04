# Learning Fleet export implementation plan

**Goal:** 기존 Episode와 실제 DeviceActionReceipt의 정확한 상관 키를 검증하고 별도 export로 보존한다.
**Architecture:** learning registry 옆의 오프라인 도구가 기존 공통 Episode와 D-18 receipt를 읽는다. 원본 Episode/정책 단계는 바꾸지 않으며 기존 wire schema를 재사용한다. 결과는 인증이나 실행 허가가 아니다.
**Tech Stack:** Python, 기존 Pydantic wire validator, stdlib canonical hash.

## 구현과 검증

1. `learning/registry/policy/test/test_fleet_join.py`에 성공 receipt/unknown 과제 분리,
   action/attempt/device 불일치, 다중 키 모호성, 손상, output 덮어쓰기 거절 테스트를 작성하고 RED를 확인한다.
2. `learning/registry/policy/fleet_join.py`에 source 파일을 검증하는 CLI와 순수 join을 구현한다.
   단일 action/attempt가 모두 일치할 때만 mission/step/epoch/generation을 연결한다.
   null policy revision과 task unknown을 보존한다. 비일치도 명시적 unmatched 산출물로 남긴다.
3. 기존 Dataset snapshot의 실제 Episode를 사용해 파일 검증과 unmatched export를 실행한다.
   키 없는 시연에 mission/step이나 정책 실행을 만들어 넣지 않는다.
4. 관련 host suite와 문서 gate를 실행하고 독립 리뷰를 받는다.

## owner 경로 조사 결과와 후속

`operations/execution/api/plan.py`의 GrantBinding은 PICK_PLACE identity view이며
인증/권한이 아니다. `integrations/robots/omx/transfer_provider.py`는 기존
StopFence.run_if_open과 authority_epoch/dispatch_generation을 재사용한다.
CORE CommandManager의 nav/docking slot과 OMX ArmCommandOwner의 learned_policy
owner 문자열에는 policy artifact 신뢰·승격·lease 검증이 없다.
따라서 정책을 nav slot에 주입하거나 owner 문자열만 지정하는 것으로 목표를 달성하지 않는다.
현재 branch의 D-442 구체 wire 결정은 확인되지 않아 새로운 명령 API를 만들지 않는다.
후속 owner 구현은 승인된 설치 binding·실제 lease/fence·stale/HOLD/stop 및 rollback
readback을 기존 최종 writer에 연결해야 한다. 이 export는 그 실행 및 실물 수용을 증명하지 않는다.
