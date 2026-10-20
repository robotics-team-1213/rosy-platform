# OMX 실제 물체 RGB 시연 3회 재검증 — 2026-10-21

고정 초기 상태의 부착 보조 Gazebo 과제에서 새 시연 **3/3회**가 성공했고, 모델 PC에서
독립 물체 판정과 실제 RGB export/readback **7,940/7,940장**을 통과했다.
학습 checkpoint와 독립 학습 정책 20회 평가는 아직 없으므로 전체 목표는 미달성이다.

| episode | RGB 장수 | 들림 mm | XY 오차 mm | 해제 뒤 안정 SIM 초 |
|---|---:|---:|---:|---:|
| b10775c8-ff01-4a20-8214-f4e4f2b1810e | 2,642 | 102.014014 | 0.062742 | 2.206 |
| 644a9dfc-36a1-44b8-ae0a-5cb3b0d823c6 | 2,658 | 101.826080 | 0.244674 | 2.240 |
| c0bbc64d-32c2-4faa-b03e-6466c9c82012 | 2,640 | 102.021524 | 0.066475 | 2.208 |

세 번 모두 Z 오차는 0.000046194mm이며 실제 gripper/부착·분리, 원 명령 수락/종단,
owner 시계, 원 장면·카메라와 종료 정리를 검증했다. 허용 오차·장면·카메라 속도는
바꾸지 않았다. 영상 readback 최대 프레임 평균 오차는 1.802257/255 이하이다.
LeRobot 0.4.4/v3.0, 판정 출처는 sim_ground_truth다. seed는 기록되지 않았고 위치
일반화나 RNG 독립성을 주장하지 않는다.

수집 source는 `45718a83d7432a6cc1ea01ca752b4b9be606d684`, native run은
`45718a83d7432a6cc1ea01ca752b4b9be606d684-64029a80783a`다.
archive 65,956,035 bytes의 SHA256은
`449c6713dacf86b7d412e75b7d03dfa2c073dbd7903719b3447ae793cc7b25af`다.
모델 PC의 작업 전용 input으로 복사한 뒤 archive와 모든 파일 bytes를 대조했다.

검증/export source `4b710f290e`, 승인된 remote_sim의 MODEL-PC 실행은 exit 0이다.
로컬 원본은 `C:/DevTemp/pipeline-completion-20261021/omx-batch7-truth-model/`의
run.txt와 out/result.json 및 각 proof/export 디렉터리에 있다.
run.txt SHA256은 `0405fd47c9b2dc5e36aef5859c208bacbc10ceaf1423c120906c9ec458a48108`,
out/result.json SHA256은 `a706307f877bc2ee5626ccbe31ab680a821654ab52ffb13c30fe920550bb0e13`다.

[앞선 기록](../omx-object-rgb-truth-2026-10-21/result.md)의 7회 뒤 batch6 한 번은
실제 readback 대비 목표가 0.04rad를 넘어 실패했다. 이를 고친 현재 묶음 이전까지
RGB 시연 시도는 8회이며, 현재까지 누적 시도 11회 중 complete 성공 시연은 5회다.
그중 이전 1회와 현재 3회, 총 4회는 엄격한 원본 정답 검증과 실제 영상 재독출을
통과했다. 나머지 이전 성공 1회에는 필요한 원 owner/gripper 증거가 없어 편입하지 않는다.

학습에 사용할 새 고정 cohort는 이 묶음을 시작으로 25회 중 3회 수집된 상태다.
완료 뒤 첫 20회 train/마지막 5회 validation으로 고정한다. 이어 같은 checkpoint를
새 world/episode 20회에서 평가해 18회 이상 성공해야 목표 달성이다.
시연 성공률과 단위시험 통과 수는 학습 정책의 물체 성공률에 합산하지 않는다.
