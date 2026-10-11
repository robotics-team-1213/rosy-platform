# CORE Drive 우선 책임 분리 실행 계획

기준: `291d03a9f`, 브랜치 `feat/platform-structure-migration`. D-625/D-627과 기존 CORE 계획 P0/P4의 첫 행동 불변 단위다. 사용자의 CORE drive 우선 요청으로 M7의 조립 부분을 앞당긴다.

1. 기존 CORE의 docking mode/release, listener isolation, line-follow envelope/recovery, goal tracker, cmd_vel/port, Safety 시험을 기준 SHA에서 원격 실행하고 known_failures와 비교한다.
2. 기존 line-follow 배선을 `core/drive/line_follow.py`로 옮기고 old import facade를 유지한다. 도킹/군집 생성과 take/release callback만 `core/drive/docking.py`의 함수로 추출한다. callback의 closure와 순서가 동일한지 비교한다. 공통 mode mirror/전체 E-stop 배선은 CoreServices에 남긴다.
3. public service attribute, seed parser 재-export, producer slot, listener 순서, import/설치 identity를 유지한다. 새로운 운용 port/container/registry나 자동 복구 옵션은 만들지 않는다. Safety 파일 추적, package guide와 영향 시험 경로를 갱신한다.
4. 독립 Safety 리뷰 후 후보를 커밋한다. 같은 기준 회귀와 source 구조 검사, 실제 임시 Linux wheel 설치 검사를 원격 실행한다. source와 설치·ROS runtime·ARM64·장치 수용을 분리해서 기록한다.
5. 문서/로그에 수행 단위와 증거를 남기고 generate/lint 한다. 잔여 주행 알고리즘 추출, 곡률·문제 복구 개선, Arm/world 확장은 기존 후속 계획을 유지한다.

완료 기준: Drive 조립의 실제 폴더와 caller가 분리되고 기존 동작 회귀/설치 검증이 통과하며 source-only Safety 승인이 기록된다. 전체 CORE 주행 설계를 구현 완료했다고 선언하지 않는다.

## 실행 결과

기준 `ca7335b07`의 원격 characterization 257 성공을 확보했고, `1691d395c`에서 Drive 조립을 추출했다. `5faad3583`의 전체 CORE와 실제 Python package 설치 시험은 2575 성공·10 skip, 새 실패 0이다. Feature 전체 1675 성공 및 architecture/harness/Safety 272 성공도 확인했다. 도킹 lock/callback·mode 선점·Nav2 취소·E-stop 순서와 line-follow 기하/복구 배선은 독립 source Safety 승인을 받았다.

이 계획의 첫 조립 단위는 완료다. 기존 장치·ROS evidence를 새 후보의 수용으로 확대하지 않았다. [현재 구조](../reference/core-drive-responsibilities.md), [검증과 남은 항목](../validation/d626-holder-migration-2026-10-11/result.md)을 따른다.
