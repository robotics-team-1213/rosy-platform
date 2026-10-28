# OMX SIM 명목 그리퍼 하강 형상과 배치 수정

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. source `eacdc5af1a`.
[실제 이동 trace](../omx-native-motion-trace-2026-10-17/result.md)에서 두 번째 이송 중
이전 물체가 움직였다. 기존 15 mm 간격을 고정 finger mesh·URDF 변환으로 계산하면
닫힌 그리퍼의 일부가 이웃 40×30×30 mm 물체 내부에 들어가는 반례도 확인했다.
실제 접촉한 link의 식별이나 전체 arm 충돌 검증으로 해석하지 않는다.

## 수정한 canonical SIM fixture

recipe/cell과 일반·SIM AID 두 Gazebo world를 함께 바꿨다. 하드웨어 profile은 바꾸지 않았다.

| 항목 | 새 값 (m) |
|---|---|
| recipe gap | 0.030 |
| 각 pallet 크기 | 0.115 × 0.095 × 0.010 |
| A frame origin | (0.115, -0.005, 0.010) |
| B frame origin | (0.105, -0.125, 0.010) |
| A world plate centre | (0.1725, 0.0425, 0.005) |
| B world plate centre | (0.1625, -0.0775, 0.005) |

원래 16 box + 2 slip sheet 정의와 checkpoint를 유지한다. 기존 profile에서 sheet
transfer가 거절되는 범위도 유지한다. native G2는 기존과 같이 sheet를 제외한 명시적
box-only16 파생 scenario이며, sheet 작업이나 수동 checkpoint를 검증했다고 표시하지 않는다.

새 배치의 box-only16은 canonical compiler와 analytic planner/validator로 **64개 phase**를
계획했다. 정적 artifact의 최대 nominal duration은 approach 11.460초, grasp 2.549초,
transfer 27.952초, release 17.379초다. 기존 phase 시간 상한은 늘리지 않았다.
한 후보는 endpoint IK가 가능해도 transfer가 43.68초여서 기존 40초 한계로 거절됐다.
최종 후보는 B를 base 쪽으로 10 mm 옮긴 것으로, IK endpoint 검사만 통과한 후보가 아니다.

## 새 검사의 정확한 범위

G2 preflight가 고정 STL과 URDF/xacro hash, TCP/jaw profile을 대조하고 다음만 검사한다.

- 고정 box 형상, 16개 placement, 검토된 yaw twin과 명목 수직 하강.
- 두 층·두 팔레트의 앞서 놓인 물체와 이후 placement 사이 120개 ordered pair.
- finger convex projection을 높이 slab으로 자른 보수적 AABB. 각도 표본 사이의 최대
  변위를 포함하고 2 mm 여유를 추가한다. 단순히 mesh vertex가 안에 없다는 검사가 아니다.

검사한 jaw 구간은 약 0.380426–0.515745 rad다. 실제 stall 측정값을 대신하지 않는다.
새 fixture의 최소 남은 간격은 inflation을 포함한 경계 밖 **4.879 mm**다.
보고서 scope는 `NOMINAL_DESCENT_FINGER_ENVELOPE_ONLY`이며, full-open retreat,
nonvertical interpolation, whole arm, 실제 contact와 hardware는 검증 범위 밖이다.
이 값을 전체 경로의 collision-free 판정으로 사용하지 않는다.

SDK 검사는 실제 ament description의 STL·generated URDF·두 xacro 파일이 고정 형상과
다르면 시작 전에 UNSUPPORTED로 거절한다. source asset만 쓴 host 시험 결과는
TRACKED_ASSETS_ONLY, 실제 SDK가 일치한 결과는 RUNTIME_SDK_MATCHED로 구분한다.
일반 장치 명령이나 새로운 ROS writer를 추가하지 않았으며 기존 goal predicate,
이전 배치 확인, freshness·timeout·HOLD·자원 상한을 유지했다.

## 검증과 증거 한계

원격 RED는 빠진 helper/preflight에 대한 예상 실패 5개였다. 최종 원격 검증은
**315 passed, skip 0, NEW/known/flaky 0**이다. 기존 배치 간섭 거절, mesh/변환/yaw/box
변경 거절, 두 world 정렬, canonical과 box-only 계획, G2/owner/intake/topic client,
문서·harness 검사를 포함했다. 독립 코드 리뷰 material finding은 0개다.

외부 scratch의 `native-layout-clearance-green/run-1.txt`에 로그를 보존했다.

```text
test_log_sha256 = 442a72e49daa619eaaf2100e01f8ddd8343ab82fba0616cad6bbe6266049a521
candidate_analysis_sha256 = 3e8743295c925373b6cccd6e20b365c0dc8bfcaef798eb1cd0b8c9da6b6cb97d
old_geometry_counterexample_sha256 = e4db24bc85feb983806e04280fc77d4912bd07ef4592223db5da6254c2d05c34
```

실제 16-placement 완료는 별도 native 실행 결과로 확인해야 한다. 전체 G2 fault matrix·
실물 수용·모방학습 수집 완료의 증거가 아니며 적격 실제 episode는 0개다.
