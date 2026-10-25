# 동일 모델의 durable admission 이후 관측: HOLD

2026-10-24, AI 시험 호스트의 별도 단일 진단이다. 기존 [engineering HOLD](../omx-recovered-policy-engineering-2026-10-24/result.md)와 [첫 추종 진단](../omx-policy-controller-tracking-2026-10-24/result.md)은 보존한다. [잠금 수정](../omx-policy-journal-admission-2026-10-24/result.md)의 실제 모델 실행에서 관측을 확보했으며 작업 성공이나 물리 원인 해결을 주장하지 않는다.

- runtime commit `2c47808edcf1e102a58f8a8aa2e4131406e3e245`, 로컬 main commit `46b2de59387ffe43ee83ccf507592cb248456b6d`와 실행 코드 blob 일치 확인 뒤 시작했다.
- frozen 모델 `30bba42551e85be5007d45fcef6a7e36268bad711d8bd85905ad383113cc1326`, 데이터 `9233e3c239561670ad21dd7791526561abde3c801bb4551f8df40c96c6ac3503`. 모델 결과 SHA256 `50e972da3896575210e204b160fe7a32c978b91690382c942af7e838f78c3d1e`.
- 최대 calibration1회+관측 episode1회, optimizer0/formal0/실물 권한0. world·초기화·JTC 허용치·freshness·lease 기간을 유지했다. SIM actor/collector는 앞 진단의 canonical Git blob과 같다. 물리 camera readiness/autoupdate 변경은 해당 SIM 경로에서 호출하지 않는다.
- 실행: `python run_diagnostic.py --manifest manifest.json --binding-sha256 c61981b5fa08ef4917507d33dbdc0fa40524791753a1f33b6a4785fd8f29a96d`. 기존 불변 driver를 재사용한 새 wrapper SHA256 `1458d002e9af8d1905708886eb14808baefb4c9a1293d0a0c99937f0bba849f6`. 원래60개와 새6개 입력 pins를 확인했다. 출력 경로가 이미 있으면 재실행하지 않는다.
- raw는 로컬 `C:/DevTemp/learning-execution-20261023/journal-admission-diagnostic-20261024/`에 보존한다. 공개 저장소에 raw·모델·카메라 자료를 넣지 않는다.

## 실제 결과와 종료

| 실행 | 결과 | 회수·원본 바이트 대조 | 추종 샘플 |
|---|---|---|---|
| calibration `540ae46debfc` | native 종료0/PASS | 96파일, 108489845bytes | 309 |
| 관측 정책 `49673f9a5965` | native 종료1/HOLD | 254파일, 121813335bytes | 2771 |

coordinator 종료0은 진단 수집 완료다. 정책 성공이 아니다. 두 실행 모두 PID0·빈/부재 cgroup·budget lock/reservation 부재를 실제 확인했다. 정책의 `process-cleanup.json`은 remaining_groups=[]/verified_absent=true다. 추가 실행은 하지 않았다.

정책은170 intents/170 native 수락/170 terminal이며169개 status4/result0, 마지막 status6/result−5다. 마지막 command `0d1e4fcc-327d-42f0-8c9a-abc36daee24c`, native goal `2c46bcc2-6879-46fd-a43c-ba2424c42739`. JTC 로그의 zero-based index3/4는 joint4/joint5이며 오차−0.059814/−0.028733rad, 허용치0.02rad, goal-time 초과1.010s다. admission_rejection/camera_error는null, worker_errors=[]이고 owner_final=hold다. journal_prepare170회의 중앙값5.1212075ms/최대98.506227ms는 이번 실행의 관측값이며 앞733ms 지연의 원인 해결이나 성능 보장이 아니다.

완전한2771개 추종 샘플의 여섯 관절 벡터는 finite이며 error=reference−feedback이다. 마지막 수락~terminal 사이32샘플 중19개가 최종 후보 목표와 같은 reference를 담는다. terminal 약80ms 전 샘플의 joint4/5 오차는−0.058913/−0.029425rad다. 명령 참조와 시각은 수동 관측 상관이며 native goal의 인과 바인딩이 아니다. abort 뒤 reference가 바뀌므로 마지막 샘플만으로 실패 전 오차를 판단하지 않는다.

객체 전이는[]이며 lift0.000043934m, 불완전 관측 success=false다. 원래 실행도 attach 전에 실패했고 teacher와 정책은 같은 SIM 부착 기능을 사용한다. 현재 증거는 controller 추종 실패를 지지하며 접촉·충돌·하중·그리퍼 구동 중 물리 원인을 구분하지 못한다. formal0과 원래 HOLD를 유지한다.

## 바인딩과 별도 사후 비교

- 새 ledger SHA256 `2d9fa92923c26c51b27bd1a1eff6addd35fbc2ad12dc4d6e1c41f2ade45f6b82`.
- calibration archive sha256: `227277f7411a77a5ebf598366f07d48a4f9d99a6d58e87561af24dbaf604e74e`, policy archive sha256: `b726276f4f10f7e9376f9c205059b3d192cb96bc874f49b35482aa0f174f1d83`.
- policy trace sha256: `4d3ee53adff7dfd073dcd9d13d03c4899ec620ed9790d9f426dcc06e6e352e62`, DB sha256: `abbee24de1bec1b2fabd6d6e6141ba350d77b9b4d5ff36b41799805d7ab96e67`, timing sha256: `6a105234dbc22a4a5843fe1ca6edccd13da332292afe1c6cea79ad3f90505b4c`.
- 독립 검토자가 양쪽 archive/map·전체 바이트·DB·추종 산술·terminal·closure·불변 pins를 재확인했다. 중요 불일치 없음. 추가 inference·학습·SIM 실행을 검토에 사용하지 않았다.
- 별도 사후 state-hold 비교는 기존 validation5개/7936행만 사용했다. 원본 archive/map/JSONL과 frozen offline report를 대조했고 모델 MAE0.00362326142rad, 현재 관절 유지 기준0.00636102795rad다. 동일 action/원소평균으로 독립 재계산했다. target-current arm 차이0.005rad 초과5734행은 실제 움직임 측정이 아니다. frozen gate 변경·state-copy 진단·closed-loop 성공 근거가 아니다.
- 비교 raw는 위 경로의 형제 `validation-hold-baseline-20261024/`, script SHA256 `cca3dffe690393ec71b02879e7b2b35e98bd0b2e126834ffe8d22fcd7cd29e47`, result `ddcc7ea45feba2d8792747895830816fe034e65383ee032e1e2b5f5cda77bab8`, 원래 offline report `b6d2f2fc3fed2a569c9f9d9f3076b4f07ad0274ac78f72912fb1b444e01de488`다.

CE: 미해결 — 원래 물리 추종 실패의 원인과 해결 증거가 없다. 다음 확인은 실패 전 접촉·충돌 또는 actuator 구동의 직접 증거다. 허용치·모델·동결 기준을 완화하거나 실패를 성공으로 대체하지 않는다. HF 인증 유예·실물/양팔 수용은 그대로 남는다.
