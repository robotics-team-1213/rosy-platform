## D-566 `v13.1.00`의 선 바깥 오탐을 게이트로 막고, 모델 PC의 긴 작업은 메모리 상한을 둔 백그라운드 단위로만 돌린다

**Status:** Accepted (2026-10-09, 사용자 결정). 1·2항은 `v13.1.01`부터, 3항은 다음 모델 PC 작업부터 적용한다.

### Problem

1. **선 바깥 오탐이 남았다.** D-554 9·10항 라벨로 학습한 `v13.1.00`(`v13-drivable-20261009-4e60dac5`)의 결과는 다음과 같다. 1,428장으로 학습했고 카나리아는 163/181 = 0.901, val drivable IoU는 0.901(부모 배경 화소)이다. 그러나 **선 바깥 띠의 drivable 오탐률은 0.496**으로, 선 바로 바깥 바닥의 절반을 여전히 drivable로 칠한다. epoch마다 0.36–0.90으로 흔들렸고, best epoch는 IoU만으로 골랐다. `v13.0.00`이 "카펫 전체를 칠한" 문제가 줄었다는 근거가 아직 없다.
2. **원인 가설.** 음성 띠는 도로 폭의 절반뿐이라, 화소 수가 drivable의 약 3분의 1이다. 손실에 클래스 균형이 없고, 선택 기준에 오탐이 빠져 있다. 경계 근처 화소는 부모 차선 클래스와 붙어 있어 헤드가 구분하기 어렵다.
3. **모델 PC가 멈췄다.** 2026-10-09 18시대, `v13.1.00` intake(재생 7,160프레임) 중에 OMEN이 응답을 멈췄다. LAN ping은 약 230 ms로 살아 있었지만, SSH는 배너 단계에서 시간이 초과됐다. 같은 시간에 다른 세션의 `remote_pytest`도 이 PC에서 돌았다. intake는 노트북의 포그라운드 SSH로 실행해서, 연결이 끊기며 작업도 함께 잃었다. 이 PC는 이전에도 트래커 RAM 때문에 멈춘 적이 있다.

### Decision

1. **선 바깥 오탐을 shadow 게이트에 넣는다.** drivable 후보는 val의 drivable IoU와 함께 `val_outside_band_fp`를 기록한다. shadow intake는 `val_outside_band_fp ≤ 0.15`일 때만 통과한다. 화면 아래 40% 가운데 열의 예측 drivable 비율은 라벨 비율의 0.8배 이상이어야 한다(D-563 4항의 앞길 지표). 기준을 넘지 못한 후보는 원장(D-558)에 `rejected`로 남긴다. 실물 shadow는 기준을 넘은 후보만 올린다.
2. **같은 규칙으로 다시 학습한다(`v13.1.01`, patch).** 라벨 규칙은 그대로 두고 학습만 바꾼다.
   - 손실의 drivable/비drivable 화소 가중치를 val 화소 비율의 역수로 둔다.
   - best epoch를 IoU 대신 `IoU − λ·outside_band_fp`(λ는 기록)로 고른다.
   - 기준을 넘지 못하면 띠 폭 `k`(D-554 9항)를 늘리는 minor 변경(`v13.2.xx`)을 따로 결정한다. 지도 투영 라벨(D-563 3항)이 그 다음 minor다.
3. **모델 PC의 긴 작업 규칙.** 학습, intake, 대량 추론처럼 5분을 넘는 작업은 다음을 지킨다.
   - 노트북 SSH의 포그라운드로 돌리지 않는다. 모델 PC에서 `systemd-run --user --unit=<이름> -p MemoryMax=<한도> -p MemorySwapMax=0`으로 실행한다. 한도의 기본값은 물리 메모리의 60%다. 로그는 실행 폴더에 남긴다. 상한을 넘으면 그 작업만 죽고 PC는 살아 있다.
   - GPU 작업은 기존 `gpu_lease`로 하나씩만 돈다.
   - 시작 전에 `free`와 다른 세션의 작업(`remote_pytest` 실행 폴더, 사용자 유닛)을 보고, 사용 가능한 메모리가 한도보다 적으면 기다린다.
   - 작업이 끝나거나 실패하면 결과 파일로 판단한다. SSH 세션이 살아 있는지로 판단하지 않는다.

### Consequences

- `v13.1.00`은 intake를 다시 돌려도 1항 게이트 때문에 shadow로 가지 않는다. 비교 기록용 `candidate`로 원장에 남긴다.
- 모델 PC의 멈춤 원인은 재부팅 뒤 `journalctl -k`(OOM 기록)와 당시 프로세스로 확인해, 이 ADR의 Problem 3항에 덧붙인다.

**Related:** [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-558](D-558-drivable-model-semantic-version.md), [D-563](D-563-drivable-near-road-false-negative-and-map-pose-labels.md), [D-553](D-553-cd-speed-parallel-build-and-test-pcs.md).
