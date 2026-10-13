# 남은 폴더 정리

**결과:** S3~S10은 각 단계 별도 commit 뒤 local main ff-only 착지. push 없음. 설치 이름과 실행 권한을 유지하며 source holder·현재 호출자·Docker/서명/manifest/검사·안내를 함께 갱신했다.

| 단계 | local main에 포함된 commit |
|---|---|
| S3 | `8acaebe047493a5c5af7aa3bd3ccefcd52da4766` |
| S4 | `57c99647dff3517c724371d64b909354606f319a` |
| S5 | `575fa2466cc93b9aced696f39dff76d56d41a6de` |
| S6 | `2134e03b64ff06e67fd2db83a64d8b50173d96ca` |
| S7 | `2e96da6dddf5a4b15dbaeaf5f5dee7a447bd1b73` |
| S8 | `5b5eb527c7e647adac9f58187394e80702f78c66` |
| S9 | `cb827166368bccfdefa657bade4c56c82e8e3f19` |
| S10 | `10581c1cea9e610cdda41b5ad43248b5ac573d89` |



기준 main 3cf2aecde. 사용자가 요청한 local merge 범위로 처리하며 push하지 않는다. 원격 시험 PC 주소/VPN 변경으로 pytest 재검증은 NOT RUN이다. 폴더 이동은 실행 권한·설치 identity·CORE 최종 명령을 바꾸지 않는다. 단계별 static 검사와 local Git 착지를 원격/장치 수용과 구분한다.

## S3

35개 조립 파일을 perception/control에서 perception/nodes로 옮겼다. 기존 CONTROL_ROOTS/build_py/source inventory를 재사용한다. control에는 다섯 facade와 source mapping을 유지하고 S2 기능 holder는 다시 옮기지 않는다. 서명 source closure는 이동한 35개 파일을 요구한다. 독립 source/Safety/closure 리뷰 PASS, 단독 sdist → wheel 생성에서 35개 flat 모듈 각각 한 번 설치·bytes 동일 PASS. 실행 코드가 같으며 web_http의 경로 설명 주석만 변경됐다.

파일 목록·이동 직전/직후 hash는 X 세션 2026-10-13--205210--folder-remaining--b51428/evidence/S3-moves.json에 둔다. 원격 pytest·CI·배포·장치 검증은 미실행. 단계의 실제 착지는 Git ancestry와 X readback으로 확인한다.

## S4

로봇 local policy/receipt는 middleware/robot_execution, 현장 PlanBundle/progress는 operations/site_execution. Existing rosy.execution.local and rosy.execution imports/wheels remain unchanged. Source install, CI, Docker, test and current guide paths move together; immutable d427_target retained.

파일 목록·이동 직전/직후 hash는 X 세션 2026-10-13--205210--folder-remaining--b51428/evidence/S4-moves.json에 둔다. 원격 pytest·CI·배포·장치 검증은 미실행. 단계의 실제 착지는 Git ancestry와 X readback으로 확인한다.

## S5

로봇 Dashboard/Pilot/Face와 현장 Console/Cam holder를 robot_ui/site_ui로 구분했다. App/serving/import identity, assets and backend authority remain unchanged; packaging/deploy/source consumers use the new paths.

파일 목록·이동 직전/직후 hash는 X 세션 2026-10-13--205210--folder-remaining--b51428/evidence/S5-moves.json에 둔다. 원격 pytest·CI·배포·장치 검증은 미실행. 단계의 실제 착지는 Git ancestry와 X readback으로 확인한다.

## S6

D-748에 따라 천장 패키지는 operations/overhead, lamp 사실은 operations/signal_observation, 로봇 앞 카메라는 middleware/perception/front_camera로 구분했다. 기존 ROS/import/wire identity와 지도 계보는 유지하고 image/서명/source 소비자를 맞춘다.

파일 목록·이동 직전/직후 hash는 X 세션 2026-10-13--205210--folder-remaining--b51428/evidence/S6-moves.json에 둔다. 원격 pytest·CI·배포·장치 검증은 미실행. 단계의 실제 착지는 Git ancestry와 X readback으로 확인한다.

## S7

D-749: generic 제품 action rules는 action_rules, 공통 안전은 safety_gate, 관측 저장은 preview, Drive 후보 제한은 motion_limits. 기존 core_features.decision/safety/vision 및 control.control/control.safety 설치 identity와 CORE 최종 명령을 유지한다. 실제 구현은 하나이고 옛 package에는 source facade만 둔다.

파일 목록·이동 직전/직후 hash는 X 세션 2026-10-13--205210--folder-remaining--b51428/evidence/S7-moves.json에 둔다. 원격 pytest·CI·배포·장치 검증은 미실행. 단계의 실제 착지는 Git ancestry와 X readback으로 확인한다.

## S8

D-750: 60개 Fleet server 모듈을 peer/cell/auth/console/ledger source holder로 구분했다. 기존 channel과 app 조립, DB/거래/import identity는 유지한다. source와 wheel 모두 fleet.server.*를 사용한다.

파일 목록·이동 직전/직후 hash는 X 세션 2026-10-13--205210--folder-remaining--b51428/evidence/S8-moves.json에 둔다. 원격 pytest·CI·배포·장치 검증은 미실행. 단계의 실제 착지는 Git ancestry와 X readback으로 확인한다.

## S9

D-751: Gazebo rigs→tools/sim/gazebo, calibration migration→tools/calibration, static ROS audit→tools/validation. 로봇 hotpath/IR 측정 2개는 기존 device holder에 남긴다. map/calibration 입력은 바꾸지 않고 package root/CWD를 명시한다.

파일 목록·이동 직전/직후 hash는 X 세션 2026-10-13--205210--folder-remaining--b51428/evidence/S9-moves.json에 둔다. 원격 pytest·CI·배포·장치 검증은 미실행. 단계의 실제 착지는 Git ancestry와 X readback으로 확인한다.

## S10

D-752: 모든 현행 Fleet/sim/test MapPose import를 rosy.world.state.projections.map_pose로 전환하고 Fleet identity alias를 제거했다. 구현은 World 하나, 기존 rosy-world==0.1.1 dependency와 현재상태 의미·Fleet 거래 owner는 유지한다. 외부 미등록 옛 alias 소비는 canonical import로 갱신해야 한다.

파일 목록·이동 직전/직후 hash는 X 세션 2026-10-13--205210--folder-remaining--b51428/evidence/S10-moves.json에 둔다. 원격 pytest·CI·배포·장치 검증은 미실행. 단계의 실제 착지는 Git ancestry와 X readback으로 확인한다.

## 검증 증거

S3: 35 flat modules 단독 sdist→wheel에서 각 설치 이름 한 번, source bytes 동일. S4: 35 이동 파일·source root·Docker 설치 목적지 readback. S5: 501 이동 파일, 운영 JS/CSS/native 자산 동일·console source root 존재. S6: 156 이동 파일·signal test root readback. S7: 43 구현 source bytes 동일; Core/Perception 단독 sdist→wheel identity/unique bytes PASS 및 Core source facade import PASS. S8: 60 source bytes 동일, standalone sdist→wheel 각 fleet.server.* 한 번·source import·중복 basename 거절 PASS. S9: host 51 이동 항목·source/CWD/map 및 script 참조, ROS inventory CLI 349 rows/272 endpoints. S10: World 독립 wheel 구현 한 번·원본 bytes 동일·30 canonical import sites의 export/type identity PASS.

모든 단계 독립 source/Safety/closure 검토 PASS, Python AST/diff check PASS. harness lint S3~S4 0 errors/32 warnings, S5 0/28, S6~S10 0/27. 원격 pytest·known-failure 비교·CI·image/browser/Android·장치·실물 수용은 NOT RUN이다. 새 구조/설치 guard는 작성했으나 pytest 실행 완료를 주장하지 않는다. 기존 map_v2_fleet 및 보정 입력은 그대로다.

## P2 중복 proof 처리

CORE peer_crypto와 Fleet peer/camera_peer_crypto는 byte 동일하고 각각 독립 배포 owner다. package 역방향 의존성이나 새 공유 dependency를 추가하지 않고 복제 이유·동시 갱신 위치를 두 파일에 동일하게 기록했다. test/architecture/test_peer_proof_ownership.py가 byte 동등성을 검사한다. static byte readback PASS, 해당 pytest NOT RUN.

## P3 및 보존 범위

현재 Git 등록 목록은 X 세션 evidence/P3-current-git-worktrees.txt에 최종 readback으로 기록한다. 관리 도구 Worktrees 호출은 완료 exit를 확보하지 못했으므로 기존 관리 snapshot은 최신 소유/활성 증거로 쓰지 않는다. merged 여부는 owner 종료·활성 process·lock·local DB/overlay의 삭제 허가가 아니다. 이 작업은 다른 세션 worktree/branch/WIP를 제거하지 않았다. P3는 제거 안전성이 확인된 명시적 후보가 없어 HOLD다. 기존 15개 HOLD의 8/2/5 처리 판정은 별도 artifact-hold-review-2026-10-13 기록이며 재삭제하지 않았다.

공유 main의 reference/AGENTS.md·reference/src/AGENTS.md 삭제, rosy_default.yaml.lock·list.txt·robot-8kcn-display.txt는 소유 세션 상태로 보존했다. 기존 generator tools.explore_sim 부재는 이전부터 있던 제한이다. 저장소 밖 fleet.localization.map_pose 사용자 스크립트는 canonical World import로 갱신해야 한다.

## 다음 검증

변경된 시험 PC 주소/VPN을 반영한 뒤 committed main의 해당 suite를 remote_pytest.py로 실행하고 known_failures.py와 비교한다. Source·local merge는 원격 시험·배포·장치 수용 증거가 아니다. 사용자 요청대로 이번 작업은 local commit/merge까지만 수행한다.
