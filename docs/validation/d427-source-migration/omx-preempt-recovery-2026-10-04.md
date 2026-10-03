# D-442 U3 선점·운영 복구 검증 — 2026-10-04

후보: `fix/d442-preempt`, 부모 `f17f4f906`. Accepted D-442와 인계의 즉시 U3 범위다. Arbiter 전용 preempt(reason)는 출처와 무관하게 현재 exact goal을 취소하고 owner HOLD를 래치한다. 반복 선점은 원래 사유·시퀀스를 유지하며 새 goal을 보내지 않는다. 기존 owner-matched cancel은 유지한다. 새 MANUAL 스트림과 우선순위 Arbiter 연결은 후속이다.

Fleet GET owner readback과 named-operator POST recovery를 기존 감사 INTENT/RESULT·bounded UDS transport에 연결했다. CellOwner가 같은 owner/local-stop/journal recovery adapter를 조립한다. 정확한 workcell/instance, peer UID, epoch/generation, strict true 확인, 최신 post-HOLD joint-state sequence와 calibration을 검증한다. local-stop → owner → journal 잠금 순서로 recovery와 stop·journal claim을 직렬화한다. PREPARED도 미해결로 막는다. 래치 해제 뒤 SQLite commit 실패는 같은 owner lock 안에서 HOLD로 되돌리고 503을 반환한다. ACK 유실 뒤 자동 재시도는 없다. 소유권 복구는 motion이나 RearmLocal을 실행하지 않는다.

## 호스트 근거

- 선점 회귀 최초 RED 8건, 수정 뒤 관련 owner/stop/구조 114 passed. 새 recovery API 최초 RED는 구현 부재였다. 독립 리뷰가 재현한 commit 실패 후 ready 잔류와 float status 허용은 각각 RED를 확인하고 회귀 시험으로 고쳤다.
- 최종 관련 Fleet route/transport, OMX API/owner/action journal, CellOwner composition/workflow, 안전 태그 및 구조: **152 passed, 43.14 s**. 로그: `X:/DevTemp/rosy-d427/resume/recovery-final.txt`.
- `test_named_http_to_actual_uds_dispatcher_and_owner_recovers_without_motion`은 실제 Fleet named 인증·SQLite 감사, transport recovery frame, ActionApi, OwnerRecoveryApi, owner/local-stop/journal을 연결했다. HTTP readback은 HOLD, recovery 뒤 ready이며 SDK goal은 0개다. `_exchange`와 UID는 시험 대역이므로 실제 socket/SO_PEERCRED 증거는 아니다.
- 실제 SQLite transaction 안의 journal claim 경합과 local-stop 경합을 결정적으로 시험했다. owner commit 실패 시험은 latch clear 뒤 DB commit 오류를 주입하여 503/HOLD 유지와 무동작을 확인했다.
- Fleet 29,264 줄은 독립 구조 재판정을 거쳤다. 기존 split 판정·분할 계획·600/800/>1000 예산·+150 허용은 유지한다. ActionStore의 기존 readback만 같은 owner의 helper로 추출하여 >1000 무성장 조건을 지켰다. 새 motion publisher는 없다.

## 판정 경계

SOURCE/호스트 후보 증거다. 전체 CI, 실제 UDS peer credential, ROS-SIM, ARM64 artifact, 실제 운영자 확인·정지·복구와 DEVICE/FIELD는 이 후보에서 NOT_RUN이다. simulation CellOwner composition만 연결했으며 물리 reset, 프로필 enable, 새 motion writer나 정책 dispatch를 추가하지 않았다. 독립 리뷰 `/root/d427_safety_review`: APPROVE, 추가 source/host blocker 없음. 리뷰어가 직접 152건 로그를 확인하고 HTTP 시험 8 passed를 독립 실행했다. lint·정리 결과는 같은 회차 로그에 남긴다.
