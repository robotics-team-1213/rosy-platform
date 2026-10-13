# Gazebo drive 역사 커밋 안전 검토 · 2026-10-13

독립 리뷰어 `/root/drive_review`가 정확한 네 커밋의 원래 diff와 최종 통합본 `d157ccbf2`의 관련 경로를 검토했다. 판정은 **history-only SOURCE APPROVE WITH NOTES**다. 기존 D-430 검사기의 `EXEMPT`는 독립 검토된 역사 커밋을 기록하는 장치이며, 이번 후속은 아래 네 SHA에만 적용한다. 검사 범위·safety 태그·trailer 규칙·BASELINE은 바꾸지 않는다. 이미 푸시한 이력도 다시 쓰지 않는다.

| 정확한 역사 커밋 | 검토 범위와 조건 |
|---|---|
| `d02a45c9ed42` | sensor-only SDK worker 이름 분리와 CORE clock 전달. SDK가 최종 motor publisher가 되지 않는다. 즉시 실제 law 게시·설치·readiness 후속과 결합해 평가한다. |
| `f6731953a263` | D-735 이동 traffic 후보의 양축 공통 감속. HOLD와 제자리 회전 의미는 유지한다. 몸 경로·최종 발행의 완전한 후보 일치는 후속 D-737이 필요하다. |
| `9926a21c51a6` | 두 대상 파일에서 documentation을 제외한 AST가 부모와 같다. 실행 변경을 승인한 것으로 해석하지 않는다. |
| `3a7fd7323806` | 정책 실패의 window/traceback을 구분하고 writer 뒤 기록한다. 이 정확 diff에는 LINE static common clip도 포함한다. 당시 nontracking legacy family가 실제 common 고곡률을 누락할 수 있어 단독 수용하지 않는다. |

필수 후속 `c8286b9bf`의 checked pair·최종 동일 곡률/가속 방지와 `c20c8095f`의 전진·후진 union이 최종 `d157ccbf2`에 함께 존재한다. 독립 리뷰에서 candidate object·mode/input epoch, 최종 공통 ratio, 정책 None/예외 거절, raw SDK guard 및 CORE 단일 writer를 확인했다. deferred announce는 publisher 호출 이후의 기록이며 실제 wheel delivery acknowledgement의 인증은 아니다.

원문 diff 네 개, 전체 SHA, 판단과 제한은 세션 evidence의 `gazebo/leg3-review/d430-retrospective/`에 보존했다. 이 검토는 수신 순서·SOURCE 결합과 다음 원격 결과를 구분한다.

- 최종 통합본 원격 영향 회귀: 17,064 PASS·818 SKIP·세 invocation 각각 terminal 0/NEW 0. pre-push 추가 회귀: 289 PASS·terminal 0/NEW 0.
- 이전 C66 결합 실행 Leg13b: 약 0.374787m 이후 Fleet stall, 도착 false. CORE 장애물 HOLD는 자연 해제됐으나 SDK 회전 거절 뒤 native zero가 지속됐다. 현재 main의 전체 지도 실행이나 독립 완주 반복으로 확대하지 않는다.
- 첫 CI `38306497497`은 위 역사 커밋의 trailer 누락으로 scope가 실패했고 test matrix는 실행되지 않았다. 원격 회귀 통과를 CI 통과로 대신하지 않는다. 이 후속의 원격 시험·새 CI 결과는 별도 확인 대상이다.

장치 설치·ARM64·현장 감독·실물 주행·원본 지도 완주·새 ordinary moving-arc admission은 승인하지 않았다. 특히 기존 circle guard를 이 검토로 끄거나 trial 증명을 일반 속도에 재사용하지 않는다.
