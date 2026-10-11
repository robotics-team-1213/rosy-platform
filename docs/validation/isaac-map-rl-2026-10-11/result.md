# Isaac 실제 맵 CPU RL — 한 대 진단 검증 결과

D-638의 한 대 native CPU 진단에서 기존 CORE·Drive로 학습하고 고정 정책의 두 독립 시드에서 ordered 경로 완주와 실제 정지를 확인했다. 전체 ROS-SIM/Isaac Lab/Fleet·신호/실물 수용은 HOLD다.

## 실행한 source와 지도

- 전체 맵 R6: `dc25401e6141a365dfee918ca1ecc97254a1ffa5`, 시작 직전 main `19e1c7eef` 포함, source 7,014파일 전후 SHA-256 일치.
- 종료 수리 R7: `e0e5b38d788d7dbbed73900db0b986e236673838`, source 7,014파일 전후 일치. 전체 맵 재학습이 아닌 별도 URDF/world 종료 생명주기 검사다.
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

SDK venv pip check exit 0. RAM 약 15GiB 모델 PC에서 CPU trainer를 SDK와 격리 GPU trainer 없이 실행했고, 각 소유 scope는 MemoryMax 4GiB/MemorySwapMax 2GiB/CPUQuota 600%/시간 제한으로 묶었다. 시작 전 자원 floor와 GPU 작업 부재를 확인했다. Ollama inactive, ZFS ARC 4GB 제한은 sudo 권한이 없어 적용하지 못했다. swap과 단일 진단의 성공은 D-606 RAM 기준을 충족시키지 않는다.

R6 관련 CORE/Drive/Isaac/harness 원격 회귀 exit 0/NEW 0. 종료 수리 후 전체 Isaac 원격 회귀 exit 0/NEW 0. 독립 소스 [안전 검토](safety-review.md)를 거쳤다. 원격 pytest와 실제 SDK/물리 결과는 각각 별도 증거다.

## 기록과 남은 범위

상세 날짜별 문제·가설·수정·재시험의 정본은 Git 제외 경로 `private/isaac/journal/2026-10-11-map-rl.md`다. 계획·결과·다음 일지 양식도 별도 `private/isaac/{plans,journal,results,templates}/`에 있다. 초기 진행 스냅샷은 [process](process.md)에 남긴다.

Raw evidence: 관리된 `X:\DevTemp\projects\rosy-platform\2026-10-11--145859--isaac-map-rl--1c5be0\`의 `artifacts/r5`, `artifacts/r6`, `artifacts/r7`과 `logs/` 및 모델 PC의 작업 전용 scratch. 원시 로그/trace/정책/USD는 source에 넣지 않았다.

D-606 Isaac Lab 준비, 전체 ROS-SIM 회전 추종, 센서 기반 localization·선/벽 인식, Nav2, 두 대 Fleet·신호 준수와 실물 수용은 별도 미확인/HOLD다. 기존 CORE 수리의 main 착지는 완료했지만 새 RL topic은 착지·push하지 않았다.
