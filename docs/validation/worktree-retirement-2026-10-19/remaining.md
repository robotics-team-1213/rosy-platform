# 남은 워크트리 폴더 정리 — 2026-10-19

사용자의 “나머지도 처리해” 요청에 따라 기존의 브랜치·복구본 보존 방식을 이어 적용한다. 아래 9개는 현재 잠금 없음, 일반 미커밋·비캐시 ignored 파일 없음, 새 커밋 없이 6시간 이상 경과, 착지 대기열 미참여를 확인했다. 자동 prune의 72시간 판정과 별개로 이번 수동 보관 대상으로 분리했다. 미머지 이력은 폴더 정리만으로 main에 반영되지 않는다.

상태: 9개 폴더 제거 완료. 원본9개 브랜치 tip 보존, 별도 검증 저장소에서9개 ref 복원·이력 연결 확인, 제거 후 폴더 없음·Git 등록 해제 확인.

| 폴더 | 보존 브랜치 | 원본 SHA |
|---|---|---|
| account-app-landing | feat/account-app-rollout-landing | commit 76818bd9010d87ec7f3747c811edce64461603e6 |
| account-initial-password | fix/account-initial-password-policy | commit 958b8f2f11ee302d6a69e9d64dcdd4e046c37cd0 |
| auth-service-adr | feat/account-service-completion | commit 1ddea9def6b811298474dc39426ce94cf0f5a873 |
| host-recovery-publish | feat/host-recovery-publish | commit 727887c5c0c111702ce1c2efbc6ee036710545ce |
| host-report-access | fix/host-report-access | commit ef7b094bf2e5130aa58e3189562c9025f9964fc7 |
| learn-omx | feat/rosy-learning-omx-s3-s4 | commit 2dd4d009b9816e8194c0c294f3306e3a8c2174dc |
| pilot-native-fixtures | fix/pilot-native-fixtures | commit 43b3e6dceaadf03a2f0e64886d97620153af4b8f |
| publication-a0-r1-red-proof | fix/signed-catalog-restored-0ef4c1bebf | commit 0ef4c1bebfddb64940fb92d73a231d929ef6d72c |
| push-batch | feat/omx-learned-policy-gate | commit 8e3b114f7b5f657007a2f648689bbb8a554dd4a9 |

대상 루트: D:/Dev/Robot/Rosy/rosy-platform/.worktrees/. 각 대상은 위 이름의 직속 디렉터리만 포함한다. 잠긴 대상·dirty 대상·최근 작업·착지 대기열의 작업은 제외한다.

검증된 복구본: D:/Dev/Robot/worktree-backups/2026-10-19/remaining-clean-held-9-complete.bundle(33621485 bytes, SHA256 0948633d6b9d64af4c4b3c2916e690a1628e0e44f2cc0e14069e2e1ec629504d). 정확한9개 ref/SHA, git bundle verify, 전체 PACK checksum, 별도 bare 저장소로9개 fetch 복원, core.commitGraph=false fsck --connectivity-only --no-dangling을 확인했다. 기존 저장소의 6d20063618beadb3c9755b193da3b811d638cfe5 및 공통 객체가 필요한 증분 복구본이다. Git commit에 없는 자료는 bundle에 포함되지 않는다. 이번9개는 제거 직전에 full 상태 검사로 일반 미커밋·비캐시 ignored 파일 없음도 실제 확인했다.

첫 remaining-clean-held-9.bundle은 제외 기준3c9254 때문에 그 조상 host-report-access ref를 광고하지 않아 검증에서 거절했다. 해당 파일은 정식9개 복구본으로 사용하지 않는다. 제외 기준을 위 커밋으로 고쳐9개 ref 모두 포함된 -complete.bundle을 다시 만들고 실제 복원까지 확인한 뒤 제거했다.

폴더 제거는 각 대상의 해결된 절대 경로가 지정 .worktrees 루트의 직속 자식인지, 정확한 HEAD·브랜치, 일반 미커밋 파일 없음, 잠금·진행 중 Git 작업·동일 브랜치 착지 대기열 없음 여부를 재확인한 뒤 native git worktree remove -- <정확한 경로>로 수행했다. --force 및 브랜치 삭제는 사용하지 않았다. 새 커밋·main 병합·푸시·호스트 설치·실물 검증은 수행하지 않았다.

이번 조사 중 app-names는 동료 세션이 잠금을 해제하고 폴더를 정리해 본 세션 제거 수에 포함하지 않았다. 명시적인 증거 보존 잠금, 미커밋 파일, 현재 착지 대기열 및 최근 활동이 있는 대상은 그대로 보호했다. main의 aff1.log도 그대로다.

최종 재조사 당시 남은28개: 잠금9개, 잠금 없는 미커밋 작업9개, 최근 활동·착지 대기열10개. 조사 도중 새 omx-policy-publish가 생성됐다. 자동 정리 가능 대상은0개였다. 잠금은 fleet-ship, omx-bounded-commission, omx-core-runtime, omx-feedback-fix, omx-native-feedback, omx-preserved-init, omx-torque-readback, signal-occupancy, wt-fleet-budget-a8f123. 미커밋 작업은 auto-state, d427-bulk, d427-bulk-check, hardcode-paths, learning-delivery, learning-plan, omx-auto-deploy, omx-native-ready, v13-map-labels다. 최근 활동·착지 대기열은 gripper-tune, land-cache, mjpeg-cap, omx-policy-publish, origin-g1, origin-sync, sim-tools, site-video-mosaic, v2-timing, xwalk-walls다. 동료 작업 때문에 이 수치는 이후 달라질 수 있다.

