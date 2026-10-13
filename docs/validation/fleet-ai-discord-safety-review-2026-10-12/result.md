# Fleet AI Discord 이력의 독립 안전 검토

2026-10-12. 검토한 최종 결합 소스는 `bdea36dd89`다. CI [38265134663](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38265134663)은 아래 9개 과거 커밋의 `Safety-Review` trailer 누락으로 scope에서 실패했고, GitHub 시험 job은 실행되지 않았다. 실패한 이미지 빌드는 취소 상태이며 서명·배포하지 않았다.

독립 reviewer `/root/ralph_quality`가 정확한 diff, 영향 호출부, 최종 소스와 후속 수정, 회귀 단언 및 종료 로그를 검토했다. 판정은 **필수 후속 수정이 모두 포함된 결합 소스의 이력 기록만 승인**이다. 중간 스냅샷을 단독으로 배포할 수 있다는 뜻이 아니다. 기존 D-430 `EXEMPT` 방식으로 정확한 9개 SHA만 기록하며 baseline, 안전 경로 분류, trailer 판정과 실패 기준은 바꾸지 않는다. 공개 이력도 재작성하지 않는다.

| 이력 commit | 검토 근거와 필수 후속 조건 |
|---|---|
| `d83cf43a1` | 원문·attempt·fresh admission은 `4ff29b07e`가 필요하다. owner ACK·resource 보호·경쟁 worker 완료에는 `aae232f11`, `8d4d752ee`, `ba3645264`가 추가로 필요하다. |
| `4ff29b07e` | 원문·withdrawal fence를 고친다. 독립 snapshot의 owner ACK·resource·경쟁 worker 처리는 위 세 후속 수정 없이 미완료다. |
| `1b75148ce` | native owner 연결은 docking admission 수정 `84331745a`와 cleanup·undock 수정 `675aa7bc6`가 필요하다. 중간 수정에서 도입된 stale callback 회귀도 마지막 수정과 함께 검토했다. |
| `1d709ffe2` | 초기 consumer는 proof·event·stop fence `db0037481`, ACK 불일치 거절 `0a4f7d41c`, withdrawal·restart 재검사 `041d567e6`와 아래 unsent·주입·boot·stop 후속 수정을 모두 요구한다. |
| `db0037481` | corrective delta는 승인한다. snapshot 단독 consumer closure는 아니며 `0a4f7d41c`, `041d567e6`, `b9dae83e3`, `80f54e300`, `b5efedabe`가 필요하다. |
| `b9dae83e3` | 정확한 unsent marker만 정리하고 row CAS를 강화한다. safety→decision import는 `80f54e300`까지 남으며 boot·cancel 증거는 `b5efedabe`가 필요하다. |
| `80f54e300` | safety lease owner의 decision import를 주입으로 제거하고 preparation·transport admission을 유지한다. 후속 boot·stop closure는 여전히 필요하다. |
| `b5efedabe` | 정확한 cancellation mapping·예상 boot ACK를 검증한다. stop closure에는 `3a8d211af`, `1dbea2742`, CORE producer 수정 `36c74cfaa`, idle closure `080eb36a7`가 필요하다. |
| `ed761a957` | live selected-run 재검사와 최종 CORE epoch binding은 known-unsent context 거절·orphan marker 정리 `7b0855fa2`와 함께 승인한다. |

결합 소스는 CORE 최종 `/cmd_vel` 및 Arm 권한, 불명 실행 재발행 금지, 정확한 native identity·claim generation, 첫 terminal 불변성, 지속된 후속 대화 권한을 보존한다. 후속 `4554e84c6`는 optional owner 증거 누락이 실제 안전 latch를 막지 않도록 한다. 승인 조건의 후속 수정은 모두 검토한 최종 소스에 포함되어야 한다.

검토자가 독립 확인한 원격 종료 근거는 통합 **10,162 + 4,650 + 5,002 passed**, 추가 gate **207 passed**, CORE **95**, 설치 **91**, site client **30 passed**다. 각 7개 로그의 `known_failures.py` 비교는 NEW 0이었다. 이는 최종 결합 소스의 호스트 회귀이며 중간 commit 개별 시험 결과가 아니다. 해당 원본은 세션 증거 `logs/integration-bdea36dd89/`와 각 구현 세션의 최종 로그에 보존했다.

이 기록의 엄격한 전체 이력 재검사와 도구 회귀, 새 commit의 GitHub CI·이미지 서명·설치, 실제 Discord 원문/회신, 로봇 실행·물리 정지·DEVICE/FIELD 수용은 별도 확인 대상이다. 소급 검토로 운영·물리 성공을 만들지 않는다.
