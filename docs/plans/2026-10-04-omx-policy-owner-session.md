# OMX policy owner session implementation plan

**Goal:** 고정 policy binding의 행동 후보를 기존 ArmCommandOwner와 LocalStopController를 거쳐 제출하고 lease/stale/HOLD를 집행한다.
**Architecture:** middleware local session은 승인된 issuer의 read-only authority callback을 요구한다. 내부 lease는 기존 AttemptIdentity/epoch/generation에 묶이며 wire API나 issuer를 만들지 않는다. 기존 stop fence가 최종 재검사와 owner.submit을 직렬화한다. 초기 구현은 default-disabled/SIM 전용이며 기존 runtime process를 켜지 않는다.
**Tech Stack:** Python stdlib, 계약 wheel, 기존 OMX command owner/stop fence.

1. 실제 ArmCommandOwner와 SQLite LocalStopController의 HOST fixture로 RED 테스트를 작성한다.
   default off, 정확한 후보 제출, expiry/revocation/generation/clock/stale/잘못된 episode·policy·nonce,
   원본 변조, 닫힌 fence, 취소/HOLD 재제출 거절을 포함한다.
2. `middleware/execution/local/src/rosy/execution/local/omx_policy.py`에 불변 lease/candidate와 session을 추가한다.
   owner controller source SHA 및 config envelope SHA를 설치 binding과 대조한다.
   local snapshot/sequence/time과 후보를 묶고 policy limits를 검사한다. lease는 짧은 installed TTL 이내이다.
3. final stop lock 안에서 authority/lease/time/artifact를 다시 검사하고 기존 owner.submit만 호출한다.
   실패는 session HOLD와 활성 정책 명령 cancel 요청으로 남긴다. cancellation을 stop readback으로 해석하지 않는다.
   명시 renew는 같은 lease identity/episode/policy만 유지하며 HOLD를 해제하지 않는다.
4. watchdog poll은 lease/관측·owner terminal을 검사한다. scheduler 실제 wiring/주기 실행 증거는 별도다.
5. safety module로 태그하고 독립 리뷰/관련 host·아키텍처 테스트, wheel·보고서를 보강한다.

## 경계와 수용

authority callback은 설치·승격 trust·scope·현재 lease를 판정하는 기존 trusted composition의
local 입력이어야 한다. caller bool이나 registry stage를 권한으로 받는 public endpoint는 없다.
구체 issuer, runtime process wiring, 실제 정책 admission 및 독립 SIM 과제는 후속이다.
합성 callback/모델 HOST fixture를 실제 승인/owner ROS 실행으로 표시하지 않는다.
physically real environment는 이번 session이 거절하며 물리 승인 경계를 유지한다.
Pinky CORE 연결은 별도이며 같은 final writer 옆에 publisher를 만들지 않는다.
