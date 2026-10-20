# 암·주행 로봇 학습 파이프라인 현황 점검 보고서

작성일: 2026-10-19 KST. 대상: LeRobot 기반 OMX 암, Pinky 계열 주행 로봇.

## 1. 종합 판단

**두 파이프라인 모두 학습·추론·실행을 연결하는 코드와 부분 실행 증거가 있다. 그러나 ‘실제 데이터를 모으고, 독립 평가를 통과한 모델을 로봇에 적용해 과제 성공을 확인하고, 실패를 다음 학습으로 돌리는 과정’ 전체가 완료됐다고 판단할 근거는 부족하다.**

암은 실제 시연·학습 결과를 안전한 실물 실행과 과제 성공 판정까지 연결하는 것이 남았다. 주행은 기존 학습·검수 자료를 현재 목적에 맞는 독립 정답으로 정리하고, 학습 모델이 실제 제어에서 사용되는지와 그 성능을 검증하는 것이 남았다. 코드 시험 통과, 모델 파일 생성, 명령의 성공 응답을 각각 과제 성공으로 계산해서는 안 된다.

| 구분 | 확보한 것 | 아직 완료되지 않은 것 | 현재 판단 |
|---|---|---|---|
| 암: 직접 LeRobot → device-core | 녹화 잠금, 카메라 보정 연계, 실제 SDK 모델·processor 적재와 추론, SafeDriver 실행 경로 | 이 경로에 사용할 실제 시연 학습 체크포인트, 실물 통합 실행, 과제 성공 판정 | 실물 학습 실행 준비 단계 |
| 암: ROSY Platform CORE/Fleet 연동 | 시연 export·ACT 학습·재적재·평가 도구, CORE 관측·정책 후보 전달, native ROS Action 검증 | 실물 정책 runtime·lease 연결·승인·shadow·장치 수용 | SIM 연동 확보, 실물 정책 실행 차단 |
| 주행: 인식 모델 + 기존 Drive | 영상·MCAP 수집, 검수, 학습·평가·registry·전달 경로, 모델 및 장치 진단 기록 | 현재 road-surface 목적의 승인 정답과 독립 평가, 최신 설치본의 성능·현장 수용 | 부분 연결, 품질·운영 수용 미완료 |
| 주행: 영상 → 속도 모방학습 | 실제 MCAP 기반 CNN/ridge 학습·재적재·공통 정책 산출물 | expert 의도 확인, 기준선 이상 성능, 실행 수용 | 연구 모델은 있으나 등록 거절 기록 |
| 주행: 시뮬레이션 강화학습 | Isaac native 환경에서 학습·고정 평가·9.342 m 경로 완주·정지 | 센서 기반 관측, Gazebo/Fleet 평가와의 구분, 기준선 대비 개선, 실물 이전 | 제한된 SIM 성과 확보 |

완료율을 백분율로 표시하지 않았다. 데이터 적합성, 모델 품질, 장치 실행은 서로 대체할 수 없는 조건이다.

## 2. 조사 범위와 근거의 읽는 법

- 현재 소스, 관련 시험 코드, ADR, 검증 기록을 읽었다. 제품 코드와 설정은 수정하지 않았다.
- `rosy-platform` 조사 시작 HEAD는 commit `a804896e58fbef93cd3ef98d210f175b367d9822`, `rosy-vault`는 `69a4d03`이었다. 공유 작업 공간의 스냅샷이며 운영 설치 버전과 동일하다고 가정하지 않았다.
- 이번 점검에서 pytest·GPU 학습·Gazebo를 새로 실행하거나 원격 호스트·실물 장치에 접속하지 않았다. 아래 성능·통과 수치는 해당 날짜의 보존 기록이다.
- CORE–LeRobot 검증 manifest의 원시 로그 **25/25개**, 후속 착지 manifest의 원시 로그 **30/30개**를 로컬 보존본과 SHA-256으로 대조해 모두 일치함을 확인했다. 이는 기록의 보존 무결성 확인이며 현재 HEAD의 재시험 결과가 아니다.
- `STATUS.md`는 모듈별 집계다. 오래된 HOLD 설명만으로 최근 부분 구현이 없다고 판단하지 않았으며, ADR의 Proposed 상태를 구현 완료나 승인 완료로 해석하지 않았다.

핵심 근거: [CORE 연동 검증](../validation/core-omx-lerobot-2026-10-18/result.md), [로그 manifest](../validation/core-omx-lerobot-2026-10-18/evidence/log-manifest.json), [착지 검증 기록](../validation/core-omx-deployment-2026-10-18/landing.md), [착지 로그 manifest](../validation/core-omx-deployment-2026-10-18/evidence/landing-logs.json).

## 3. 암 파이프라인

### 3.1 실제로 존재하는 두 실행 경로

현재 암은 실행 경로가 둘이다. 두 경로의 데이터 단위·권한·검증 범위를 섞으면 현황을 잘못 판단하게 된다.

**직접 실행 경로 — rosy-vault**

```text
카메라·팔 보정 → 배타 잠금 아래 LeRobot 녹화 → 외부 LeRobot 학습
→ checkpoint·processor → LeRobotPolicy → SafeDriver → 실물 드라이버
```

`tools/record.py`는 device-core와 같은 팔 잠금을 잡고 녹화 명령을 실행한다. `lerobot_policy.py`는 실제 LeRobot의 모델·전후처리기를 읽고, 관절 rad와 `omx_follower` 정규화 값 사이를 보정 파일로 변환한다. 정책 출력은 `policy.py`를 거쳐 SafeDriver에 전달된다. 카메라 준비 실패 시 시작을 거부하고 종료·오류 시 자원을 정리한다.

이 경로에는 ROSY Platform CORE의 SIM 제한을 그대로 적용하면 안 된다. 별도 직접 실행 구현이 있기 때문이다. 반대로 직접 실행 어댑터가 있다는 이유로 플랫폼의 실물 정책 실행까지 열렸다고 볼 수도 없다.

직접 경로의 녹화 래퍼는 외부 명령을 실행하는 도구다. 자체적으로 데이터 검수·학습·독립 평가·승격을 모두 조율하는 서비스가 완성된 것은 아니다. 첫 검증에서는 LeRobot 학습 명령과 산출물을 명시적으로 연결해야 한다.

근거: [녹화 래퍼](../../../../rosy-vault/tools/record.py) 13행, [실제 SDK 적재·추론](../../../../rosy-vault/device_core/backends/lerobot_policy.py) 151행, [안전 실행 루프](../../../../rosy-vault/device_core/backends/policy.py) 37행, [V-018](../../../../rosy-vault/docs/adr/V-018-LeRobot-정책-연결.md).

**플랫폼 경로 — rosy-platform**

```text
Pilot/teacher 시연 → episode·LeRobot export → ACT 학습
→ 별도 재적재·평가·정책 기록 → CORE 관측 → 정책 후보
→ CORE/session 검증 → OMX owner → ROS Action
```

CORE의 arm port는 선택적 연결이다. 기본 CORE에 자동 결선되지 않으며 HTTP로 모델 설치·lease 발급·재무장을 할 수 없다. 현재 연동은 SIM이며 한 대의 RGB, 일치하는 관절명·rad 단위, ACT `n_action_steps=1`과 temporal ensemble 없음이 지원 범위다. 실물 녹화의 정규화 값을 SIM rad 계약과 자동 혼용하지 않는다.

근거: [D-800](../adr/D-800-core-mediated-omx-lerobot.md) 15·35행, [CORE 연동 검증](../validation/core-omx-lerobot-2026-10-18/result.md) 16–27행, [native 학습 cycle](../../learning/training/omx/native_cycle.py).

### 3.2 단계별 현황

| 단계 | 확인한 현황 | 완료 판단의 한계 |
|---|---|---|
| 장치·카메라 준비 | 카메라 프로필·보정 Session·녹화 잠금 구현. 10/19 실제 카메라 밝기와 스트림 시작 시 설정 변화 등을 측정 | 통합한 도구/API는 가짜 카메라로 확인. 실제 보정 저장 → 감싼 녹화 전체 경로는 후속 확인 필요 |
| 시연·데이터 정리 | 플랫폼에 시연 수집·export·출처 검증·분리 도구 존재 | 직접 실행용 실물 시연 체크포인트는 V-018에서 없다고 명시. 과거 SIM·합성 자료를 실물 과제 시연으로 계산하지 않음 |
| 학습·재적재 | ACT trainer와 별도 모델·processor 재적재 경로 존재 | 코드가 평가 기능을 제공한다는 사실과 실제 과제 학습 모델의 품질 통과는 별개 |
| 품질 평가 | 오프라인 오차·기준선 비교·거절 원장 존재 | 기존 SIM ACT 실험은 기준선보다 나빠 거절. 직접 경로의 실물 성공률은 미확인 |
| 추론·명령 전달 | 직접 경로의 SDK CPU smoke, 플랫폼의 CORE → 실제 ROS Action 서버 검증 존재 | CPU smoke는 학습 안 된 모델, ROS 서버는 격리 시험 서버. 실물 폐루프 과제 성공 아님 |
| 실물 적용·피드백 | 안전 owner·정지·보정·승인 조건이 정의되고 일부 구현됨 | 직접 경로 KAN-61 과제 판정, 플랫폼 승인·live lease·장치 수용이 남음 |

### 3.3 확보한 실행 증거와 의미

1. **직접 경로 SDK 호환성:** 10/19 LeRobot 0.4.4의 학습 안 된 작은 ACT 체크포인트로 CPU 추론 루프를 실행했고 첫 추론 194 ms를 기록했다. 장치 없는 호환성 확인이다. 실제 모델의 지속 추론 지연이나 과제 성공률 수치는 아니다. [V-018 20행](../../../../rosy-vault/docs/adr/V-018-LeRobot-정책-연결.md)
2. **카메라 실측:** 통합 이전 동일 보정 규칙에서 녹화 프로그램이 본 평균 밝기 top 112.7/front 115.0을 기록했다. 목표는 120±8이었다. 카메라 재개방 시 값이 초기화되는 문제와 검은 프레임 정지도 관측했다. 카메라 측정 성공을 팔 정책 성공으로 확대하지 않는다. [V-019 36–50행](../../../../rosy-vault/docs/adr/V-019-카메라-보정-프로필.md)
3. **플랫폼 SDK·ROS 연결:** 10/18 집중 검증 22 passed/0 skipped. 실제 SDK recorder가 합성 프레임을 저장했고 별도 합성 3-episode 데이터로 ACT를 CPU 2 step 학습·재적재했다. 실제 ROS Action의 수락·완료·취소도 확인했다. 이 시험들을 하나의 실물 학습 과제 성공으로 합산할 수 없다. [검증 기록 37·52–61행](../validation/core-omx-lerobot-2026-10-18/result.md)
4. **기존 SIM 모델 품질:** 10/04 같은 12프레임 평가에서 ACT 400 step의 MAE는 0.009403 rad, 학습 target 상수 평균은 0.005990 rad였다. 오차는 40 step 대비 줄었지만 기준선을 넘지 못해 거절됐다. 현재 관절 유지 진단 기준선은 0.000705 rad였다. 이 작은 데이터에서는 오래 학습하는 것만으로 과제 정책이 좋아졌다고 말하기 어렵다. [학습 길이 비교 27–46행](../validation/act-training-length-study-2026-10-04.md)

### 3.4 암 완성을 막는 핵심

- **직접 경로의 실제 학습 산출물과 통합 실행:** V-018은 이 경로에서 실물 카메라·팔로 실행하지 않았으며 녹화·학습한 체크포인트가 없다고 명시한다. 이는 저장소의 모든 과거 연구 모델이 없다는 뜻이 아니다.
- **과제 성공 판정:** 직접 경로의 `SUCCEEDED`는 정해진 시간 동안 정책을 실행했다는 의미다. 파지·운반·배치 성공 판정은 KAN-61에 남아 있으며, 그전에는 앱 자동 호출에 정책 기술을 쓰지 않는다는 조건이 있다.
- **플랫폼의 실물 실행 연결:** `--target real` preflight는 현재 exit 3으로 거부한다. 실제 대상·정책 pin·owner 결선·live lease·승인·물리 수용을 갖춰야 한다. 패키지 빌드나 정책 registry 승격만으로 해소되지 않는다.
- **물리 보정과 실행 일치:** 녹화 이후 홈 오프셋을 다시 쓰거나 카메라·속도 조건이 달라지면 입력·출력 의미가 어긋난다. 보정 파일과 모델 버전을 함께 고정해야 한다.

근거: [V-018 23–29행](../../../../rosy-vault/docs/adr/V-018-LeRobot-정책-연결.md), [실물 활성화 잔여 조건 60–68행](../validation/core-omx-deployment-2026-10-18/result.md), [D-793의 단계별 승인 조건](../adr/D-793-omx-learned-policy-execution-approval-gate.md).

## 4. 주행 로봇 파이프라인

### 4.1 세 가지 학습을 구분해야 한다

**현재 인식 모델을 사용하는 주행 경로**는 다음과 같다. 모델이 차선·도로면을 추정하고 기존 Drive가 주행 후보를 만들며 CORE가 최종 명령을 집행한다. 영상에서 속도를 바로 내는 모방학습 정책과는 다른 경로다.

```text
영상·MCAP → 프레임·출처 정리 → 사람 검수 → dataset
→ 모델 학습 → 고정 평가 → registry/intake → shadow·설치
→ learned 관측 → Drive → CORE → 주행·실패 기록 → 다음 검수
```

검수·학습·평가·전달 코드는 연결되어 있다. 다만 모델 전달은 주행 활성화가 아니며, 자동 생성 라벨과 사람의 독립 정답도 구분된다. 실행 사건의 export·검수·registry 경로가 있어도 자동 실패 분류와 재훈련 전체가 완료됐다는 뜻은 아니다.

근거: [전체 실행 흐름 점검 24–27행](../plans/2026-10-15-runtime-pipeline-closure.md), [학습 모듈의 권한 경계](../../learning/AGENTS.md).

### 4.2 인식 학습: 데이터가 없는 것이 아니라 평가에 쓸 수 있는 조건이 부족하다

| 단계 | 확보한 것 | 남은 문제 |
|---|---|---|
| 수집·출처 | 실제 영상·MCAP, 원본과 파생 자료의 hash·출처 대조 기록 | 촬영 파일 수를 독립 세션 수로 계산하면 안 됨. 일부 출처·보정·capture group 미확정 |
| 사람 검수 | 기존 lane 승인 857장 및 v2 image/mask 2,769쌍 확인 기록 | 기존 lane/current-region 정답을 새 road-surface 정답으로 바꿔 부를 수 없음 |
| 학습 | 실제 GPU 학습, CNN 폭·recipe 비교, 모델 산출물 존재 | 기존 목적·자동 라벨에 맞춘 성능을 현재 도로면 품질로 일반화 불가 |
| 독립 평가 | 이미지 hash 중복 검사, 원본 영상까지 추적한 감사 기록 | 동일 이미지가 없어도 같은 원본 영상이 train/val/test에 걸쳐 존재. 독립 최종 시험으로 부적합한 자료 존재 |
| 접수·전달 | intake·registry·watch·delivery 경로 존재 | 과거 특정 모델 intake 통과는 최신 목적·장치·현장 수용과 별개 |
| runtime 사용 | 실제 장치 진단과 learned mask 소비 문제 수정 기록 존재 | 최신 설치본의 사용률·지연·위험 진행·과제 성공을 함께 재확인해야 함 |

10/15 점검은 2,769쌍과 lane 승인 857장을 확인했지만 현재 road-surface 목적의 독립 정답/IndexedReview 수용과는 다르다고 기록했다. 당시 검수 owner의 승인 mask는 0으로 HOLD였다. **기존 사람 작업을 없었던 것으로 볼 수 없고, 그 작업을 다른 의미의 정답으로 자동 승격할 수도 없다.** [점검 계획 105–109행](../plans/2026-10-15-runtime-pipeline-closure.md)

더 상세한 출처 감사에서는 v2 2,769장 중 2,519장이 upstream 원본 영상 hash에 연결됐고 250장은 연결되지 않았다. 연결된 원본 그룹 다섯 개가 둘 이상의 split에 걸쳐 있었다. MCAP 평가 후보 중 99프레임도 기존 학습 194장과 촬영 원본을 공유했다. 이 자료는 연구·개발 기준선으로 보존하되 독립 최종 평가로 사용하지 않는다는 결론이다. [기존 자료 재점검 65–77·108–116행](../validation/drivable-reviewed-desktop-2026-10-11.md)

### 4.3 모델 성능과 실제 사용 여부

10/04 recipe 비교에서는 개선 base16이 lane IoU 0.79448/mIoU 0.51486, 개선 base8이 lane IoU 0.76222/mIoU 0.50522로 당시 intake를 통과했다. 그러나 drivable IoU는 각각 0.00042/0.00241이었다. **차선 성능이 개선된 사실과 도로면 인식이 충분한지는 별개다.** CPU p95 51.22/18.91 ms 역시 당시 시험 환경의 값이며 Pinky 동시 부하 측정값으로 쓰지 않는다. [모델 비교 20–47행](../validation/perception-model-comparison-2026-10-04.md)

이때 base8의 실제 accepted 등록까지 확인되지만, 전달은 DNS 실패 또는 기존 push hold로 pending이었고 push 시도는 0이었다. 당시 watcher timer도 설치되지 않았다. 따라서 학습→접수의 실제 성과는 인정하되 상시 자동 학습→장치 교체 서비스가 운영 중이라고 판단하지 않는다. [accepted 모델·전달 기록 16–21·36–50행](../validation/model-store-accepted-2026-10-04.md)

10/09 장치 진단에서는 모델이 정상 적재됐지만 운영 관측 25/25건이 fallback이었다. 별도 worker 재현에서는 learned 0/fallback 50, 마지막 추론 지연 354.2 ms였다. 프레임 수명 약 250 ms보다 추론이 느려 결과를 사용하지 못하는 문제가 확인됐다. [live 진단](../validation/learned-paint-live-2026-10-09/result.md), [cadence 진단](../validation/learned-paint-cadence-2026-10-09/result.md)

이후 10/10 D-570 수정 기록은 ego-motion 보정 재사용을 도입해 **실물 정지 상태 100%, SIM 95–99%** 사용률을 기록한다. 따라서 10/09의 fallback 문제를 현재 미수정 상태라고 보고하면 안 된다. 동시에 정지 상태 사용률을 실제 주행의 정확도·안전성·완주율로 확대해서도 안 된다. 확인할 값은 모델 적재 여부뿐 아니라 `paint_source_used`, `paint_model_revision`, 지연·stale·fallback 사유다. [수정 학습 기록 23–44행](../solutions/logic-errors/learned-paint-frame-count-gate-drops-slow-masks-2026-10-10.md)

후속 SIM 기록은 learned 사용률 95% 이상을 확인하면서도 흰 벽 오검출·벽 옆 테이프 누락 문제를 남겼다. 또한 Gazebo의 **m29 연속 15바퀴 성공**은 일지 바로 다음 행에서 m20 이후 대체 인식을 사용했다고 명시한다. 해당 모델은 wall 역할이 없어 floor gate를 통과하지 못했다. 따라서 15바퀴는 그 제어 조건의 성과로 기록하고 학습 인식 모델의 수용 성과로 계산하지 않는다. [후속 모델 SIM 검증 47·79–85행](../validation/sim-model-lap-rosy26-2026-10-09/result.md), [Gazebo 일지 511–512행](../plans/2026-10-12-gazebo-lane-lap.md)

### 4.4 영상 → 속도 모방학습

`learning/training/pinky/comparison_job.py`는 실제 MCAP를 검증하고 학습·평가 세션을 나눠 상수 기준선, RGB ridge, 작은 CNN을 비교한다. 모델을 저장·다시 읽고 공통 PolicyArtifact와 평가·거절 이력을 남기는 경로도 있다.

10/04 기록에서 CNN과 ridge 모두 expert intent 미확인, 선속도 기준선 미달, 각속도 기준선 미달로 거절됐다. 따라서 ‘Pinky를 데이터로 학습시키는 기능’은 존재하지만 ‘채택 가능한 학습 주행 정책 확보’까지 도달한 것은 아니다. stale/HOLD 집행·독립 SIM 과제·Fleet 연결·카메라 보정·장치/현장 수용도 해당 연구 기록에서 미완료다.

근거: [비교 job 안내](../../learning/training/pinky/README.md), [정책 산출물·거절 기록 37–61행](../validation/pinky-policy-artifact-2026-10-04.md).

### 4.5 강화학습·시뮬레이션

Isaac native 실험에서는 기존 PathFollower의 yaw gain을 tabular Q-learning이 선택했고, 고정 정책으로 9.342 m의 ordered 경로와 네 시작 방향 평가를 완료했다. 실제 SDK의 시뮬레이션 속도·정지 유지까지 확인했으며 종료 수정 뒤 재학습·재평가도 실행했다.

다만 관측은 카메라·ROS localization이 아닌 **시뮬레이터의 native pose/속도와 고정 경로 정보**다. 카메라는 녹화 용도였다. 기존 기준선도 완주했으므로 강화학습의 성능 개선을 수용한 결과는 아니다. 여기서 말하는 정지는 시뮬레이션 물체의 정지이며 실제 Pinky의 물리 정지 시험이 아니다. ROS/Fleet·Isaac Lab·다중 로봇/신호·실물 수용은 별도다. [Isaac 검증 18–31·39–68행](../validation/isaac-map-rl-2026-10-11/result.md)

최근 Gazebo 경로도 별도로 진행 중이다. D-769의 10/18 개정에는 지도 bridge·제자리 재관측·차로 선택 보정과 기존 안전 검토가 기록돼 있다. 이는 주행 제어 개선이며 그 자체로 강화학습의 추가 효과나 실물 수용 증거가 되지 않는다. 지도와 실제 테이프의 오차, CORE/Fleet 배포 순서 같은 조건도 남아 있다. [D-769 131–160행](../adr/D-769-drivable-rl-gazebo-validation.md)

10/19 커밋 `8274be02f9`의 r21–r40 수정과 장소별 시나리오 추가도 확인했다. 검토한 공개 검증 자료에서는 r40 최종 성공 수치를 확인하지 못했으므로, 최신 코드 반영과 최종 완주 수용을 구분했다.

## 5. 완성까지 필요한 작업 순서

아래는 이번 조사에 따른 작업 제안이다. 새 실행·배포·승인을 수행했다는 뜻은 아니다.

| 우선순위 | 작업 | 끝났다고 판단할 산출물 |
|---|---|---|
| P0 공통 | 암의 첫 실물 검증 경로를 직접 device-core 또는 CORE/Fleet 중 명시하고, 주행의 첫 목표를 인식+Drive/속도 정책/RL 중 구분 | 대상 장치·과제·경로·모델·데이터 버전을 고정한 검증표 |
| P0 암 | 실제 보정 Session → 배타 녹화 → 과제 시연을 연결하고, 별도 episode로 평가 데이터를 예약 | 원본 시연, 카메라·관절·보정·task 계보, 학습/평가 분리와 검수 기록 |
| P0 주행 | 현재 road-surface/차선/경계의 정답 의미를 고정하고 원본 촬영 단위로 최종 평가를 분리 | 승인 정답, 검수자·출처 결속, 학습 제외된 독립 평가 manifest |
| P1 암 | 실제 시연 학습 → 별도 모델·processor 재적재 → 기준선 비교 | 고정 checkpoint hash, 독립 episode 오차·위험 출력·추론 지연 보고서 |
| P1 주행 | 기존 모델을 독립 평가로 비교하고 최신 장치에서 실제 소비를 측정 | 클래스별 품질, 모델 revision, learned 사용률·fallback·동시 부하 p95/p99 |
| P1 암 실행 | 선택한 경로의 정지·한계·권한 조건 아래 짧은 과제 실행과 성공 판정을 연결 | 실물 정지 기록, 독립 파지/배치 결과, 성공·실패·중단 횟수. 시간 만료 성공과 분리 |
| P1 주행 실행 | 같은 인식 모델에서 기존 제어와 학습 정책을 분리 비교 | 완주·이탈·충돌·정상 대기·정지·회복 결과와 실제 적용 행동 기록 |
| P2 공통 | 실패 기록을 원본 관측과 묶어 검수로 되돌리고 다음 버전 재학습·회귀를 반복 | 실패→검수→새 dataset→새 모델→독립 평가→적용→rollback의 한 회전 기록 |

암 직접 경로는 KAN-30·KAN-61의 기존 조건을 따른다. 플랫폼 실물 정책 경로를 선택하면 D-793의 shadow·단계별 승인·lease 조건을 별도로 충족해야 한다. 주행 RL의 개선을 검증할 때는 인식 모델까지 동시에 바꿔 개선 원인을 섞지 않는 D-769의 비교 조건을 따른다.

## 6. 완료 보고에 필요한 최소 증거

암과 주행 각각에 다음 여섯 묶음이 같은 버전 계보로 연결돼야 ‘학습 파이프라인 완성’이라고 보고할 수 있다.

1. **수집:** 실제 과제의 원본 영상·상태·행동과 카메라/장치 보정·시각·출처.
2. **데이터:** 목적에 맞는 검수 정답, 촬영/episode 단위 분리, 독립 평가 예약.
3. **학습:** 실행 설정·코드 SHA·dataset manifest·고정 모델과 processor hash.
4. **평가:** 별도 재적재, 독립 정답과 기준선 비교, 한계·실패·지연을 포함한 결과.
5. **실행:** 실제 설치 모델 확인, 최종 owner·권한·정지 조건, 실제 사용과 과제 결과.
6. **반복:** 실패의 원본 결속, 다음 버전 개선, 회귀·rollback 확인.

현재는 이 묶음들의 일부가 여러 실험과 경로에 나뉘어 확보되어 있다. 다음 검증은 **암 하나의 구체적 과제와 주행 하나의 고정 코스에 대해 같은 계보로 끝까지 연결하는 것**을 완료 단위로 잡는 것이 적절하다.

## 7. 조사 한계

원격 데이터 전체·현재 호스트 가용성·현재 설치 모델·실물 팔과 Pinky의 상태는 새로 측정하지 않았다. 기존 기록의 장치 진단·학습 성과와 이번 소스 점검을 구분했다. 특히 10/19 실제 카메라 관측이 있어 과거 ‘카메라 미연결’ 기록을 오늘의 상태로 단정하지 않았고, 과거 fallback 장애에도 후속 수정을 반영했다.

독립 정답 부족을 데이터 자체의 부재로, 코드 연결을 실물 과제 성공으로 해석하면 남은 작업을 잘못 잡게 된다. 이번 보고서의 주요 미완료 항목은 이 두 구분을 기준으로 정리했다.

## 8. 후속 실행 결과 — 2026-10-19

사용자의 후속 처리 요청에 따라 암은 직접 LeRobot → device-core 녹화 경로, 주행은 인식 학습의 사람 검수 준비 경로부터 보완했다. 아래는 처음 조사 이후 실제로 수행한 변경이며, 앞 절의 실물 미검증 상태를 해제하지 않는다.

### 암: 녹화 진입점 연결과 종료 복구 수정

- `tools/record.py`가 기기 설정의 `workcell`·`lock_path`를 읽고 같은 PC의 ROSY owner 충돌을 거부하도록 수정했다. 이전에는 기본 잠금만 사용해 설정된 별도 잠금이 잡힌 상태에서도 child 녹화를 시작할 수 있었다. 실제 subprocess 회귀에서 수정 전 실패를 확인했다.
- 같은 잠금 안에서 기존 `device_tune.py session`을 호출하도록 연결했다. 카메라 준비 실패 시 녹화를 시작하지 않으며, 녹화 명령의 인자·종료 코드를 보존한다. 별도 보정 구현은 만들지 않았다.
- 독립 코드 검토에서 감시 스레드의 종료 경합을 발견했다. 녹화 시작 실패 뒤 카메라 서비스를 복구하면 남아 있던 감시가 이를 녹화 프로그램으로 오인해 복구된 값을 다시 쓸 수 있었다. 이를 재현하고 공용 `Session`에서 감시 취소·회수 후 카메라 복구·서비스 재시작 순서로 수정했다.
- 최종 전체 시험: **235 passed / 4 skipped / 1 warning**. 건너뛴 네 건은 `ROSY_PLATFORM_DIR` 미설정으로 실행하지 않은 진짜 Fleet 통합 시험이다. 경고는 기존 Starlette/AnyIO deprecation이다. 수정 후 독립 재검토에서 추가 중요 지적은 없었다.
- 저장소: `rosy-vault`, 브랜치 `fix/learning-recording-pipeline`, 커밋 commit `63af65695f1bee71eb4988decd2ee0af1d40d5d7`.
- 작업 공간: `C:/Users/SERIGGG/AppData/Local/Temp/rosy-learning-closure/vault`. 공유 main 병합·push·실물 실행은 수행하지 않았다.

새 녹화 진입점은 운영자가 수용 조건을 갖춘 장치 PC에서 다음 형태로 사용한다. 이 점검에서는 녹화 명령을 실제 장치에 실행하지 않았다.

```text
python tools/record.py <workcell> --config <device.yaml> --calibration <calibration.yaml> --report <new-recording-dir> -- lerobot-record --config_path=<record-config.json>
```

### 주행: AI 검수 보조의 정답 의미·최신성 결속

- 기존 AI 의견 프롬프트는 차선 안쪽 구역을 기준으로 한다. 배치 CLI와 직접 worker가 이를 전체 도로면(`road_surface/1`)에도 적용할 수 있는 빈틈을 수정했다. 지원하지 않는 의미는 모델을 호출하기 전에 거부하며 기존 도로면 검수 보조 제한을 유지한다.
- 실제 클래스 내용·선언된 의미·클래스 출처 hash·프롬프트와 출력 형식의 hash를 의견 보고서에 묶었다. 이미지·마스크가 같아도 이 의미가 바뀌면 이전 의견을 최신으로 사용하지 않는다. 기존 보고서와 사람 라벨·승인은 보존한다.
- 독립 검토가 표시용 기본 이름과 저장된 원본 클래스 사이의 hash 불일치를 찾아냈다. 원본 클래스로 통일하고, 표시 이름을 생략한 기존/명시적 current-region 클래스 각각의 비동기 발행→읽기 회귀를 추가했다.
- 최종 집중·HTTP·실제 Chromium 브라우저 시험: 커밋 commit `935c7b841c88925c30b8f419e85dd779d6ce2fa8`, **55 passed / 0 skipped**, runner exit 0, known_failures NEW 0.
- 같은 최종 커밋의 전체 영향 범위 perception·저장소 guard 회귀: AI 역할의 원격 시험 PC에서 **2,256 passed / 62 skipped / 36 warnings**, 733.05초, runner exit 0, known_failures exit 0(NEW/known/flaky 모두 0). 두 실행 모두 실제 Chromium opt-in을 켰으며 순차 실행했다. 최종 독립 검토에서 추가 중요 지적은 없었다.
- 건너뛴 62건은 미검증이다. 실행기가 뒤에 붙인 `-rfE`로 요청한 `-rs`가 덮여 개별 skip 사유가 원시 로그에 남지 않았다. 소스의 선택적 의존성 조건을 실제 62건의 사유로 추정해 집계하지 않았다. 직접 변경한 집중·HTTP·브라우저 55건은 모두 실행됐다.
- 브라우저 시험 한 건은 변경 전 기준 commit `a27b980c7cb780b042ba6a85b5e541d9e533d823`에서도 동일하게 실패했다. 제품이 요구하는 클래스 선택을 시험이 생략한 것이어서 UI의 기존 클래스 선택 한 단계를 추가했다. 미저장 제스처·AI 차단·결과 재적재 검사는 유지했으며 독립 검토에서 확인했다.
- 작업 공간: `D:/Dev/Robot/Rosy/rosy-platform/.worktrees/learning-review-semantics`, 브랜치 `fix/learning-review-semantics`. main 병합·push·운영 모델 호출·장치 활성화는 수행하지 않았다. 시험의 모델 응답은 대역이다.

최종 원격 원시 로그와 실제 호출 인자·runner 결과·기존 실패 비교는 `C:/Users/SERIGGG/AppData/Local/Temp/rosy-learning-closure/mobile/`에 보존했다. 각 실행 폴더의 `runner.txt`, `run-1.txt`, `known-failures.txt`를 함께 본다. 아래 두 원시 로그의 SHA-256과 성공 요약·비교 결과를 보고서 작성자가 다시 읽어 확인했다. 수정 전 실패·기준 커밋의 브라우저 실패·중단한 중간 회귀도 보존하며 최종 통과에 합산하지 않았다.

| 최종 SHA의 원시 로그 | SHA-256 |
|---|---|
| `final-browser/run-1.txt` | `72987279908e6b8b5302cc0210631f33b3e13aba657c62408a52b2c90de793c1` |
| `affected-serial/run-1.txt` | `e6dff3e24e803cabcf94e40088f4d9d438e02d38b45486d2f0c8d40c1a073958` |

### 실제 학습에 남아 있는 입력

로컬 `data/teleop/learning`에서 기존 MP4 **22개, 195,789,572바이트**를 다시 확인했다. 두 전달 manifest의 SHA-256도 계산했다. 그 기록은 사람 라벨 승인과 학습 시작을 모두 false로 선언하며, 하나는 모델 PC의 원본 보관 완료 false, 다른 하나는 촬영/수집 그룹 UNKNOWN을 선언한다. 영상 자체가 없다는 뜻이 아니다. 현재 `data/perception/raw`의 일반 디렉터리를 심볼릭 링크를 따라가지 않고 탐색한 범위에서는 `.mcap`/`metadata.yaml` 원본 파일을 찾지 못했다.

후속 작업에서는 기존 설정의 모델·AI PC 두 후보에 SSH 읽기 전용 조회도 수행했다. 첫 후보의 `~/rosy-ml`에서 검수 상태와 이미 실행 중인 검수 앱의 state 인자를 찾아, 아래 다섯 SQLite를 `mode=ro`로 열고 각 읽기 트랜잭션 안에서 상태를 집계했다. 직접 앱 기동·DB 마이그레이션·라벨 변경·모델 호출·로봇 접속은 하지 않았다. 두 번째 후보에는 조회한 학습 루트가 없었다. 전체 PC·디스크를 탐색한 결과는 아니다.

| 모델 PC `~/rosy-ml` 아래 작업 공간 | frames 수 | 프레임별 최신 mask 상태 | 승인 mask |
|---|---:|---|---:|
| `review-v13-drivable/eval-20261008T163945Z` | 8 | pending 8 | 0 |
| `review-v13-drivable/state` | 53 | pending 30 / excluded 23 | 0 |
| `vision-review/state` | 38 | pending 18 | 0 |
| `edge-capture/review-state` | 63 | pending 43 | 0 |
| `review-v12-vision-obstacle/state` | 43 | pending 43 | 0 |

다섯 DB 중 네 곳에는 drivable 역할이 있었으나 의미 선언은 없었고, obstacle 작업 공간에는 그 역할이 없었다. 이미 실행 중인 검수 앱 네 개의 state 위치도 확인했지만 화면 렌더와 원본 이미지 적재는 이번에 검사하지 않았다. 이 조회는 현재 미승인 상태를 확인한 것이며 원본 hash·독립성·현 목적 적합성의 재수용은 아니다. 기존 검수 작업 공간은 실제로 존재하므로 위치가 전혀 없다고 판단하지 않는다. 사람 검수를 이어갈 후보로 보존한다.

따라서 실제 학습·독립 평가를 이어가려면 **암의 실제 시연 dataset과 과제·보정 revision**, **주행의 검증된 MCAP 원본·촬영 그룹·사람 검수 상태 또는 일관된 작업 공간 사본**이 필요하다. 기존 영상으로 검수 후보를 만들 수는 있지만 출처와 사람 승인을 합성해 독립 정답으로 인정하지 않는다. 해당 입력이 확보되면 기존 `native_review.py`→`native_cycle.py`, 주행 `review_eval_bootstrap.py`→검수→`review_pipeline.py` 경로를 사용한다.

이번 변경은 두 파이프라인의 구체적인 소프트웨어 연결과 오류를 보완한 것이다. 실제 데이터 학습·장치 배포·실물 과제 성공·현장 수용은 아직 완료되지 않았다.
