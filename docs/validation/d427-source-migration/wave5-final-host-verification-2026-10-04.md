# D-427 wave5 최종 호스트 검증과 잔여 시험 수정 — 2026-10-04

이 기록은 SOURCE/LOCAL 검증이다. GitHub 전체 CI·ARM64·SD image·release·DEVICE·FIELD 완료를 뜻하지 않는다.

## 확인한 실행

- 후보 1792877e72da의 enforced push11: lint 오류 0, 경고 13, 안전 커밋 2개 확인, fast 462 passed/2 skipped. 이어진 mapped 시험은 2 failed/3,664 passed/151 skipped(860.60 s)여서 push는 exit 1로 거부됐다.
- 실제 Ubuntu/OpenCV 4.6 전체 middleware/perception/test 실행: 2,588 passed/107 skipped(2,755.26 s), exit 0, NEW 0. CI의 ros:none과 같은 호출이다. 수정된 perception 파일은 시험 시작 전 적용됐고 commit/rebase 중 bytes를 보존했다. 독립 리뷰가 원본 로그 hash와 최종 결과를 확인했다. 합성 주행·도킹 시험이며 실기 수락이 아니다.
- 같은 1792877e72da Git archive를 X:의 별도 source에 풀어 WSL Ubuntu Jazzy에서 실제 colcon discovery/build를 실행했다. 033 workspace package 27개와 동일했고(vendor sllidar_ros2 별도), CI처럼 gz_sim을 빌드에서 제외한 26개 package가 14분 51초에 완료됐다(exit 0). 15개 package stderr의 기존 setuptools pytest-repeat egg 경고는 로그에 보존했다. HOST symlink install이며 ARM64·이미지·wheel boot smoke 증거가 아니다.

## 두 실패의 수정

흡수 패키지 소유권 시험은 삭제된 src/AGENTS.md 대신 정본 platform_parts.yaml에서 실제 middleware/perception의 유일한 소유자, middleware part, control import_prefix를 확인한다.

Git diff 영향 시험은 제거된 src/node.py에 가짜 변경을 만들고 payload 판정을 기대했다. 현행 middleware/perception/control/node.py fixture로 변경했다. 알 수 없는 src/node.py와 현행 native 변경을 함께 주면 REVIEW가 우선하는 회귀를 추가했다. 실제 artifact_impact.py의 안전한 REVIEW 판정과 production policy는 그대로다. classifier를 완화하거나 src를 colcon root에 재추가하지 않았다.

관련 시험은 소유 실행 14 passed(2.54 s), 독립 실행 14 passed(2.02 s), 독립 SOURCE/LOCAL APPROVE다. 두 root 시험과 아래 증거만 바꿔 compiled package·runtime·manifest·wheel 입력은 이전 WSL build/전체 perception 실행과 같다. [독립 리뷰](wave5-push11-corrections-review-2026-10-04.md).

원본·해시·source provenance는 X:/DevTemp/rosy-d427/resume의 push-11.txt, ci-legacy-full.txt, wave5-full-legacy-perception-result.json, wave5-wsl-build.txt, wave5-wsl-build-result.json에 보관한다. 새 candidate의 enforced push와 원격 CI는 후속이며 이전 거부 결과를 통과로 바꾸지 않는다. firmware S7은 다음 개정 항목이고 flash·motion·E-Stop reset을 수행하지 않았다.
