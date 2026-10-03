# D-427 안전 경로 이동 독립 리뷰

- 날짜: 2026-10-04
- 리뷰어: 별도 `d427_safety_review` 에이전트. 이동 커밋 작성자와 다른 세션이며 읽기 전용으로 검토했다.
- 범위: `c402cc45e..6820c2dc5`의 22개 커밋. 브랜치 `fix/d427-resume`.
- 판정: 안전 실행 코드의 동작 변경을 발견하지 않았다. 이 판정은 소스 이동 리뷰이며 장치·현장 수용을 뜻하지 않는다.

| 이동 | 검토 커밋 | 결과 |
|---|---|---|
| signal firmware | `dd6238b08` | 실행 코드 R100; 폴더 노트의 링크만 변경 |
| dock firmware | `6ea10c14b` | 실행 코드 R100; 폴더 노트의 링크만 변경 |
| Fleet 안전 경로 | `040ef50ff` | 실행 코드 R100; `console.py` 문서 링크만 변경 |
| OMX owner·stop | `6b0bb9f02` | 안전 실행 코드 R100 |
| CORE safety·command·bridge | `21de6b578` | 안전 실행 코드 R100 |
| sensing 안전 subtree | 범위 전체의 perception 이동·잔여 수정 | 안전 subtree R100; 나머지 실행 변경은 `shared/web` source fallback 경로 |

안전 모듈은 17→17, 앵커는 35→35, 안전 root는 3→3으로 보존되었다. 앵커 값은 동일하며 모듈과 root는 새 경로로 대응한다. `KNOWN_SAFETY_VIOLATIONS`는 경로 대응 뒤 동일하고 21→21이다. `python tools/harness/safety_review.py origin/main HEAD`는 22개 커밋을 검사해 exit 0이었다.

비차단 문서 문제: `operations/fleet/fleet/server/console.py`의 `../../../docs/` 상대 링크는 올바른 저장소 문서 위치에 닿지 않는다. 실행 동작에는 영향이 없으며 후속 문서 정리 대상으로 남긴다.

로컬 원시 리뷰 출력: `X:/DevTemp/rosy-d427/resume/review/inspect.txt`, `commits.txt`. 이 경로는 이 머신의 임시 자료이며 영구 보관 증거가 아니다. ARM64 payload·SD 이미지 동등성, CI 전체 시험, 로봇 readback은 이 리뷰에서 실행하지 않았다.
