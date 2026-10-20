# 보류 워크트리 19개 보관 정리 대상

상태: 사용자가 “브랜치·복구본을 남기고 폴더만 제거”를 선택한 뒤, 명시된19개 작업 폴더를 하나씩 제거했다. 전부 경로 부재·원본 브랜치/SHA 불변·복원 ref 일치·bundle 유효성을 최종 확인했다. 원본 브랜치·커밋은 삭제하지 않았다.

## 실행한 정리

- 아래 19개는 네이티브 git status로 미커밋·일반 미추적 변경이 없고 잠금·동일 브랜치의 착지 큐가 없는 것을 확인했다. 미머지 변경의 원본 브랜치와 커밋을 그대로 유지한다.
- 각 대상의 SHA·브랜치·청결·잠금·진행 중 작업과 해석된 절대 경로 경계를 다시 확인하고, 해당 작업 폴더만 `git worktree remove <정확한 경로>`로 하나씩 제거했다. `--force`·브랜치 삭제·원본 이력 재작성·미완성 변경의 main 병합은 하지 않았다. 대상19개 모두 상태가 같아 제거와 검증에 성공했다.
- 현재 진행 중인 fleet-prune·stuck-jpeg-api·host-uv와 다른 동료 작업, dirty·locked·stale-history는 제외했다.
- 이 방식은 main에 들어간 워크트리만 다루는 기본 자동 prune과 범위가 다르다. 사용자가 브랜치 보존 후 작업 폴더 제거를 명시적으로 선택한 범위에서 실행했다.

## 복구 검증

- 보관용 복구 bundle: `D:/Dev/Robot/worktree-backups/2026-10-19/held-branches-183823.bundle`. 임시 폴더의 원래 bundle도 남겼으며, 보관용 bundle 역시19개 ref/SHA 일치·git bundle verify·실제 unbundle·전체 pack checksum 검증을 통과했다.
- 현재 main 객체를 전제로 하는 증분 bundle이며 원본 저장소 전체의 재해복구 사본은 아니다. 이 작업은 원본 저장소와 아래 브랜치를 그대로 유지한다.
- `git bundle verify` 통과, advertised refs19개와 아래 SHA 전부 일치.
- 별도의 bare 검증 저장소에 bundle refs19개를 실제 fetch해 모두 정확한 SHA로 복원했다. 객체 연결 검사와 전체 도달 가능 객체 조회 결과 누락0개.
- 원본 object store의 오래된 commit-graph 캐시에 무관한 누락 항목이 있어 기본 fsck는 오류를 보고했다. 실제 복원 데이터는 `-c core.commitGraph=false`로 캐시 없이 검사해 fsck exit0·도달 가능 객체 누락0을 확인했다. 원본 캐시는 수정하지 않았다.
- 검사 기록 정정: 작업 폴더 제거 전 사용한 worktrees.scan은 간이 정보만 반환하며 비캐시 ignored 내용은 judge(full=True)로 채워야 한다. 해당 사전 검사에서 이를 호출하지 않아 ignored 자료를 실제 검사했다고 주장할 수 없다. 네이티브 clean 검사와 bundle은 추적된 커밋 보존을 확인하지만 ignored 파일은 bundle에 들어 있지 않다. 원본 커밋19개는 정확히 검증됐으나, 제거된 폴더의 ignored 자료 보존까지 보장하지 않는다.
- 복구할 때는 보존한 브랜치를 `python tools/worktrees.py new <짧은이름> fix/<새주제> --from <보존브랜치>`의 출발점으로 사용할 수 있다. 브랜치 복구가 필요한 경우 bundle 안의 원본 ref를 먼저 확인해 별도 이름으로 가져온다.

## 대상 목록

모든 경로는 `D:/Dev/Robot/Rosy/rosy-platform/.worktrees/<이름>` 아래다.

| 이름 | 보존할 브랜치 | 보존 SHA |
|---|---|---|
| cal-pr | feat/measured-camera-calibration-pr | commit 2a401b5ed0b6079cc466d21f39c37c75992f1f95 |
| wt-rules | refactor/worktree-rules | commit 7923905dea52f2041bdf014616db0b3cc3092f7d |
| pre-grasp | feat/omx-pre-grasp-source-check | commit 9806ffc49dfaa2bedd30b4ef858aa4bf2c969a38 |
| camera-evidence | feat/device-trial-camera-evidence | commit dc18ae0e8e1d42d646c713e7782ba7969ba4c456 |
| wt-map-lap-9c7d70 | fix/gazebo-map-lap | commit 83b83a782a1dd60fdef4d26eac828dada87baafe |
| device-trial | feat/device-trial-profile-identity | commit 9a6cebce3c13085cf3099e5d40ea24dc15be2a6e |
| trip-prod-open | feat/trip-jobs-production-open | commit 9ad766d3fb04b8384c1dc05296038dc613638ecd |
| omx-native-pilot | feat/omx-native-pilot-sim | commit d83f8f383751dd6a26ef49cd732df8e39017daaa |
| sim-closed-loop | feat/omx-sim-act-closed-loop | commit b44ed031adda685835dc4efe318084c91662699c |
| sim-il-int | feat/omx-sim-il-loop | commit a03e69d1fb2aa51f76d5177919b0568af8bcc4fd |
| sim-il-run | feat/omx-sim-il-run | commit f83db056894a196336159de2f76247513c943266 |
| policy-gov | feat/omx-policy-governance | commit d03c2802c8eb96cc4b4d29a032cfd8547d6726f4 |
| camera-calibration | docs/camera-calibration-lifecycle | commit 899aa28ad1f3a4d80900aebe48bc3142986dbf51 |
| fleet-net-load | fix/fleet-network-load | commit 5f90ae64e16926e087840bd6c341fce3d902bedb |
| webrtc-plan | feat/webrtc-camera-migration | commit 1b30615099590b68417d83d63cfd1ffa65033842 |
| d769-learned-follow | feat/d769-learned-follow | commit 9a9d05d67e754d8e5feadb66a870785d35a9130e |
| pinky-lap-goal | feat/pinky-lap-runtime | commit 59bb7c8f23bc771abb76667f8d24628596b54127 |
| size-ratchet | refactor/size-ratchet-d766 | commit b8fdf1725c23ed682a3518ab99042fef3e6d82a7 |
| perception-agents-pr | docs/perception-claude-md-into-agents-pr | commit 2298f5bf8cc46a07aab7f7416451e6619325bdcb |

보류 사유와 이전 시험 기록은 worktree-cleanup-plan-2026-10-18.md 및 worktree-cleanup-followup-2026-10-19.md에 있다. 이 목록은 소스·실물 수용이 완료됐다는 뜻이 아니다.

