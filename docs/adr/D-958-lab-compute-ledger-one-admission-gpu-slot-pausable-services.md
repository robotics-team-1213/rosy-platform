## D-958 실험실 PC 계산 작업은 호스트마다 한 입구로 받고, GPU는 한 자리로 세며, 상시 서비스는 양보한다

**Status:** Proposed (2026-11-02). 사용자 요청 「모델이나 프로세스, 병렬, 컴퓨터 자원까지 관리하는 파이프라인 — 이 PC들이 굉장히 중요하다」. 설계만 정하며 구현은 아래 단계마다 별도 변경이다.

**관련:** D-568·D-571(자리 고르기) · D-866 §3·§4(GPU 배치 작업, `hold_gpu`) · D-897(호스트·seed마다 독립 작업, 서비스 일시 중지) · D-852·D-530(호스트 서비스 대장) · D-446(model-code `work.lock`) · D-434·D-527(PC 역할) · D-584

### Context

조사(2026-11-02, 이 브랜치 기준)와 같은 날 Isaac 배치에서 드러난 사실이다.

- **입구가 둘이고 서로 모른다.** `~/rosy-jobs`의 `*.lock`/`*.resv`(코어·GB, `host_probe`가 합산)와, GPU·model-code를 지키는 `flock`(`~/.cache/rosy-learning/gpu.lock`, `<model_code_root>/work.lock`)이 따로 있다. `hold_gpu.sh`는 표시만 하고 `gpu.lock`을 잡지 않고, `run_admission`·`train_job.gpu_lease`는 `gpu.lock`만 잡고 `~/rosy-jobs`에 쓰지 않는다.
- **실제로 기다려 받는 입구는 pytest뿐이다.** `remote_job.ADMIT`(`.admit` flock, 코어·GB 합)만 대기·승인한다. sim, `fleet_trips`, `hold_gpu`, Isaac, native sim, 검수 파이프라인 타이머, Pinky 학습은 `.admit`을 지나지 않는다. 노트북이 고른 뒤 시작하기 전 다른 작업이 끼어든다(Isaac run 991a, 2026-11-02 회전 시험이 다른 배치에 GPU를 뺏겨 실행 없이 끝남).
- **상시 서비스가 GPU 승인을 늘 막는다.** AI PC Ollama(`warm.conf`, 약 8 GB)와 SAM 워커가 GPU 프로세스로 떠 있어 Isaac 승인(GPU 프로세스 0개)이 항상 거절됐다. 모델 PC Ollama·review-v12/v13도 같은 이유로 Isaac과 model-code 업데이트(`gpu_busy`)를 막을 수 있다.
- **멈춘 서비스를 되살리는 책임이 노트북 프로세스에 있다.** 2026-11-02 `isaac_batch --pause` 대신 쓴 임시 스크립트가 세션 종료로 죽자 AI PC Ollama가 꺼진 채 남았다.
- **노트북이 꺼지면 작업 진행도 멈춘다.** 원격 실행은 살아 있어도 다음 실행을 넣는 드라이버가 노트북에 있다. 세션 재시작으로 배치 세 개가 한꺼번에 끊겼다.
- **우선순위·양보가 없다.** 일시 중지는 `isaac_batch.service_window`와 손 `systemctl`뿐이다.
- **한눈에 볼 곳이 없다.** 상태가 `~/rosy-jobs`, `~/rosy-test/runs/*.jobs`, `~/.config/rosy/isaac-runs`, systemd 저널에 흩어져 있다.
- 자리 고르기·입구·조사기는 이미 `tools/remote`가 소유한다(D-427 import 규칙 밖). 서비스 선언은 `deploy/hosts/services.yaml`(D-852)에 있다.

### Decision

1. **호스트마다 입구는 `remote_job.ADMIT` 하나다.** 모든 계산 작업(pytest, browser, sim, gpu, alone)은 시작 전에 `~/rosy-jobs/.admit`을 지나 자기 `*.lock`(pid가 살아 있는 동안 유효)을 남긴다. `hold_gpu.sh`, `remote_isaac`, `train_job`, `native_sim_job`, `fleet_trips`, 검수 파이프라인의 GPU 단계가 이 입구로 들어온다. 새 입구·새 잠금 위치를 만들지 않는다.
2. **GPU는 호스트마다 한 자리다.** `gpu` 등급 작업은 그 자리를 독점한다. 자리를 잡으면 `gpu.lock`도 함께 잡아 기존 `run_admission`·`gpu_lease` 검사와 맞물린다. 자리가 차 있으면 기다린다(거절하고 끝내지 않는다). `CUDA_VISIBLE_DEVICES`를 비우는 pytest 보호는 `gpu` 등급 잠금 전체를 본다.
3. **상시 GPU 서비스는 「양보함」을 선언한다.** `services.yaml` 항목에 `gpu: idle-yield`(노는 동안만 멈춤, 4) 또는 `gpu: keep`(멈추지 않음)을 둔다. `gpu` 작업이 자리를 받을 때 입구가 노는 `idle-yield` 서비스를 멈추고 `~/rosy-jobs/paused-<unit>` 표시를 남긴다. **되살리기는 호스트가 한다**: `gpu` 잠금·예약이 하나도 없고 표시가 남아 있으면 호스트의 조사(`host_probe` PROBE)와 사용자 타이머가 그 유닛을 다시 켜고 표시를 지운다. 노트북·배치 프로세스가 죽어도 서비스가 꺼진 채 남지 않는다. 현장 PC 서비스와 실물 장치 owner는 `idle-yield`로 선언하지 않는다.
4. **각 PC의 본업이 최우선이고, 실험은 노는 자원만 쓴다** (사용자 결정 2026-11-02 「모델 PC와 AI PC가 실제로 처리하는 역할이 최우선, 유휴 자원을 쓰게 한다」).

   | PC | 본업(항상 먼저) | 노는 상태의 신호 |
   |---|---|---|
   | AI PC | 실시간 상황 서비스(D-577, Ollama 시각 추론, 10초 기한), Pinky 학습(D-897) | Fleet에 운행 중인 로봇이 없고, 상황 서비스의 마지막 추론 요청이 10분 넘게 없음 |
   | 모델 PC | 검수 파이프라인·시험 운전 기록 수집(타이머 작업), 사람이 쓰는 검수 화면(review v12/v13 추론), model-code 업데이트(D-446), 계획된 학습(D-434) | 본업 타이머 작업이 돌고 있지 않고, 검수 화면의 마지막 추론 요청이 10분 넘게 없음 |

   실험 배치(Isaac 훑기, sim 훑기, seed 반복)는 그 PC가 노는 상태일 때만 입구를 받는다. 착지 시험(pytest 게이트)은 실험보다 앞이지만 본업보다는 뒤다. **본업 요청이 들어오면 실험이 양보한다**: 입구가 그 PC에서 돌고 있는 실험 실행을 멈추고(실행 기록 `STOPPED`) 대기열에 다시 넣으며, 멈췄던 본업 서비스를 곧바로 되살린다. 실험 실행 하나는 10~12분이라 잃는 것은 그 실행 하나뿐이다. AI PC는 Fleet 운행 중에는 처음부터 실험을 받지 않는다(Ollama 재적재와 GPU 반납이 10초 기한을 넘길 수 있다). 본업 서비스는 전부 `gpu: keep`이 아니라 「노는 동안만 멈춤」(`gpu: idle-yield`)으로 선언하고, 노는 상태 판정은 그 서비스가 직접 내는 마지막 요청 시각으로 한다.
5. **배치 대기열은 노트북이 아니라 모델 PC에 둔다.** 계획(실행 목록 또는 `cases`×`seeds` 격자, 현행 `isaac_batch` 형식)을 모델 PC의 사용자 서비스 대기열에 제출하면, 그 서비스가 두 PC의 입구에 실행을 넣고 결과를 모은다. 실행마다 `request`/`receipt`/`result` 세 파일을 남겨 끝난 것은 건너뛰고, 시작된 것은 그 호스트에서 이어 받고, 나머지만 새로 시작한다(`isaac_batch`의 규칙을 모든 작업 종류로 넓힌다). 노트북은 제출·조회·결과 가져오기만 한다.
6. **한 화면.** `tools/remote/lab_jobs.py status`가 모든 호스트의 입구 상태(GPU 자리, 코어·GB, 대기열, 멈춘 서비스, 최근 결과)를 한 표로 낸다. 같은 자료를 Learning center 화면에 나중에 붙인다.
7. **예약은 짧게 갱신한다.** Isaac HOLD의 2시간 예약은 10분으로 줄이고 상태 조회마다 갱신한다. 클라이언트가 사라진 예약이 자리를 오래 쥐지 않게 한다.

### 단계

| 단계 | 내용 | 수용 |
|---|---|---|
| 1 | `services.yaml` `gpu: idle-yield/keep`, 호스트 측 되살리기(PROBE + 사용자 타이머), 본업 서비스의 마지막 요청 시각, Isaac 예약 10분 | AI PC에서 배치 프로세스를 강제로 죽여도 Ollama가 10분 안에 다시 켜짐. 본업 요청이 들어오면 실험 실행이 멈추고 다시 줄에 섬 |
| 2 | `.admit`에 GPU 자리·우선순위·대기, `hold_gpu`·`remote_isaac`·`train_job`이 입구를 지남 | 두 배치를 동시에 넣어도 둘 다 끝까지 돎(현재는 하나가 실행 없이 끝남) |
| 3 | 모델 PC 배치 대기열 서비스, `lab_jobs.py status` | 노트북을 끈 채 24개 배치가 끝나고, 다시 켰을 때 결과를 가져옴 |
| 4 | 검수 파이프라인 GPU 단계·Pinky 학습·native sim도 입구로 | 한 화면에 모든 GPU 사용이 보임 |

**1단계 진행(2026-11-02):** `deploy/hosts/gpu_tenants.py`·`rosy-gpu-tenants.timer`를 AI PC에 설치했다. Ollama(`gpu: idle-yield`)는 로봇이 온라인이 아니고 최근 제안이 없을 때만 빌려주고, 빌리는 동안 situation `owner_mode`는 `shared`다. 호스트가 1분마다 확인하되 GPU 작업 잠금·Isaac 예약·기존 `gpu.lock`이 모두 비었을 때만 되살린다. `owner_mode`는 helper가 쓴 `shared`의 수정 시각이 그대로일 때만 복원해 그 사이 소유자의 변경을 보존한다. Isaac 예약은 10분이며, 예약이 만료돼도 worker의 `gpu.lock`이 남으면 복구를 미룬다. 강제 종료 수용 시험은 2026-11-02 통과했다: 배치를 13:44에 강제 종료하자 마지막 Isaac 예약이 10분 뒤 만료됐고, 13:54 점검이 표시 파일을 지우고 `owner_mode`를 `available`로 되돌렸다(설치본은 이 단락의 lease·owner mode 보강 이전 판). 본업 요청에 따른 실험 선점·재대기와 모델 PC 적용은 남았다.

### Consequences

- 잠금 위치가 다섯 곳(`~/rosy-jobs`, `~/.cache/rosy-learning`, model-code root, `%t`, `/tmp`)에서 `~/rosy-jobs` 중심으로 모인다. 기존 `gpu.lock`·`work.lock`은 바깥 방어로 남긴다.
- 실험 배치는 검수·추론보다 늦게 자리를 받으므로 사람이 쓰는 시간대에는 느려질 수 있다. 대신 서비스가 꺼진 채 남는 일은 없어진다.
- 모델 PC에 상시 서비스가 하나 늘어난다(D-852 대장에 등록, D-871 자동 업데이트 대상).
- `isaac_batch.py`의 `--pause`·이어 받기 규칙은 단계 1·3에서 이 결정의 공용 부품으로 옮기고, 그 뒤 도구는 얇은 제출기가 된다.

### 미결 (사용자 확인)

- ~~우선순위 순서~~ → 결정됨(본업 최우선, 실험은 노는 자원, 2026-11-02).
- 노는 상태 판정의 10분 기준. 상황 서비스·검수 화면이 마지막 요청 시각을 내는 방법은 구현 단계에서 각 서비스 소유 코드에 더한다.
