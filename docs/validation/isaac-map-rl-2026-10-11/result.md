# Isaac 실제 맵 CPU RL — 한 대 진단 검증 결과

D-638의 한 대 native CPU 진단에서 기존 CORE·Drive로 학습하고 고정 정책의 독립 시드에서 ordered 경로 완주와 실제 정지를 확인했다. 종료 수리를 포함한 전체 학습 재시험 R8과 네 시작 방향의 실제 headless Isaac 녹화 R9도 통과했다. 전체 ROS-SIM/Isaac Lab/Fleet·신호/실물 수용은 HOLD다.

## 실행한 source와 지도

- 전체 맵 R6: `dc25401e6141a365dfee918ca1ecc97254a1ffa5`, 시작 직전 main `19e1c7eef` 포함, source 7,014파일 전후 SHA-256 일치.
- 종료 수리 R7: commit `e0e5b38d788d7dbbed73900db0b986e236673838`, source 7,014파일 전후 일치. 전체 맵 재학습이 아닌 별도 URDF/world 종료 생명주기 검사다.
- 전체 재시험 R8: commit `57ad87993fa1da4daef360224774dda6e11fb414`, source 7,050파일 전후 일치. main `33729c514` 포함, 종료 수리 뒤 전체 baseline·학습·고정 평가를 다시 실행했다.
- 네 방향 녹화 R9: commit `b6a8d0d2e834d31a5df407ec54a3cf5baeda1837`, source 7,053파일 전후 일치. R8 정책을 한 번 읽고 검증한 뒤 평가만 실행했다. 실행 당시 source SHA는 이후 병합 HEAD로 바꾸지 않는다.
- 이후 main `d4988bffb`의 D-637 구조 변경을 topic에 통합했다. R6 이후의 GUI 종료 수리를 제외하고 CORE command·최종 port·Drive·Isaac·지도 실행 파일은 그대로다. 이전 실행의 source SHA를 이후 HEAD로 바꿔 기록하지 않는다.
- 원본 `map_v2_fleet/260919 MAP FILE.STL` SHA-256: `cabf17a84175da8be1ef7562054ec598971bbb9378810acb8cee3f686fe1f92b`.
- 기존 STL/training_scene generator와 training-curved graph, east/ring_e/ring_n/ring_w/west/ring_w/ring_s/ring_e 순서. 경로 길이 9.3420349m, 흰 외곽 네 벽 높이 0.30m.
- 기존 Pinky URDF·질량·형상·wheel gain 유지, passive caster의 servo 0. 바닥 restitution 0, physics/render dt 1/240초. 실제 runtime Kp=[0,0,0,0], Kd=[57.29578,57.29578,0,0]. SDK 단위 환산 뒤 값이며 USD 숫자와 직접 동일 비교하지 않는다.

## CORE·Drive와 학습

기존 `PathFollower`/`pursuit_index`의 후보에 tabular Q-learning이 yaw gain .75/1/1.35/1.7을 선택한다. 기존 CORE `CommandManager`와 단일 `cmd_vel_cycle` wheel callback이 최종 출력한다. SimulationOwner는 POLICY identity·0.1초 expiry/observation freshness·epoch·0.06m/s와 0.8rad/s 상한을 후보 및 최종 출력에서 확인한다. 운영 API·ROS/Fleet 연결이나 policy registry promotion은 없다.

관측은 native rigid-body world pose/속도와 고정 ordered 경로의 거리·방향이다. ROS odom/localization이나 카메라/차선·LiDAR 검증과 구분한다. 실패는 teleport·비유한 관측·벽 overlap·5cm 초과 이탈, 시간 제한은 truncation이다. 경로 끝 1.5cm 이내에 도달한 뒤 v<0.005m/s, |w|<0.02rad/s를 0.3초 유지해야 complete다. reset 전에 후보를 지우고 실제 정지를 확인한다.

| R6 단계 | 결과 | simulation 시간 | 실제 경과 | 종료 후 v / w |
|---|---|---:|---:|---|
| baseline 101 | complete | 249.4583s | 160.0089s | 0.00007991m/s / 0.00051105rad/s |
| 학습 0~5 | 6/6 complete, Q 37,591회 갱신 | 구간당 약 25~29s | 구간당 약 16~19s | 모두 stop dwell 통과 |
| 고정 eval 202 | complete, 학습 상태 57,658step | 240.5458s | 145.1235s | 0.00004623m/s / 0.00070727rad/s |
| 고정 eval 303 | complete, 학습 상태 57,658step | 240.5458s | 143.9999s | 0.00007869m/s / -0.00025672rad/s |

두 eval의 ordered progress는 9.3320085m + 끝점/실제 정지 기준 통과다. trace progress의 단조성을 별도 확인했고 최대 편차는 각각 0.0165887m/0.0165573m였다. 비기본 gain의 비영 yaw 후보가 각각 57,652/57,644step 적용됐다. Q table 9개 bin, 평가 중 Q 변경 없음. policy SHA-256: `5f24adbb1348a91d01ead863a50c08af1f7535f8d8b715b413c8fb2b8429604e`.

baseline도 complete다. 이 결과는 기존 로직에 연결한 실제 Q-learning과 독립 완주의 증거이며 baseline 대비 성능 개선 수용을 주장하지 않는다.

## 종료·자원·시험

R6 최종 cleanup v=0.00007428m/s, w=0.00026768rad/s, dwell 0.30417초. SDK exit 0, 9분55.42초, Peak RSS 4,659,484KB. GUI shutdown callback의 비동기 Traceback **1건**은 물리 결과와 별도 오류로 기록했다.

R7은 같은 SDK/URDF/importer/World에서 메뉴가 importer 후 실제 enabled인 것을 확인했다. 공통 close_sdk가 stage-close 전에 메뉴를 disable/확인하고, disable 실패에도 SDK close를 시도한다. close 반환·SDK exit 0, 원시 로그 Error/Traceback 0건, 소유 잔여 PID 없음·GPU compute 목록 비었음을 확인했다. R7은 37.71초/Peak RSS 4,607,784KB이며 맵 학습을 다시 수행한 결과가 아니다. probe SHA-256: `81cab28e55ee499b9b10b0c44a3d5544d10319f54a82433510769214d1692a47`.

R8 전체 재시험의 baseline 101·학습 6회·고정 eval 202/303은 모두 complete다. Q updates 37,591/9개 bin, 정책 SHA는 R6와 동일하다. 두 eval simulation 240.5458459초, wall 141.1525/141.1221초, ordered progress 9.3320085/9.3420349m와 실제 stop dwell 통과. SDK exit 0, 원시 Error/Traceback 0, 전체 9:29.07, Peak RSS 4,676,036KB다. 종료 수정 뒤 전체 학습을 실행하지 않았던 제한은 R8로 해소했다.

## 실제 Isaac 녹화와 시작 방향

R9는 SDK Camera의 실제 RGBA를 960×540 H.264로 저장한다. simulation 약0.2초 간격의 프레임을 25fps로 표시하는 약5배속 영상이며 위치를 보간하지 않는다. 프레임마다 SDK Fabric render 시각·physics 시각·실측 pose를 함께 보관한다. 이미지나 궤적을 그려 만든 replay 영상이 아니다. 카메라는 기록 용도이고 정책 관측은 기존 native pose/경로다.

| 시드 | 시작 경로 대비 방향 | complete/실제 정지 | simulation | 영상 | 최대 경로 편차 |
|---|---:|---|---:|---:|---:|
| 707 | 0° | 통과 | 240.5583s | 48.20s / 1,205frames | 0.0165510m |
| 808 | +90° | 통과 | 243.8792s | 48.88s / 1,222frames | 0.0165583m |
| 909 | 180° | 통과 | 244.9125s | 49.08s / 1,227frames | 0.0165599m |
| 1001 | -90° | 통과 | 242.5833s | 48.60s / 1,215frames | 0.0165711m |

네 실행 모두 같은 ordered 경로, 고정 정책 SHA와 0.3041667초 stop dwell을 확인했다. 첫 전진 후보는 각각 simulation 0/3.3250/4.3458/2.0167초이며 실제 양·음 yaw 회전이 모두 관측됐다. 이는 네 시작 방향의 평가이며 역순 경로 또는 임의 모든 방향 수용은 아니다. 최대 실제 선속도는 0.056883m/s다.

R9 SDK exit 0, Error/Traceback 0, 전체 11:46.15, Peak RSS 4,658,528KB. cleanup v=0.00005779m/s, w=0.00019094rad/s, dwell=0.3041667초. 종료 후 SDK/encoder 소유 PID 및 GPU compute 없음, source 전체 SHA 재확인. camera interpolation 경고는 있었으나 실제 프레임 시각의 단조성·시작/중간/정지 화면과 전체 영상 디코딩을 독립 검사했다.

MP4 SHA·960×540·H.264·프레임 수·전체 디코딩·실제 마지막 정지·전체 trace 단조 progress/후보 제한/5cm 이탈 한계를 별도 assert 검사했다. 정책 변경 없음, four complete, 영상 및 프레임 시각 검증 모두 통과. 사용자 요청에 따라 최종 MP4·미리보기·검사 요약·열람 페이지는 Git 제외 `private/isaac/media/2026-10-11-directions/`에 보관한다. raw trace·SDK/encoder 로그·정책은 X: session에 유지한다.

SDK venv pip check exit 0. RAM 약 15GiB 모델 PC에서 CPU trainer를 SDK와 격리 GPU trainer 없이 실행했고, 각 소유 scope는 MemoryMax 4GiB/MemorySwapMax 2GiB/CPUQuota 600%/시간 제한으로 묶었다. 시작 전 자원 floor와 GPU 작업 부재를 확인했다. Ollama inactive, ZFS ARC 4GB 제한은 sudo 권한이 없어 적용하지 못했다. swap과 단일 진단의 성공은 D-606 RAM 기준을 충족시키지 않는다.

R6 관련 CORE/Drive/Isaac/harness 원격 회귀 exit 0/NEW 0. 종료 수리 후 전체 Isaac 원격 회귀 exit 0/NEW 0. R9 녹화·정책 복원·encoder cleanup의 TDD RED 9 NEW 뒤 commit `b6a8d0d2e8` 원격 Isaac/Drive/CORE cycle/harness 시험 exit 0/NEW 0. 독립 소스 [안전 검토](safety-review.md)는 정책 단일 read/freeze·물리 정지·stop 실패 시에도 encoder cleanup·pipe close 실패 시 wait/reap을 확인했다. 원격 pytest와 실제 SDK/물리 결과는 각각 별도 증거다.

## 기록과 남은 범위

상세 날짜별 문제·가설·수정·재시험의 정본은 Git 제외 경로 `private/isaac/journal/2026-10-11-map-rl.md`다. 계획·결과·다음 일지 양식도 별도 `private/isaac/{plans,journal,results,templates}/`에 있다. 초기 진행 스냅샷은 [process](process.md)에 남긴다.

Raw evidence: 관리된 `X:\DevTemp\projects\rosy-platform\2026-10-11--145859--isaac-map-rl--1c5be0\`의 `artifacts/r5`, `artifacts/r6`, `artifacts/r7`, `artifacts/r8`, `artifacts/r9-directions/run-directions`와 `logs/` 및 모델 PC의 작업 전용 scratch. 원시 로그/trace/정책/USD는 source에 넣지 않았다.

D-606 Isaac Lab 준비, 전체 ROS-SIM 회전 추종, 센서 기반 localization·선/벽 인식, Nav2, 두 대 Fleet·신호 준수와 실물 수용은 별도 미확인/HOLD다. 사용자가 main 병합·원격 push를 요청했으며 최종 검사 뒤 수행한다. 대한민국 신호·횡단보도·두 대 Fleet는 별도 후속 목표이며 이번 네 방향 한 대 영상으로 통과시키지 않는다.

최종 착지 검사에서 이번 진단의 CORE/Drive 직접 import가 learning root의 D-427 경계를 위반한 것을 확인했다. 기존 여러 package를 조합하는 도구 소유인 `tools/sim/isaac/`로 task·runner·recorder를 옮기고 helper/test/CLI 참조를 갱신했다. import 숨김·의존 규칙 whitelist 또는 운영 코드 변경은 없다. 경로 이동 이전 R8/R9의 실행 SHA·raw evidence는 그대로 보존한다. legacy-path scan의 문자열 결합 오탐은 tuple 순서만 바꿨고 문서 commit/ledger SHA256 표기를 명확하게 했다.
