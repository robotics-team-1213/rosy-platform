# OMX native 주제 task 연결과 배치 간섭 HOLD

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. source `a160ba66d8`, run nonce `03e5465e316b`.
[관절 freshness 진단 기록](../omx-native-feedback-2026-10-17/result.md)의 후속이다.
승인된 AI 역할 호스트에 고정 source/SDK를 SSH 배포하고 canonical start를 한 번 호출했다.
서비스의 4 CPU / 4 GiB / swap 0 / 7,500초 상한과 private network/devices/tmp,
strict root·read-only home·고정 state 쓰기 경계를 실제 unit에서 확인했다.

## 실제로 연결된 경로

startup home이 READY가 됐다. 기존 등록 문서의 ID와 digest를 지정한 topic client가
typed compile → proposal(PROPOSED) → 현재 dispatch 세대 확인 → admit(admission_accepted=true,
READY)를 통과했고, 같은 mission이 Fleet → UDS → canonical OMX owner로 실행됐다.
고정 SIM recipe를 호출자가 명시한 실행이다. 임의 자연어를 이해하거나 미등록 작업을
자동 계획한 증거로 해석하지 않는다.

첫 두 action의 approach·grasp·transfer·release, 합계 **8개 phase**가 ROS status 4 /
result code 0으로 끝났다. 첫 번째 물체는 독립 관측과 Fleet 목표 판정으로
GOAL_CONFIRMED가 됐다. 두 번째 action 종료 후 이전 배치 재검사에서 실패해
runner 결과는 **HOLD, 목표 확인 1/16**이다. terminal UNKNOWN 진단은 없었다.
이 한 번의 실행으로 이전 freshness 문제가 모두 해결됐다고 판정하지 않는다.

## 중단의 실제 측정값

| 첫 물체의 pose | 첫 목표 확인 시 | 두 번째 action 뒤 |
|---|---:|---:|
| x (m) | 0.20726776 | 0.21169896 |
| y (m) | 0.07244884 | 0.10478687 |
| z (m) | 0.02499995 | 0.02206629 |

첫 물체는 약 **32.64 mm** 이동하고 약 **0.974 rad** 기울었다. 독립 predicate는
xy 0.0325588 m, z 0.00293371 m, yaw 0.299950 rad, tilt 0.974042 rad 오차를 기록하고
네 조건을 모두 거절했다. 초기 목표는 (0.2075, 0.0725, 0.025) m였다.
두 번째 목표는 (0.2075, 0.0275, 0.025) m로, 폭 30 mm 물체 사이 명목 간격은 15 mm다.

이는 이전 물체가 실제로 움직였다는 증거다. 두 endpoint만으로 접촉한 link나 phase를
확정할 수 없다. 기존 planner는 collision scene이 없으며, 현재 release는 이미 제한된
jaw opening과 수직 후퇴를 사용한다. 물체 크기·허용 오차·검증 조건을 바꾸거나 배치를
임의로 넓혀 통과시키지 않았다. 다음 확인은 이미 확인된 물체의 독립 pose 변화와
실제 phase 시각을 결속해 간섭 구간을 찾는 것이다.

## 정리와 증거

cleanup_verified=true, remaining_groups=[], cgroup 부재, MainPID=0 / 빈 ControlGroup,
해당 run의 실제 budget 파일 부재를 확인했다. ACK 이후 같은 run을 재시작하지 않았다.
private 운영 scratch의 `native-auto-deployment-7/fetches/20261017T105018-c725b08ef3cb`에
원본 archive·추출 대조표·receipt를 보존했다.

```text
archive_sha256 = e79e0ee51c751f35eba08dea13149a4e8224501c168fb5990623ca67af2df12a
extraction_map_sha256 = 2184563be643cebe5408f85fdd564f44bee223b7879d6ce479b4b0b79751e08e
```

topic prepare/admission 영수증, placement 초기·최종·이전 배치 관측, ROS phase 결과와
정리 관측을 함께 남겼다. 원격 집중 63개 통과와 별개인 실제 SIM 실행 결과다.
전체 G2 fault matrix, 실제 파지·실물 수용·실제 시연 수집은 확인하지 않았다.
적격 실제 episode는 0개이고 실제 ACT 학습은 시작하지 않았다.
