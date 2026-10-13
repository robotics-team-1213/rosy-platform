## D-752 Fleet은 World MapPose를 직접 소비한다

**Status:** Accepted
**Date:** 2026-10-13

## Decision

D-738 S10: 모든 현행 Fleet·sim·시험 MapPose 소비자는 rosy.world.state.projections.map_pose를 직접 import한다. D-630의 fleet.localization.map_pose identity alias는 현재 소비자가 사라진 뒤 제거한다. 설치된 rosy-world==0.1.1 의존성은 이미 선언되어 있으며 구현·type·monkeypatch identity는 동일한 World 모듈 하나다.

World는 받은 sightings/odom의 현재 상태 투영을 소유한다. Fleet service/transaction/goal/claim/admission은 그대로 유지하며 미래 예측이나 완료 판단을 World로 옮기지 않는다. historical ADR·로그·검증 스냅샷은 동결한다. 옛 내부 alias를 사용하는 외부 미등록 스크립트는 canonical import로 갱신해야 한다.

| Previous ADR | Relationship |
|---|---|
| D-630 | World 구현과 기존 identity alias의 최종 전환 |
| D-738 | S10 모든 현행 소비자 전환 후 alias 제거 |
| D-430 | 권한 경계·독립 Safety 리뷰 유지 |

## Verification

현행 import/patch 소비자와 canonical exports·source/wheel closure·독립 리뷰·lint를 확인한 뒤 사용자 merge-only 범위로 ff-only 착지한다. 원격 pytest·CI·image·장치 검증은 NOT RUN이다.
