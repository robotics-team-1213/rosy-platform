# OMX 물체 과제 RGB·SIM 정답 편입 — 2026-10-21

실제 Gazebo 물체 시연 한 개를 원본 증거로 재검증하고 모델 PC에서 LeRobot 영상으로
내보낸 뒤 2,650장을 모두 재독출했다. **학습 파이프라인 전체 목표는 미달성이다.**
train 20/validation 5, 학습 checkpoint 재적재, 새 정책 과제 20회 중 18회 이상 성공이 필요하다.

| 지표 | 실제 값 | 범위 |
|---|---:|---|
| RGB 수집을 시작한 시연 | 7회 | 실패도 분모에 보존; 준비만 한 job 제외 |
| complete RGB 시연 | 2/7 | native 3과 batch 4 첫 시연 |
| 원 owner/gripper 증거까지 검증한 시연 | 1/25 목표 | 아직 train/validation 분할 전 |
| 실제 영상 export/readback | 2,650/2,650장 | LeRobot 0.4.4, v3.0, sim_ground_truth |
| 영상 readback 최대 프레임 평균 오차 | 1.79319/255 이하 | 기존 허용치 8/255 |
| 학습 checkpoint | 없음 | 학습 NOT RUN |
| 독립 학습 정책 물체 평가 | 0회 | 성공률 미산출; 0%로 표시하지 않음 |

일곱 시도는 RGB native 2·3, batch 1·3, batch 4 두 시도, batch 5 한 시도다.
규칙 제어기의 별도 [baseline 1/1](../omx-object-baseline-2026-10-21/result.md)은
학습 정책 성공률에 합산하지 않는다. 모든 물체 실행은 명시적인 부착 보조 SIM이다.

## 실제 편입 결과

수집 source `71c5b5a4d2182c18ad5ff7fdedd008c4fdd29910`, run nonce `b62e120a55e3`,
episode `e78fe2cf-3e86-4345-8d50-dac1b6f3509c`의 첫 시연이다.
독립 물체 관측을 재계산한 들림은 0.10201623383909464m,
XY 오차는 0.00006435743809894127m, Z 오차는 0.00000004619359970231551m,
해제 뒤 안정 시간은 2.224초다. 수집 wall 327.591초, complete, 종료 정리 확인이다.

원본 archive는 42,303,888 bytes,
SHA256 `5e23cfefa00f0648f92d3ab2f563d82609c79f440e5615c53047b847d29f8216`다.
모델 PC의 작업 전용 input에 복사한 뒤 archive와 모든 materialized file bytes를 대조했다.
검증/export source는 `0973db044a`다. 승인된 `remote_sim.py --host model`로 실행했다.
원본 시연·명령 수락/완료·gripper owner 시계·장면·카메라·물체 관측을 검증한
companion과 실제 judge는 export의 `rosy_sim_truth/`에 보존됐다.

첫 export는 전용 NumPy와 OS SciPy의 ABI 충돌로 실패했다. 새 run은 작업 전용
SciPy 1.15.3 overlay를 사용했고 공유 venv를 변경하지 않았다. 최종 runner exit0이다.
운영자 외부 scratch `pipeline-completion-20261021/omx-object-truth-model-2/out/`의
`truth-result.json`, `object-export-result.json`, `export/`에 결과가 있다.
같은 job `run.txt` SHA256은
`14c377f97e1391464d0072d837e76b078ce0808a97ff0e23cef95485c5b366f7`이다.

이전 native 3의 complete RGB 2,644장은 원 owner/gripper 신선도 원문이 없어 이 새
자동 정답으로 소급 편입하지 않았다. 과거 파일에 새 관측이나 시각을 채우지 않는다.

## 남은 수집 실패와 수정 검증

batch 4 두 번째 시연은 2,318장 뒤 영상 275.800초와 직전 관절 275.748초의 52ms
차이로 거절됐다. 최신 관절은 275.928초였다. batch 전체는 1/2·HOLD·정리 확인이다.

관절 기록이 기본 카메라 callback group에 막히는 현상을 실제 ROS에서 재현했다.
`0973db044a` RED 1 failed/1 passed, `f36d56762a` 분리 후 2 passed/0 skipped다.
그 뒤 실제 batch 5는 2,257장 뒤 72ms skew로 다시 실패했다.
영상 270.200초·직전 관절 270.128초·최신 관절 270.268초이며 0/1·HOLD·정리 확인이다.
archive 20,827,012 bytes, SHA256
`abda008913ba5f9f87d361408b10c987434c18905e3e1a581a32400669d2888f`를 보존했다.
콜백 분리만으로 전체 수집 문제가 해결됐다고 판단하지 않는다.

`5384de9e63`의 실제 ROS 재현에서는 콜백을 잠시 멈춘 동안 보낸 과거 샘플 100개 중
depth 5 큐가 마지막 5개만 보존했다(1 failed/2 passed). 실제 실패의 모든 원인을
이 재현 하나로 확정하지 않는다. `8eac830ce0`은 같은 sensor QoS를 복사하고 기록용
관절 subscription의 depth만 512로 늘렸다. 50ms skew, 미래 상태 금지, live 신선도
0.5초, source clock, command owner 한계와 부착 판정은 유지했다.

최신 depth 수정의 GREEN은 **미실행**이다. AI 시험 PC는 VPN offline, 모델 PC는
승인된 SSH 경로에 접속할 수 없어 두 `remote_sim` 준비 검사가 실행 없이 종료됐다.
로컬 VPN은 Running/online·health 이상 없음이었다. 호스트 재시작·정책 변경·
로컬 SIM/pytest로 우회하지 않았다. RED job의 원격 output archive fetch도 연결
오류로 실패했으며 runner stdout과 원격 작업 폴더를 보존했다.

## 소스 검증과 다음 단계

학습 계약 0.1.13은 raw gripper/owner freshness·고정 자산·실제 accepted/terminal
goal·원본 byte closure를 검증한다. ACT는 train-only 정규화와 sampling,
여러 validation episode 간 reset을 수행한다. 명시된 자동 증거가 사라지면
operator로 바꾸지 않고 거절한다. 재생은 에피소드별 오차/판정과 전체 판정을 구분한다.

- `d324a77929`: 관련 원격 45 passed.
- `f36d56762a`: 확장 원격 521 passed/4 skipped, harness 3 failures.
  자기 로그의 누락 필드·날짜 정렬·generated index를 고쳐 재검증했다.
- `ac33a60200`: 소비자·DatasetStore·harness 등 174 passed, NEW0.
- `844d9896c8`: 단일/다중 검증 episode의 재생 제어 흐름 2 passed/0 skipped.
  이 시험은 stub reader이며 실제 학습·수치 모델 증거가 아니다.
- `844d9896c8` 전체 변경의 독립 읽기 전용 검토에서 지원되는 지적 없음.
  후속 depth 수정은 별도 검토·원격 GREEN과 실제 반복 수집이 필요하다.

연결 회복 후 최신 실제 ROS GREEN→반복 시연 수집/정답 검증→train 20/validation 5
동결→모델 PC 학습/reload→새 정책 20회 순서로 진행해야 한다. 학습 정책의 실행
설치 binding도 아직 남아 있다. 기존 세션은 `timing.period_ns`를 실제 goal duration으로
소비하므로 연구 artifact의 100ms와 시연 goal의 0.8초를 명시적으로 정합시켜야 한다.
첫 학습 정책 평가 전에 owner·timing·lease·camera 예산을 고정하고 검증해야 한다.
현재 커밋 보존은 병합·학습 정책 실행·DEVICE/FIELD 수용을 의미하지 않는다.
