# OMX 고정 예산 복구 학습과 실제 재로딩 검증

2026-10-24 KST 검사다. [원래 중단된 학습](../omx-fixed-budget-input-audit-2026-10-24/result.md)은 HOLD로 보존했고, [검증된 선택형 원격 실행](../omx-durable-learning-transport-2026-10-24/result.md)을 사용하는 별도 복구 시도 한 번을 사전에 고정·독립 검토했다. 원래 claim·동결7개·36개 수집·25개 선택은 바꾸지 않았다. 중단된 optimizer를 재개하거나 실패 회차를 대체한 결과가 아니다.

## 실행과 실제 완료

- 실제 ML source는 commit `8d119665da8f`, 전송 구현은 main commit `ed473fde01`이다. MODEL 역할에서 8 CPU·6GiB·120분 한도를 유지했다.
- study `fixed-budget-teacher-training-recovery-r1-8d1196`, native ID `sim-8d119665da-63bc43`을 한 번 제출했다. 새 요청은 원래 recipe origin과 실제 recovery launcher·binding·부모 interrupted claim을 따로 기록한다.
- recipe는 10,000step·seed42750·부모 모델 없음·`n_action_steps=1`·`command_entry_and_exit`·`joint_delta_tanh_from_chunk_source_v1`·학습 state noise0.01이다. 학습과 입력 검사 코드는 동결된 원본을 사용했다.
- 07:25:10 KST 같은 원격 작업의 terminal rc0과 최종 `trained_reloaded_offline_verified` 결과를 확인했다. 로컬 runner도 실제 종료0이며 회수를 마쳤다. 완료 표식은 같은 run·metadata·100파일/53,757,260바이트의 정확한 해시 목록을 묶는다.
- 07:28:53 KST 읽기 전용 관측에서 scope inactive/dead·빈 cgroup·lock/예약 없음, 원격 source/OUT 정리와 별도 terminal journal 보존을 확인했다. 영구 학습 study는 유지한다.

목표 설정의 `steps=10000`이나 중간 상태를 완료 근거로 사용하지 않았다. 영구 `model/history.json`의 손실값이 실제로 10,000개이고 모두 유한값임을 확인했다. 첫 손실은1.5707206726, 마지막은0.7397014499다.

## 오프라인 결과와 재로딩

고정 train20개·validation5개를 유지했다. 전체 validation7,936프레임의 MAE는0.0036232614rad, 상수 기준선은0.2918046737rad다. limit violation0, 타깃 군집556개이며 전체와5개 episode별 판정은 `offline_only`다. `independent_task_success=unverified`를 유지한다. 이 오차를 작업 성공률로 바꾸어 해석하지 않는다.

정규화는 train20개에만 맞췄고 변환 범위0.035rad·학습 전용 noise0.01·seed42751을 확인했다. 저장된 CPU ACT 설정은 chunk4·소비 action1·dim64/heads4·VAE 없음·사전 모델 없음이다.

trainer 내부 재로딩 검사 외에 서로 다른 새 프로세스 두 개가 같은 저장 가중치·정규화·첫 validation 원본 RGB/state를 읽었다. PID는1224982와1225036이다. 원래 RGB320×240와 sample line 해시가 실제 원본과 일치하고 chunk0·현재 입력 소비·6개 유한 관절값·1e-6 수치 일치를 확인했다. 두 stdout의 proof는 보존된 JSON과 같고 stderr는 모두0바이트다. 부모 PID 숫자는 별도 보존되지 않았으며, 동결 worker가 PASS 전에 child PID와 부모 PID의 차이를 검사했다는 범위만 주장한다. 재로딩의 합성 시계는 실제 제어기의 freshness·운영 권한 근거가 아니다.

## 데이터·모델 무결성

영구 dataset의25개 episode·80,547개 선언 파일/1,731,229,079바이트를 모두 실제 해시와 대조했다. 추가·누락·symlink가 없고 sealed DatasetManifest와 읽기 전용 SQLite 등록이 같은 revision을 가리킨다. policy의 dataset 연결·training-index·normalizer·실제8d trainer tool 해시와 회수한 policy bundle의 모든 파일도 일치한다. 이 저장소는 해당 study의 로컬 DatasetStore이며 운영 승격을 뜻하지 않는다.

학습 뒤에도 원래36개 export 전체58,109파일/1,279,177,309바이트가 사전 inventory와 같다. 동결 worker의 동일 `verify_inventory` 함수를 읽기 전용 검사에 재사용했다. 원래 중단된 study에는 여전히 최종 가중치·완료 결과가 없다.

독립 검토에서 로컬100파일·요청/claim·원본 RGB/sample·bundle을 먼저 대조했고, 이후 두 실제 MODEL 검증 스크립트와 실행 payload 해시를 재구성해 영구 history/dataset/export/reload 증거까지 확인했다. Important 지적이 없었다. 재검토에서 ML·추가 optimizer·정책 trial을 실행하지 않았다.

| 보존 근거 | SHA-256 |
|---|---|
| 복구 protocol | `sha256:3b656303ab1ab30339f664587170610a3ee5745aa4d0e1c9c92e470a864def75` |
| 실제 요청 | `sha256:9bc0360c9695cf8ce0dd025bddfe1927626a0594e4c1a734148cdc043a892f16` |
| native metadata | `sha256:b6e552672221f9d77ddfd016078bd3a0792b19857dfd04865b6de7763a91d8e3` |
| 완료 model result | `sha256:50e972da3896575210e204b160fe7a32c978b91690382c942af7e838f78c3d1e` |
| 실제10k history | `sha256:5403c6c8b6c4f85e3f4826e9759506b2bc142871bd794d7f24c4067c37050597` |
| offline report | `sha256:b6d2f2fc3fed2a569c9f9d9f3076b4f07ad0274ac78f72912fb1b444e01de488` |
| 두 별도 process reload | `sha256:69bf18578fc09277872c15efc2a31e7bdb700a848746604cc759562c668fcf12` |
| sealed policy revision | `sha256:30bba42551e85be5007d45fcef6a7e36268bad711d8bd85905ad383113cc1326` |
| sealed dataset revision | `sha256:9233e3c239561670ad21dd7791526561abde3c801bb4551f8df40c96c6ac3503` |
| 완료 회수 표식 | `sha256:b2d9198a899c00a2320936b466d8af788479cf75069a7f17b6a95d54727b411b` |
| 실제 history/dataset 검증 | `sha256:89e7f8e6b34e661b6ca34999e475f4cd09798b126c8747cd9bdcd5a6f0e257c7` |
| 실제 export/reload lineage 검증 | `sha256:c0272e03ecf1d99b089b4373e53d81e8a0b199769aec06d662072962b4134644` |

원본은 Git 밖 `learning-execution-20261023/`의 해당 study와 `verified-recovery-model.json`, `verified-recovery-reload-lineage.json`에 보존한다. 원격 영구 study의 원본 history·dataset snapshot·reload stdout/stderr도 유지한다. 공개 기록에는 주소·private 설정·원본 이미지·가중치를 넣지 않는다.

## 다음 단계의 경계

위 결과는 학습·오프라인·재로딩 수용까지다. 독립 SIM 정책 성공·실물·HF 업로드·제품 운영 승격은 아직 수용하지 않는다. 별도 평가 manifest를 고정·검토한 뒤 원래 calibration→engineering1회→formal20회/18성공 기준으로만 평가한다. 실패 대체·추가 학습·기준 변경은 허용하지 않는다. HF 인증은 사용자의 결정대로 연기한다.

CE: 해당 없음 — 이번 완료·해시·재로딩 검증의 판단은 동결 코드와 위 실제 증거에 직접 남았다. 원래 중단의 정확한 정지 주체와 기존 물리 원인은 별도 미해결이다.
