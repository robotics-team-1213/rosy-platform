# ACT 학습 길이40/400 비교와 입력 적합성

2026-10-04, source checkout 89f95cd03bdb03c2e566dbf275faf76285dafd63.
같은 데이터/모델/seed로 학습 길이만 바꾼 HOST 연구 비교이다.
실제 독립 SIM 과제 성공·운영 승격 또는 장치 수용의 근거가 아니다.

## 사전 고정과 산출물

X:/DevTemp/rosy-learning-audit-20261004/act-400-step-study/experiment.json으로 실행 전에
400steps/seed42751/n_action_steps1/chunk4/batch8/CPUthreads4/AdamW lr.001/weight_decay.0001/
gradient clip1과 기존40step control, train5/fixed validation1, 원입력135개 파일 SHA를 고정했다.
평가 episode는 모델 비교에 이미 사용됐으며 새 독립 holdout이라고 주장하지 않는다.

frozen trainer SHA256:
6a2fc05eadfd09832dc45ef78b047c088ce5d5c529ba788985463106776e0371.
출력 X:/DevTemp/rosy-learning-audit-20261004/omx-act-seed42751-step1-400/.
history400개, 최초40개 loss가 기존40step과 정확히 같았다. config/normalization bytes,
DatasetManifest/135reader 파일도 같았다. 원본 입출력과 기존 거절 이력은 수정하지 않았다.
400step weights SHA256:
2c62b9841883c08625cd55c480c3681612dc9fbaed74a59c619b341093a44bbf.

trainer 내부 save/reload prediction 검증과 최종 result.json/source SHA 검사 완료를 확인했다.
elapsed200.672초. controller wrapper handle10513은 terminal **exit1**이었다.
PowerShell stderr redirection의 NativeCommandError와 최종 보고가 로그에 함께 있으며,
이 실행을 exit0 성공이라고 표시하지 않는다. 산출물의 실제 검증과 프로세스 종료 코드는 별도이다.

## 같은12frame validation 비교

| 비교 대상 | MAE rad | 의미 |
|---|---:|---|
| ACT40step | 0.0293680454 | 기존 연구 모델, reject |
| ACT400step | 0.0094026672 | 약67.983% 감소했지만 원래 gate에서 reject |
| 학습 target의 상수 평균 | 0.0059898481 | 원래 gate의 기준, 변경하지 않음 |
| 현재 관절 자세 그대로 | 0.0007052812 | 새 진단 baseline이며 원래 gate를 변경하지 않음 |

400step nominal limit 위반0, train target cluster5, 실제 eval12frame/reload 확인.
상수 평균보다 오차가 크므로 거절한다. 추가 학습만으로 품질 수용을 확보하지 못했다.

독립 reviewer /root/policy_registry_review가 immutable weights를 실제 reload하여12frame을
재계산했다. MAE .0094026748rad로 보고값과 차이8×10⁻⁹rad 미만이고, 상수 기준보다 나쁘다.
정규화/config/Dataset/reader SHA와 최초40loss 일치도 확인했다. 전체 학습을 다시 한 것은 아니다.

## 데이터 적합성 진단

train63frame/validation12frame, 총6Episode75frame이며 각Episode는 정확히 하나의 target와 command다.
75PNG 해시와 source의 action/state를 재검증했다. 연속 관측63개는 독립 작업63개가 아니다.
현재 자세만으로 target에 가까운 결과를 얻는다는 것은 많은 관측이 목표 근처에 있음을 보여준다.
입력 RGB를 활용하는 능력, pick/place 성공, 다양한 환경·작업 의도 일반화는 입증되지 않았다.
이 한계는 모델 오차가 상수 기준보다 낮아지더라도 별도 task 검증을 요구한다.

실제 frozen custom trainer의 optimizer는 lr1e-3이다. 저장된 ACTConfig optimizer_lr1e-5는
사용하지 않는 LeRobot default metadata이며 실제 학습률로 인용하면 안 된다.
실제 설정은 source/experiment에 보존했다. 향후 trainer의 config metadata와 실제 optimizer를
일치시키는 provenance 보완이 필요하다. 기존 frozen 산출물의 metadata를 덮어쓰지 않는다.

## 연구 원장과 남은 gate

신규 PolicyArtifact revision:
b64e626b6eccaf0299bcf835399a372586459a7166b641ce8df67a0e0c450a8a.
기존 Dataset revision4232ddc5fff8d505f18f07f41adfd1f0c44b087fbcebf2ae96fcf5deb70f2f93을
재검증·idempotent 등록했고 신규policy register+reject의2events를 추가했다.
독립 SQLite chain readback10events/5policies 모두unregistered를 확인했다.
owner binding은 여전히 unregistered study이며 설치 trust/issuer/authority/promotion을 부여하지 않았다.

근거: act-400-step-study/{experiment.json,input-audit.json,comparison-audit.json,registry-result.json,
result.json}, frozen trainer와 실제 output/source/reader, 원장 snapshot.
다음에는 실제 과제와 맞는 시연·상태/장면 변화·독립 평가를 보강하고, 실제 optimizer metadata와
입력/추론 timing을 검증해야 한다. 단순 step 증가나 재사용 validation의 수치로 승격하지 않는다.
trusted owner composition/독립SIM/stop readback/Fleet/Pinky/shadow/rollback, 사람 영상 라벨과
새 클래스 학습, model PC 전체job/DEVICE/FIELD 및 전체 목표는 미완료이다.
