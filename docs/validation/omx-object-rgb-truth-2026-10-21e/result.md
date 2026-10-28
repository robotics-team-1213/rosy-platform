# OMX 실제 RGB 학습 입력 25개 검증

MODEL-PC의 실제 작업 `fixed-object-5a2d82ce6eb05697`에서 native Gazebo 시연
25개를 독립 물체 정답으로 판정하고, LeRobot export 영상 66,080프레임 전체를
다시 읽어 검증했다. 학습 20개와 검증 5개의 Episode ID는 중복 없이 고정했다.
이 보고서는 학습 입력의 증거다. 아래 수치는 teacher 시연의 결과이며
학습 정책의 독립 과제 성공률을 의미하지 않는다.

| 실제 측정 | 결과 |
|---|---:|
| 채택·독립 정답 검증 통과 | 25/25개 |
| LeRobot 전체 영상 readback | 66,080/66,080프레임 |
| 학습 / 검증 / ID 중복 | 20 / 5 / 0개 |
| XY 배치 오차 | 0.05805–0.60499mm |
| Z 배치 오차 | 최대 0.000091mm |
| 물체 상승 높이 | 101.799–102.057mm |
| 놓은 후 안정 시간 | 2.204–2.250 SIM초 |

채택 수집은 batch 7·9·10·11·12·14·15·16 각 3개와 batch 17의 1개다.
batch 8은 3회 모두 물체 과제에 성공했지만 의존 파일 drift로 전체 제외했다.
batch 13은 3회 중 2회 성공했고, 세 번째의 `joint_state_stale` HOLD로
전체 3회를 제외했다. 따라서 이 채택 집합과 두 제외 묶음의 시작은 31회,
물체 과제 성공은 30회, 학습 입력 채택은 25회다. 이전 탐색·불완전 수집은
앞선 보고서와 `prior_collection_records`에 별도로 보존했다. 실패 회차를 지우거나
제외된 성공 5개를 학습 입력·학습 정책 성공률에 합산하지 않았다.

SIM DetachableJoint 부착 보조와 폭에 맞춘 위치 기반 gripper 증거를 사용했다.
실물 힘 센서·무보조 파지·무작위 장면 일반화는 검증하지 않았다. 독립 정답은
실제 물체 좌표·SIM 시각·원 owner/gripper 증거에 결속했다. 학습은 이 검증 이후
시작하며, checkpoint 재로딩과 새 정책 물체 과제 20회는 별도 증거가 필요하다.

- 실제 수집·MODEL 실행 commit: `45718a83d7432a6cc1ea01ca752b4b9be606d684`
- 실제 실행 범위: MODEL-PC native, 8 CPU/6GiB. 이 입력 보고서 시점에는 ACT 가중치 학습 진행 중이며 완료로 판정하지 않았다.
- [실제 학습 요청](C:/DevTemp/pipeline-completion-20261021/omx-object-training-5a2d82ce6eb05697/request.json), 전송 bytes 408,091, SHA256 `56a0b704d30369b31f7ccd74809252a7e074b7cfd85239d12b1ee3ee9a00769f`
- [25개 정답·프레임 검증 원문](C:/DevTemp/pipeline-completion-20261021/omx-object-training-5a2d82ce6eb05697/model-input-proof/curation.json), bytes 217,493, SHA256 `07d21b52dda59815da685f6a844771d88d074a971f946abf2adf5a542e4ecc8a`
- [실제 20/5 분리 원문](C:/DevTemp/pipeline-completion-20261021/omx-object-training-5a2d82ce6eb05697/model-input-proof/split.json), bytes 1,326, SHA256 `df60cc0c8853f47986c0bdda213845f83c438ea785e9c3e6bd8699e78ec0d2d0`
- [원문 회수 receipt](C:/DevTemp/pipeline-completion-20261021/omx-object-training-5a2d82ce6eb05697/model-input-proof/receipt.json): 원격 bytes를 그대로 복사하고 SHA256·25개 고유 ID·66,080프레임·20/5 분리 일치를 재확인했다.
- [수집·제외 이력](C:/DevTemp/pipeline-completion-20261021/omx-object-collection-progress.json), [batch 13 원본 HOLD 이력](C:/DevTemp/pipeline-completion-20261021/omx-object-collection-batch13-history.json), [batch 13 원인·정리 확인](C:/DevTemp/pipeline-completion-20261021/omx-demonstrations-batch-13/failure-reconciliation.json)

이 원문은 원격 study 디렉터리에도 보존돼 있다. 검증을 위해 source frame·정답·
타임스탬프·실패 상태를 소급 수정하지 않았다. 학습 설정은 10,000 step,
seed 42750, ACT `n_action_steps=1`이며 실제 완료·재로딩 결과는 이후 보고서로 구분한다.
