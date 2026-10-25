# OMX 학습 산출물 조사 — 2026-10-19

모델 PC와 AI PC의 허가된 사용자 계정에서 읽기 전용으로 조사했다. 제품 저장소,
정책·데이터·출력 디렉터리, Hugging Face cache와 OMX 학습 작업 디렉터리를 확인했다.
첫 광역 탐색은 파일 수 제한에 도달했다. 이어 test runs·venv·설치 파일을 제외한
관련 저장 위치를 별도 조사해 모델 PC 34,165개, AI PC 104,545개 파일을 확인했다.
두 번째 조사는 해당 root·깊이 범위 안에서 시간·파일 수 제한에 도달하지 않았다.
조사하지 않은 사용자·저장소·외부 Hub 전체의 부재를 주장하지 않는다.

## 확인한 산출물

- 모델 PC의 `omx-il-env/smoke-20261016-055551/` 아래 ACT checkpoint `000002`.
  모델 45,239,320 bytes, SHA256 `9836085982b92858eec2d42a81fe373c4d654af477e2eb0a1cbb7c010e5f90b1`.
- `train_config.json`: `steps=2`, `batch_size=2`, dataset `local/native-fixture_train`.
  전체 합성 dataset은 3 episodes/12 frames이며 train/eval/test 각 1 episode/4 frames다.
- 모델은 CPU ACT, 관절 입력·출력 6개, front RGB shape 3×32×32다.
  실작업 학습·독립 작업 성공 평가·실물 승인 기록으로 취급하지 않는다.
- 실제 관측 준비 자료는 observer samples 249개, joint messages 145개지만
  `commands_recorded=0`, `imitation_eligible=false`, `physical_task_success=null`이다.
  `collections`에는 학습용 collection이 없었다. 관측만으로 action 정답을 만들지 않는다.
- AI PC의 조사한 정책 저장 위치에서는 해당 OMX 학습 weight를 확인하지 못했다.

## 실제 작업 정책을 준비하는 순서

1. 대상 workcell/instance, leader/follower·카메라·rig·보정 revision을 확정하고,
   기존 [수집 안내](../../../learning/curation/omx/README.md)에 따라 실제 시연을 녹화한다.
   관측·action·원래 시각·출처와 성공/실패가 함께 있어야 한다.
2. `native_review.py inspect`로 실제 LeRobot reader 결과를 확인한다. 사람이 시연을
   검토하고 `split`으로 독립 train/eval/test를 나눈다. 관측 준비 자료와 합성 smoke를
   실제 시연으로 승격하지 않는다.
3. 검토된 split으로 `native_cycle.py run`을 실행한다. 저장 모델 재적재·독립 평가와
   모델/normalization 파일 hash, 관절 순서·단위, 카메라·rig·보정 binding을 확인한다.
   [학습 안내](../../../learning/training/omx/README.md)의 L0 등록 절차를 따른다.
4. 고정 revision을 새 SIM 실행에 결속하고 동작·갱신·철회·만료·E-stop·재연결 거부를
   검증한다. 현재 한 관절 고정 SIM 목표와 6관절 ACT 모델은 그대로 교체할 수 없다.
5. 실물은 별도 승인·실행 구현·장치 수용이 필요하다. 현재 physical learned-policy
   거부와 `PHYSICAL_POLICY_RUNTIME_CLOSED`는 유지된다. L0 등록이나 채팅 승인만으로
   실물 admission을 열거나 보정·작업 공간·정지 수용을 대신하지 않는다.
