# 차선 개선 코드 실기 배포 — 2026-10-05

## 결과

두 실제 Pinky에 서명 릴리스 **2026.10.05-040**을 수동 순차 배포했다. 실제 설치·실행 source revision은 `58d246ab3d2842890529893c8ef34e944153639a`다. 소스 커밋 `428a786ec`의 비가시 경계 복구와 앞선 `d396a2576`의 pair/crossing 수정이 함께 포함된다. 이후 다른 세션의 main 변경은 이 릴리스에 포함하지 않았다. 후속 증거 문서 커밋이 payload의 source SHA를 바꾸지는 않는다.

**DEVICE 소프트웨어 설치/정지 관측/장치 재생 PASS, 실제 keeper 제어·R1/R2 현장 주행 HOLD.** 이번 설치 중 주행·E-Stop 해제·hardware commissioning·keeper 모드 활성화는 수행하지 않았다.

## 소스와 배포 경로

- [정확한 source CI 37268067397](https://github.com/livsbittt/rosy-os/actions/runs/37268067397): success.
- [ARM64 payload build 37268633475](https://github.com/livsbittt/rosy-os/actions/runs/37268633475): success, source SHA 일치.
- 로컬 실제 pre-push: 기본 490 passed/2 skipped, 연계 3,443 passed/153 skipped, known_failures NEW0. 소스 main ff 착지를 마쳤다. 정상 push는 동료가 같은 SHA를 먼저 반영하여 ref 경합으로 거절됐지만 원격 main SHA와 해당 CI를 독립 조회해 일치를 확인했다. force-push·검사 우회를 사용하지 않았다.
- 두 장치 각각 공유 ROS Jazzy 314패키지 ABI 일치, 릴리스 342 ROS 패키지/필수 ROSY 패키지 존재 확인. 2,918개 파일 서명 검증, POSIX 실행 mode 보존, signed tar 3,284 members.
- Tarball SHA256: `4fae9d87f0e6312f691e24f7c62fba1e28633e4724178705bbb5c126f73a5122`.
- `rosy-release-push`/`rosy-device-access`/`rosy-dashboard-drive` 절차를 적용했다. pinned SSH, 장치의 공개 CA·정확한 hostname을 검증하는 HTTPS 보정 guard, preview, 실제 claim, 9dfk 선행 설치·확인, 8kcn 후속 설치 순서다. 두 guard 모두 active calibration 없음, 두 push 모두 exit0/CORE readiness PASS다.
- Image-layer는 두 장치 각각 rosy-boot-status.py 한 파일만 교체했다. device backup 000010/000008을 만들고 109파일 unchanged, 추가 live unit restart 없음이다. claim release까지 완료했다.

## 실제 실행 확인

| 장치 | readback UTC | CORE/IO/camera | 실제 CORE와 camera cwd | 카메라 / 10초 | 관측된 정지 cmd | 장치 재생 keeper p95 |
|---|---|---|---|---:|---:|---:|
| rosy-pinky-9dfk | 2026-10-05T05:48:55Z | active/active/active | `/opt/rosy/releases/2026.10.05-040` | 80 | 501 samples, v=w=0 | 14.02 ms |
| rosy-pinky-8kcn | 2026-10-05T05:52:39Z | active/active/active | `/opt/rosy/releases/2026.10.05-040` | 80 | 497 samples, v=w=0 | 18.31 ms |

두 장치의 설치된 lane_keep_lines.py SHA256: `def75b21bf6f5b5533fd09b9a597f3dd52c48b97322254cd3c5184fbc8c80050`. git의 source blob SHA256과 일치한다. symlink만 검사하지 않고 CORE·camera MainPID와 `/proc/<pid>/cwd`를 확인했다. state 파일은 실제 시각에 갱신됐고 IDLE, line-follow OFF, 선속도·각속도 0이다.

## 장치 자체 재생과 보존 사항

두 장치에서 실제 설치된 control 모듈을 import하여 원본148장을 순서대로 처리했다. PC에서 발견한 네 경계87–90이 모두 복구됐고, 두 장치 모두 동일한17비가시 index `[32,33,34,35,36,58,59,60,61,62,63,64,65,115,134,138,141]`를 유지했다. 첫36장 MAE는 둘 다0.0518585684다(PC 기록0.0518125는 frame error 소수 셋째 자리 반올림값 기준). p95는 keeper 순수 update 시간이며 영상 전달·모델 추론·ROS/대시보드 전체 지연이나 실주행 제어 주기를 뜻하지 않는다. 공칭 ground의 증거 전용 재생이며 실제 observer의 ground 허용 정책을 바꾸지 않았다.

실제 ROS parameter readback은 배포 전후 완전히 같다: camera_lane_mode=line, paint_source=threshold, camera_ground_source=PINKY, allow_nominal_ground=false, lane_half_width_m=0.0925, lane_corner_turning=false. model shadow/current/hold 파일의 경로·존재 상태는 같다. 일반 pointer 파일 내용과 모델 artifact hash의 전후 일치는 이 관측으로 검증하지 않았다. 8kcn은 learned status10/shadow9개를 관측했고 signed=true, model_revision=lane-seg-20261003-6e2e5640가 전후 동일하다. 9dfk에서는 같은10초 창에 learned 메시지가 관측되지 않았다. 실제 제어를 새 keeper나 learned source로 전환한 증거는 아니다.

두 live dashboard는 인증 후 robot/safety/commissioning/hardware API가 모두200이다. 공개 CA와 hostname으로 먼저 leaf를 검증한 뒤 그 public key만 browser에 pin하고 approved hostname을 연결했다. 전역 TLS 검증을 끄지 않았다. 스크린샷에서 대기·속도0·line OFF와 실제 카메라 영상을 확인했다. **motor bench commissioning이며 화면 안전회로가 UNVERIFIED로 표시된다. hardware API의 하드웨어 탐침 기록도 약17시간 이전의 것으로 최신 물리 상태 수용 근거가 아니다. 이를 해제하거나 주행 가능 판정으로 덮지 않았다.** 사람의 경계 정답, 곡선/교차로 경로 선택, 실제 keeper 제어·R1/R2 수용은 미검증이다.

임시 administrator 세션은 두 장치 모두 logout204를 확인하고 해당 X 드라이브 token 파일을 삭제했다. 기존 card/named operator credential이나 배포 hold를 변경하지 않았다.

증거 문서·배치·harness·비밀 검사와 keeper 재검사: 162 passed, 1 skipped, 21 기존 warnings, known_failures NEW0 (deployment-doc-checks.txt).

독립 검토자는 source blob/설치 checksum·두 장치 재생·카메라/정지 counter·parameter·로그아웃을 교차 확인해 소프트웨어 배포 증거를 승인했다. pointer 경로를 내용 검증으로 해석하던 표기는 이 검토에 따라 한정했다. FIELD 수용자는 아니다.

## 증거

원본 로그·JSON·화면·tarball은 `X:/DevTemp/keep-visible-20261005/`에 보존한다. 실제 주소·인증 값은 공개 문서에 넣지 않는다.

| 파일 | 공개 SHA256 |
|---|---|
| `push-gate.txt` | SHA256: `9bc2bf56a91eb1e69128b6e98e725a72530d105c338b7f1fd0598469a83458a3` |
| `run-37268633475.json` | SHA256: `ac4992cc3255e99179408452291e8a61f4343c607a3d561e3ec3302a178bd711` |
| `prepare.txt` | SHA256: `20743c0ddc97b9d1ef666ea5b0ee132e309f5a3425cb50bb837924b8ae0ae16b` |
| `verified-proof.json` | SHA256: `a89e4857e5bd050671b7f34572dfdf63b4983dae76f4482307e2b0e33adce1b5` |
| `logout.json` | SHA256: `abfc021a77d82a7c8fa9fba63bbfc3063a5ed351e98c6e1c4e5f9a2e90be3582` |
| `rosy-pinky-9dfk-deploy.txt` | SHA256: `43e41d5b5b385f97c265418d1c7eba93412184bbbf7163753c24a1191ec0fdb2` |
| `after-rosy-pinky-9dfk.json` | SHA256: `8d53bc9f7ed44ab6aa986b6f2482b7018edc172eea3f4c17cbe0e23e89989d36` |
| `after-rosy-pinky-9dfk-camera.json` | SHA256: `e133e41c92cf9b0344f57d855147d2afb50aafdc5bedd7e0ebd6f761e34c6819` |
| `rosy-pinky-9dfk-arm-replay.json` | SHA256: `4c2412bd8aa0172b91aa00d1763ed9f72e0b23a2f43fcfc6cc67d6c1b94bbb8b` |
| `rosy-pinky-9dfk-dashboard.json` | SHA256: `4621a7b406418733ceb18f7055a58e4c2d2d6904d125f0072a5cab32b7f445cf` |
| `rosy-pinky-9dfk-dashboard.png` | SHA256: `e7929bb3c661d493ef004e736906c9d381f5af562f3930cd92de1a26b181426a` |
| `rosy-pinky-8kcn-deploy.txt` | SHA256: `35acc56e1cbc3667affa2bdcb2dcdfc99878cdae76b0da6d7a49bbf094bb8392` |
| `after-rosy-pinky-8kcn.json` | SHA256: `5c15cd3264f59e35f1f813fc163eb88e9e03b1ebbc1d511d3b7592455d24a023` |
| `after-rosy-pinky-8kcn-camera.json` | SHA256: `f622980b241e39dd0fb8d87a931f81d0985398d4a042c399a5a52f407cb4134a` |
| `rosy-pinky-8kcn-arm-replay.json` | SHA256: `f6c30eb18d4216a1c5ac4e4adce7e910d5c2d2e54174439667c3cd6d76873da9` |
| `rosy-pinky-8kcn-dashboard.json` | SHA256: `bbb78f26a58854f0676d3eced2bd3bcab5e49e8d3dc58093308f5fb4811583a6` |
| `rosy-pinky-8kcn-dashboard.png` | SHA256: `acf526e84eb7da02e4c9a6ea41d2aaf5549f4e13dd033248c812e451ad1f1176` |
| deployment-doc-checks.txt | SHA256: `06ea7006acd3e5ec5210b052681dd66c09b9598f8b3b1dd2de61a4223d16b009` |
