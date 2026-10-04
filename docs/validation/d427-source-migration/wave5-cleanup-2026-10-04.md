# D-427 wave5 정리와 CI 환경 오류 수정 — 2026-10-04

후보는 `refactor/d427-wave5-final`의 `bcf1010b2a1e` 기준 작업이다. 이 기록은 SOURCE/LOCAL 증거이며 최종 commit의 원격 CI·ARM64·SD·DEVICE·FIELD 수락을 뜻하지 않는다.

## 정리 범위

- `src/`에 남은 추적 guide 10개를 삭제했다. `src`, `modules`, `apps`의 제품 소스가 남지 않았다. 공유 main과 다른 worktree의 파일은 고치지 않았다.
- manifest의 colcon root는 learning, operations, middleware, contracts, integrations, shared 여섯 개다. `legacy`와 잔여 경로 검사는 한 release 유예로 유지한다. 안전 21개 module·40개 anchor와 deferred 경계는 보존한다.
- root AGENTS의 이전 기간 경로 고정 규칙을 정리했고 push 규칙은 4항을 유지한다. umbrella guide의 실제 control/Fleet 경로만 맞췄다.
- literal guard는 manifest의 운영 소유 root를 읽는다. 실제 검증 파일 888개, literal hit와 기존 backlog가 이전과 동일하며 learning/tools로 범위를 넓히지 않았다. 누락 root·잘못된 경로·빈 검사 범위는 실패한다.
- 사용자 승인에 따라 Accepted인 D-443의 본문 두 문장을 수용 완료 시제로 맞췄다. D-442·D-443의 계약과 상태는 보존한다.

## 원격 CI 진단과 수정

기준 source를 origin/main에 반영한 enforced pre-push는 fast 462 passed/2 skipped, main 12,573 passed/526 skipped, perception 2,836 passed/112 skipped였다. 그러나 [GitHub CI 37174760531](https://github.com/livsbittt/rosy-os/actions/runs/37174760531)는 실패했다. Android와 unsigned site 후보 성공은 전체 CI 성공을 대신하지 않는다.

root shard의 두 실패는 빌드가 만든 Gazebo `COLCON_IGNORE` 잔존으로 source inventory가 누락된 것이었다. colcon `--packages-skip gz_sim`으로 빌드 제외를 표현해 source를 숨기지 않는다. 관련 회귀는 수정 전 1 failed/5 passed, 수정 후 source inventory 포함 9 passed였다.

인식 shard의 다섯 실패는 실제 Ubuntu/OpenCV 4.6에서 같은 node로 재현했다(5 failed/38 passed). 태그 texture builder와 두 시험은 4.6의 drawMarker/detectMarkers와 새 API를 모두 지원한다. 도킹 pose5의 거리 오차 5.363 mm는 4.6의 5 px 코너 보정 반경이 작은 태그 내부 무늬까지 포함하는 차이였다. 7개 접근 pose에서 창 반경 1~5를 두 API 세대로 비교했다. 2 px를 명시하면 양쪽 최대 x 오차 4.113 mm, y 0.237 mm, yaw 0.486°이며 최신 OpenCV 기본 결과와 같았다. fixture, sampling, 5 mm/1.5° 한계는 그대로다. 코너 보정은 실제 sensing 동작 변경이며 모든 스케일·노이즈에서의 동등성이나 실기 정확도를 주장하지 않는다.

최종 관련 실행은 Windows/OpenCV 5.0에서 52 passed, Ubuntu/OpenCV 4.6에서 43 passed였다. [wave5 정리 독립 리뷰](wave5-cleanup-independent-review-2026-10-04.md)의 초기 정리 리뷰는 SOURCE/LOCAL APPROVE이다. 추가 CI 수정도 별도 독립 SOURCE/LOCAL APPROVE를 받았다. 독립 실제 API 실행은 OpenCV 5.0에서 49 passed, 4.6에서 43 passed였다. 최종 구조·harness·literal 관련 실행은 219 passed/1 skipped, NEW 0이었다. 14개 warning은 기존 freshness 12개와 AST의 기존 invalid escape SyntaxWarning 2개다. 전체 legacy perception 결과는 후속으로 기록한다.

## 증거와 남은 경계

비공개 임시 원본은 X:/DevTemp/rosy-d427/resume에 보관한다: wave5-applied-scope.json, wave5-applied-colcon.json, ci-legacy-red.txt, ci-legacy-green.txt, ci-current-green.txt, dock-corner-window-legacy.txt, dock-corner-window-current.txt. 실제 WSL colcon discovery는 직전 서명 033의 workspace package 27개와 동일했다(배포 vendor sllidar_ros2는 별도).

최종 SHA의 enforced push·전체 GitHub CI·native ARM64와 SD image·033 대비 artifact 비교·서명 릴리스·실기 readback은 후속이다. 사이트 PC model-watch 대상과 다른 세션의 로봇 사용 상태는 확인이 필요하다. 기존 key/enrollment를 보존하며 동작, E-Stop reset, flash를 수행하지 않았다. S7 bad_cycle/uint32 firmware는 다음 개정 항목이다.


## 원격 동시 수정 통합

후보 e289942680b4 이후 origin/main에 먼저 반영된 93f66072c335는 같은 Gazebo source inventory 오류를 수정했다. 최종 rebase에서는 원격 CI 단계와 Bash 행동 시험을 그대로 보존했다. 빌드 중 임시 COLCON_IGNORE를 쓰고 EXIT 때 자신이 생성한 파일만 제거하며 기존 파일은 유지하는 방식이다. 위 --packages-skip 설명은 원래 후보의 로컬 검증 이력이다. 최종 CI 동작은 peer 방식이며 source inventory를 빌드 뒤에도 보존한다. 원격 docs/logs 원문 prefix와 두 세션의 기록을 함께 유지했다. 충돌 상태에서 시작된 push9는 lint 오류로 exit 1이며 수락 증거가 아니다.
