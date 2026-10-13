## D-751 호스트 도구와 로봇 측정을 구분한다

**Status:** Accepted
**Date:** 2026-10-13

## Decision

D-738 S9: perception/tools/gz는 tools/sim/gazebo, calibration migration은 tools/calibration, 정적 ROS inventory는 tools/validation으로 옮긴다. 기존 device/hotpath_measure·ir_line_calibrate는 로봇 프로세스/센서 측정 소비가 있어 기존 device holder에 남긴다. 새 runtime package나 facade 복사본은 만들지 않는다.

도구 import·명령·시험·source root를 함께 갱신한다. Gazebo CWD와 지도·보정 기본 입력은 계속 middleware/perception을 가리키며 원본 보정 파일과 지도 자산은 이동/변경하지 않는다. 새 destination이 있으면 이동을 거절한다. 기존 generator의 삭제된 tools.explore_sim 참조는 기존 미완성 도구로 기록하며 되살리지 않는다.

| Previous ADR | Relationship |
|---|---|
| D-738 | S9 호스트 도구와 device 개별 판정 |
| D-430 | sim command 경계 보존 및 독립 리뷰 |
| D-584 | 노트북 pytest/Gazebo 실행 금지 유지 |

## Verification

source root/map/script readback, static import/AST/byte checks, 독립 리뷰와 lint 후 local ff-only 착지한다. 사용자 merge-only 범위이며 원격 pytest·Gazebo·device 측정은 NOT RUN이다.
