# OMX 실제 RGB 시연 추가 검증 — batch 9

고정 cohort의 독립 정답·전체 영상 readback 완료 자료는 6/25개다.
batch 7의 [기존 3개](../omx-object-rgb-truth-2026-10-21b/result.md)에 다음 3개가 추가됐다.
학습 checkpoint·추론 지연·새 학습 정책 물체 과제는 아직 미검증이다.

| 실제 episode | RGB frames | Lift (mm) | XY 오차 (mm) | 안정 시간 (SIM s) |
|---|---:|---:|---:|---:|
| c74e50d5-09f1-4bc4-87e5-ad7c49a26823 | 2638 | 102.057152 | 0.094420 | 2.204 |
| a809a113-efae-42c9-bb46-4b0098798bed | 2642 | 102.010735 | 0.066761 | 2.232 |
| 11fe407d-ade9-47be-be8a-cd2e8b1f669e | 2645 | 102.011637 | 0.066997 | 2.212 |

Z 오차는 모두 `4.619359970231551e-08m`였다. native 실제 물체 시연 3/3,
독립 SIM 정답 3/3, LeRobot 0.4.4 원본 입력·영상 readback 7,925/7,925가 통과했다.
영상 변환의 최대 frame 평균 절대 오차는 `1.7974696159362793/255`다.
기존 규칙 teacher와 명시적인 SIM 부착 보조를 사용했으며, 학습 정책의 성공으로
세지 않는다. 초기 상태는 고정됐고 simulator RNG seed는 기록되지 않았다.

- native source: `45718a83d7432a6cc1ea01ca752b4b9be606d684`
- native run: `45718a83d7432a6cc1ea01ca752b4b9be606d684-3688b20534b8`
- 검증 source: `4b710f290e` — MODEL-PC, native 8 CPU/6GiB, exit 0
- 원본 archive: `65,821,942 bytes`, SHA256 `a6d932efc73b76d829f265f52b98c32e5b1ce902a7bf7da2ce0e3589cf05a59e`
- MODEL 원본 경로: `/home/rosy/rosy-test/omx-object-inputs/job-45718a83d7-3688b20534b8/files`
- [독립 검증 결과](C:/DevTemp/pipeline-completion-20261021/omx-batch9-truth-model/out/result.json), SHA256 `b7f7ecba1c78724009e8a0ea9c6780b7fe608a939fbc52c66a273e8cc00a16f8`
- [원격 실행 로그](C:/DevTemp/pipeline-completion-20261021/omx-batch9-truth-model/run.txt), SHA256 `3e17272fb75123fc00592800234ffb17296e6d78f7f38df25d7d646b694e2945`

batch 8은 물체 시연 3회 성공 뒤 시스템 Python 의존 파일 6개의 drift가 발견됐다.
정책 학습 자료에서는 전부 제외하고 [전후 hash·root helper 종료 상태·원래 결과](C:/DevTemp/pipeline-completion-20261021/omx-demonstrations-batch-8/dependency-drift-reconciliation.json)를 보존했다.
시스템 파일을 되돌리거나 hash 검증을 생략하지 않고 새 native 환경을 고정해 batch 9를
수집했다. 실패·보류된 과거 시도는 별도 원장에서 유지한다.

목표는 실제 RGB 시연 20 train/5 validation, 실제 ACT 학습과 재로딩,
같은 checkpoint의 새 Gazebo 물체 과제 20회 중 최소 18회 성공이다. 현재는 미달성이다.
