# D-442 U3 OMX 선점과 운영 복구

승인 근거: Accepted D-442 U3 및 인계의 이전 직후 첫 안전 작업. 범위는 owner와 무관한 Arbiter 전용 preempt(reason), 항상 owner HOLD, recover 운영 호출 경로다. 새 MANUAL 스트림, 엔벌로프, 정책 출력, 물리 reset은 후속이다. 기존 owner-matched cancel과 local stop의 RearmLocal은 유지한다.

1. preempt 회귀를 먼저 RED로 확인한다. 실행 중 다른 출처 선점, exact-goal cancel 1회, 취소 전송 실패, 반복 선점의 래치 유지, 모든 출처의 HOLD 거부, fresh post-HOLD readback과 operator 확인 없는 복구 거부, disabled 및 invalid reason을 검사한다.
2. ArmCommandOwner는 현재 Arbiter와 Safety Guard를 함께 가진다. preempt는 그 객체의 내부 제어 진입점 하나이며 HTTP/Action RPC에는 노출하지 않는다. HOLD 전이는 기존 잠금과 _enter_hold를 사용하고 submit 또는 자동 재발행을 하지 않는다. 실제 standstill은 별도 증거다.
3. recover는 기존 함수에만 위임한다. 운영 transport 결정은 독립 리뷰 뒤 API Reference에 구체화한다. 제안은 현재 Fleet UID에 묶인 로컬 UDS의 별도 OwnerRecoveryApi이다. GetOwnerState와 RecoverOwner의 입력을 엄격히 검사하고 workcell/instance·확인·fresh observed sequence를 요구한다. LocalStop OPEN/current fence와 미해결 Action 없음도 확인한다. RearmLocal을 호출하지 않고 다른 래치를 해제하지 않는다. Fleet UID 권한과 named operator 확인의 전달 경계를 명시한다.
4. recovery adapter RED/green 및 운영 composition/UDS 시험을 추가한다. source→로컬 시험→ROS-SIM은 구분하고 안전 게이트와 구조 예산을 바꾸지 않는다. 독립 리뷰에서 발견한 결함은 RED 회귀 후 고친다.
5. 별도 frozen 증거, append-only logs, generate/lint, 관련 known_failures NEW 0, Safety-Review trailer, 깨끗한 커밋 재검증 후 이동 브랜치와 통합한다. 실제 로봇 동작은 이 단계에서 보내지 않는다.

현재 evidence: 초기 preempt 8 failed, 관련 owner·stop fence·구조 114 passed(25.53 s), X:/DevTemp/rosy-d427/resume/preempt-red.txt 및 preempt-green.txt. recover transport 독립 리뷰 진행 중.

## 독립 설계 확인

리뷰어 d427_safety_review는 preempt 소스를 조건부 승인하고 위 UDS recovery 제안이 Accepted D-442 범위(UDS 또는 Pilot API 허용)임을 확인했다. 확인→호출 사이 TOCTOU를 막는 직렬화가 핵심이다. Fleet에는 이미 require_named_operator와 POST begin_api_audit가 있으므로 새 recovery HTTP 표면도 그 경로를 사용한다. console_token/익명 fallback은 복구 권한이 아니다. true 필드만으로 실제 사람 확인을 증명했다고 기록하지 않는다.

운영 구현 대상: 별도 omx_adapter.owner_recovery_api, ActionApi 선택적 recovery adapter, OMX CellOwner composition, Fleet recovery route/UDS client 및 API Reference. request는 version 1·operation·정확한 workcell/instance·operator_confirmed strict true·observed_sequence strict nonnegative int·authority/generation·named actor로 한정한다. readback과 response identity도 검증한다. preempt·RearmLocal·submit은 이 표면에 없다. 취소 ACK는 standstill 증거가 아니다.

잠금 순서를 검토한다: local stop fence → owner lock → Action journal transaction. recover의 fresh readback 판정부터 래치 해제까지 owner lock을 유지하고, unresolved 검사부터 래치 해제까지 journal 쓰기와 직렬화한다. 반대 순서(DB writer → stop/owner lock)는 기존 취소·callback과 교착 위험이 있으므로 피한다. ActionStore의 기존 unresolved 목록은 PREPARED를 제외하므로 recovery guard에서는 PREPARED도 미해결로 취급할지 계약과 시험에서 명시한다. recovery는 새 동작을 보내지 않는다.

최종 호스트 관련 시험 152 passed(43.14 s). PREPARED는 recovery guard에서 미해결이며 commit 실패 후 HOLD 복원과 named HTTP→실제 dispatcher→owner 연결을 회귀로 검증했다. 최종 기록: docs/validation/d427-source-migration/omx-preempt-recovery-2026-10-04.md. ROS/실제 UDS·DEVICE/FIELD는 NOT_RUN.
