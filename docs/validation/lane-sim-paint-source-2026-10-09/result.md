# 같은 굽이 영상에서 페인트 출처만 바꾼 반례

**판정: 호스트 개방루프 SIM 진단, 주행 HOLD.** 2026-10-09 KST, 로컬 `main` `77d75005f`의 keeper를 고정한 채 B8의 녹화된 Gazebo 영상 89장을 두 번 재생했다. 첫 번째는 현행 `floor_white_mask`, 두 번째는 260919 STL `PaintMap`을 각 프레임의 Gazebo 참값 자세와 지면 평면으로 영상에 투영한 마스크를 넣었다. [재현 코드](evidence/compare.py)는 둘 다 같은 `LaneKeeper`, 카메라 위치, `bend_expected=True`를 사용한다. 원본 [B8 fixture](../lane-trip-perception-2026-10-07/fixtures/b8_keeper_clips.npz)의 SHA-256은 `35bc08e1a859a8d8033c0d31cddb5717cf497665d28309ead7724d222e6504bb`이다.

이 투영은 **진단용 지도 페인트 후보**다. Gazebo 참값 자세를 써서 위치 오차를 제거했지만 벽 가림·광학 왜곡·실물 보정 오차는 모델링하지 않는다. 영상에서 보이는 픽셀의 사람 정답이나 실제 로봇에 쓸 수 있는 지도 센서가 아니다. BEV IoU는 두 입력 마스크 사이의 겹침이며 어느 쪽의 정답률도 아니다.

| B8 구간 | 프레임 | BEV 마스크 IoU 중앙값 | threshold 전략 | 지도 투영 전략 | 진행 판정 차이 |
|---|---:|---:|---|---|---|
| `south_centre_straight` | 13 | 0.757 | BOTH 13 | BOTH 12, RIGHT_ONLY 1 | 없음 |
| `corner_exit_offset` | 13 | 0.652 | BOTH 13 | BOTH 13 | 없음 |
| `bend_flipping` | 21 | 0.704 | BEND_LEFT 3, RIGHT_ONLY 18 | 동일 | 없음 |
| `bend_fork` | 11 | 0.755 | BEND_LEFT 11 | 동일 | 없음 |
| `south_centre_lost` | 11 | 0.668 | BEND_AHEAD 8, NONE 3 | BEND_AHEAD 2, NONE 9 | **threshold만 진행 15–20번 6장** |
| `premature_corner_left` | 13 | 0.648 | BEND_AHEAD 6, BOTH 4, NONE 3 | BEND_AHEAD 7, BOTH 4, NONE 2 | 지도 투영만 진행 44번 1장 |
| `spoke_transverse` | 7 | 0.755 | LEFT_ONLY 4, NONE 3 | LEFT_ONLY 3, NONE 4 | threshold만 진행 85번 1장 |

`south_centre_lost`의 15번 영상에서 두 입력 모두 약 64°의 같은 굽이 후보를 찾았다. 그러나 threshold는 오른쪽에 길이 68 mm인 짧은 경계도 추출해 `bend_ahead` 목표를 냈고, 지도 투영 입력에는 keeper가 받아들인 옆 경계가 없어 `no_boundary`로 섰다. 17–20번의 참값 자세는 사실상 동일한 정지 위치였다. 차이의 직접 원인은 **페인트 마스크가 그 짧은 옆 경계를 만드는지**이며, 그 경계가 실제로 보이는 안전한 동일 물리 선인지 이 실험만으로 판정할 수 없다. 따라서 6장을 잘못된 주행이라고 세거나 지도 투영을 정답으로 승격하지 않는다.

## 다음 결정

1. [Pi 추론 지연 재현](../learned-paint-cadence-2026-10-09/result.md)은 현행 학습 모델의 사용률 문제를 설명한다. 이 SIM 비교는 **추론이 빨라져도 페인트 출처에 따라 경계 추출과 STOP이 갈린다**는 별도 문제를 드러낸다. 속도 개선만으로 차선 추종 합격을 선언할 수 없다.
2. 같은 89장에서 threshold·학습 마스크·지도 투영의 후보 경계 길이와 대상 차로 ID를 나란히 보고, 짧은 68 mm 옆 경계의 실물 대응을 사람에게 검수받는다. 10/6·10/7 원본에는 같은 물리 경계 ID와 그때 쓴 지면값이 없어 현재는 후보 분석만 한다.
3. 지도/odom은 관측과 충돌할 때 진행을 막는 증거로 검토한다. 불일치만으로 지도 선을 관측된 차선이나 `drivable`로 바꾸지 않는다. 굽이·벽·분기 재생에서 STOP 증가와 false carry를 함께 측정한 뒤 SIM 폐루프 및 실물 감독 수용으로 넘어간다. CORE 단일 `/cmd_vel` 경계는 유지한다.
