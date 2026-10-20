# OMX 실제 물체 시연: batch 10–12 독립 검증

고정된 원본 source `45718a83d7432a6cc1ea01ca752b4b9be606d684`로 native Gazebo에서
수집한 세 batch의 9개 시연을 MODEL-PC에서 독립 검증했다. 실제 물체 좌표·SIM 시각·
gripper 증거를 판정하고 LeRobot 0.4.4로 export한 영상 전체를 다시 읽었다.

| 실제 측정 | 결과 |
|---|---:|
| 물체 과제 성공 | 9/9 |
| 영상 재읽기 검증 | 23,767/23,767 프레임 |
| 최대 영상 평균 절대 오차 | 1.802283/255 |
| 물체 상승 높이 | 101.799–102.023mm |
| XY 배치 오차 | 0.06055–0.60499mm |
| Z 배치 오차 | 최대 0.000067mm |
| 놓은 후 안정 시간 | 2.206–2.250 SIM초 |

batch 7·9의 기존 검증 6개와 합쳐 현재 cohort의 독립 검증 통과는 **15/25개**다.
이는 teacher 시연이며 학습 checkpoint·학습 정책의 독립 20회 결과는 아직 없다.
SIM DetachableJoint 보조와 위치 기반 gripper 증거를 사용했다. 실물 힘 센서나
무보조 파지, 무작위 초기 상태의 일반화 성능을 주장하지 않는다.

- 검증 checkout: `4b710f290e` (실행 로그에 전체 revision 보존)
- 별도 [검증 recipe](C:/DevTemp/pipeline-completion-20261021/validate_new_omx_batches.py), SHA256 `ba8a1acae084f21a8b2f6828a1e5f2a8c47ce3b9daa9de0440caf556bfa897a0`
- [회차별 결과](C:/DevTemp/pipeline-completion-20261021/omx-batches-10-11-12-truth-model/out/result.json), SHA256 `f0e13151b12fe5f2503381dd2f69a1edddec9c7efc90b9c7faa2160293d55770`
- [실행 로그](C:/DevTemp/pipeline-completion-20261021/omx-batches-10-11-12-truth-model/run.txt), SHA256 `00f1c477a4ccaa8b48b8c1d302fb102d4acb3e39142a85c29c9ea326335cc7b8`
- 원본 archive SHA256: batch 10 `2ca1c5abe30f9e7924bdf479dbaf51d2e952cf5bf17993f8abbe5e3c8d3daf9c`, batch 11 `cda28b999c2b3e42416b7eef5fa1f63766091b13e8f367aa2c7b8faff2991040`, batch 12 `995c2a2acca06ee23c290aae6f95123e65c41c45a37dce9446733eda30ba8e0e`

batch 8의 별도 3회는 dependency drift로 계속 제외한다. 실패·제외 기록을 지우거나
이 결과를 learned-policy 성공률에 합산하지 않았다.
