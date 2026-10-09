# 짧은 옆 경계를 일괄 제거하면 굽이 목표도 사라진다

**판정: 후보 길이 문턱 변경 보류, 주행 HOLD.** 2026-10-09 KST, [페인트 출처 비교](../lane-sim-paint-source-2026-10-09/result.md)의 `south_centre_lost` 15–20번을 다시 점검했다. 현재 threshold 페인트가 고른 68 mm 옆 경계로 낸 목표는 Gazebo 참값 차로 중심선에서 각각 **4.5, 6.1, 6.2, 6.2, 6.2, 6.2 mm**였다. 즉 지도 투영 페인트가 멈췄다는 이유만으로 threshold의 여섯 진행 목표를 오판으로 부를 수 없다.

## 반례 실험

[재현 코드](evidence/sweep.py)는 제품의 `extract_lines`가 **이미 찾은** 선 중 길이가 문턱 미만인 선만 해당 프로세스에서 걸렀다. 원래 RANSAC/라인 추출의 최소 길이를 바꾼 시험은 아니며 제품 파일·로봇 설정은 수정하지 않았다. B8 Gazebo 89프레임은 `bend_expected=True`로, 기존 실물 JPEG 434장은 `bend_expected=False/True` 양쪽으로 개방루프 재생했다. 각각 같은 프레임 순서·keeper 초기화·지면값을 썼다. SIM fixture SHA-256은 `35bc08e1a859a8d8033c0d31cddb5717cf497665d28309ead7724d222e6504bb`. 실물 434장의 `상대경로 UTF-8 + 각 파일 SHA-256 바이트` 정렬 결합 SHA-256은 `c270ca3de009e8654a3c3bad00f2bf03f5818ba6d482403263776d1e99580699`다. 실물 파일은 gitignored 로컬 입력이며 공개 저장소에 올리지 않았다.

| 후처리 최소 길이 | SIM `south_centre_lost` | SIM `bend_flipping` | 실물 434장, `bend_expected=False` | 실물 434장, `bend_expected=True` |
|---:|---|---|---|---|
| 60 mm (현행 상당) | `bend_ahead` 8, STOP 3 | `bend_left` 3, `right_only` 18 | 기준 | 기준 |
| 70 mm | `bend_ahead` 2, STOP 9 | 동일 | 진행→STOP 0, 출력 변경 23 | **진행→STOP 6**, 출력 변경 19 |
| 80 mm | STOP 11 | 동일 | 진행→STOP 1, 출력 변경 39 | 진행→STOP 15, 출력 변경 30 |
| 100 mm | STOP 11 | `bend_left` 3, `left_only` 4, `right_only` 8, STOP 6 | 진행→STOP 7, 출력 변경 69 | 진행→STOP 22, 출력 변경 64 |

70 mm에서 SIM 15–20번 6장은 전부 진행→STOP으로 바뀌었다. 실물 `bend_expected=True`에서도 `20260930T133221Z`의 231·235·237·238·240·242번 6장이 추가로 정지했다. 모든 문턱의 이 재생에서 STOP→진행은 0건이었다. 이 숫자는 **같은 녹화 자세에 대한 출력 차이**이며, 폐루프 주행 성공률이나 사람 승인 정답의 false positive/negative가 아니다. SIM에서 목표의 참값 중심 오차가 작고, 더 높은 100 mm 문턱은 굽이의 다른 정상 후보까지 잃는다. 따라서 68 mm 한 사례만 보고 전역 최소 길이를 올리는 수정은 채택하지 않는다.

다음 검증은 짧은 선의 **물리 경계 ID·측정 가능한 가시 길이·지면 보정**을 사람 검수 원본과 묶고, 같은 후보를 벽/분기 음성 사례·굽이 양성 사례에 나란히 적용하는 것이다. 그 뒤 STOP 증가뿐 아니라 목표의 차체 여유, 재획득 지연, 폐루프 통과율을 측정한다. 기존 문턱과 불확실할 때 STOP, CORE 단일 최종 `/cmd_vel`은 유지한다.
