## D-578 차선 인식 실패는 AI PC 사실과 Claude 검토를 규칙으로 합쳐 원인을 가르고, 모델 놓침만 라벨 후보가 된다

**Status:** Proposed (2026-10-09, 사용자 지시 "AI PC와 너가 함께 고민하고 처리하도록 구현해"로 구현; 같은 종류의 D-492·D-575·D-577처럼 운영 수용 전에는 Proposed다; 범위는 오프라인 학습 쪽 실패 분석 루프이고 실시간 stuck 처리는 Fleet 세션 몫이다. SOURCE와 모델 PC 실행은 `feat/lane-failure-analysis-loop`, AI PC VLM 설치는 소유자 동의 대기).

### Context

2026-10-09 9dfk 녹화 `20261009T130633Z_rosy_41`(10.6 s, CAMERA_LINE HOLD `camera_line_not_visible`, keep_debug `strategy none`, `reason no_boundary`, paint `learned`)을 손으로 진단했다. 로봇은 차로에 직각으로 경기장 벽을 약 15 cm 앞에서 보고 있었고 화면에는 벽 앞 바깥 경계선 하나만 가로로 보였다. 모델 `lane-seg-20261006-28e8454d`는 벽 65 %, 바닥 28 %, 차선 6.6 %로 맞게 나눴고 keeper의 `no_boundary`도 맞았다. 원인은 자세였고 모델 놓침이 아니었다. 이런 프레임을 학습 자료에 넣으면 모델을 틀리게 가르친다.

판정자에 대한 이전 교훈: VLM에게 결정을 물으면 47건 모두 같은 답(BACK_AND_RETRY 0.95)을 냈고, 바닥에 무엇이 있느냐고 물으면 0.24 m 앞 벽을 "없음"이라 했다(D-492 V0). Qwen3-VL 8B는 망가뜨린 겹쳐 그리기 17장을 모두 통과시켰다(D-554 2항). 숨긴 카나리아를 섞은 시트를 Claude 하위 에이전트가 검토했을 때는 181개 중 171개를 잡았다. 역할은 D-492·D-503·D-516·D-527을 따른다: 모델 PC는 자료·평가·학습, AI PC는 고정 버전 추론만, 결정은 규칙과 사람.

### Decision

1. **사건을 녹화에서 고른다.** 모델 PC가 로봇의 파일럿 녹화를 받아(로봇은 읽기만) keep_debug가 `strategy none`이고 `reason`이 `no_boundary`·`washed`인 연속 프레임을 사건으로 묶는다. `junction_fork` 같은 의도된 정지는 사건이 아니다. 사건마다 처음·중간·끝 프레임을 뽑는다.
2. **사실은 출처와 함께 남긴다.** 프레임마다 (a) 센서: LiDAR 정면 최근접 거리(로봇 전방축은 승인된 `lidar_mount` 기록, 없으면 URDF 180°), 오돔 이동·회전, keep_debug의 strategy·reason·paint 출처·경계·가로선(transverse) 수, 노출 통계, 카메라 보정 활성 여부; (b) 모델: 그 녹화에서 로봇이 쓴 모델 revision(keep_debug `paint_model_revision`, 학습 paint가 아니었으면 운영자가 준 그 로봇의 shadow revision과 그 사실)을 로봇과 같은 전처리로 다시 돌린 클래스 비율, 근거리 차선 비율, 차선 성분의 화면 방향(along/across); (c) VLM: 고정 질문 하나(선이 화면을 따라가는지·가로지르는지, 선 개수, 가까운 벽, 도로 위인지)에 대한 사실만, 모델 이름·digest·프롬프트 해시·엔드포인트와 함께. VLM에게 원인이나 행동을 묻지 않는다. 천장 카메라 자세는 시각이 맞는 기록이 있을 때만 붙인다.
3. **원인 분류는 여섯 가지다.** `model_miss`(차선이 보이는데 모델이 표시하지 않음), `pose_off_lane`(로봇이 차로를 따라 서 있지 않음: 가로질러 서거나 벽 앞), `keeper_logic`(모델은 선을 따라 표시했는데 keep이 잃음), `geometry_calibration`(선은 맞는데 투영·보정이 의심됨), `camera_exposure`(영상으로 바닥을 볼 수 없음), `ok`(실제 손실 아님).
4. **Claude가 검토하고 카나리아로 검증한다.** 사건마다 원본 | 모델 겹쳐 그리기 | 사실 패널로 된 시트를 만들고, 원인을 아는 숨긴 카나리아 타일을 섞는다. 카나리아는 손으로 판정한 창(첫 사례: 9dfk 벽 사례를 `pose_off_lane`)과, 두 경계를 잡은 구간에서 만든 합성(노출 망가뜨림→`camera_exposure`, 차선 마스크 지움→`model_miss`, keep만 잃게 바꿈→`keeper_logic`, 그대로→`ok`)이다. 검토자는 시트 폴더만 받고 키를 보지 못한다. 카나리아는 `max(4, 실제 타일의 25 %)`개 이상이어야 하고 정답률이 0.8 미만이면 그 묶음의 판정 전체를 거절한다. 거절 출력은 개수와 비율만 보이고 어느 타일을 틀렸는지는 검토자에게 주지 않는 파일에만 남긴다. 거절된 실행은 다시 들이지 않으며, 새 `collect`(새 시드·새 카나리아)로만 다시 검토한다. 실행 기록에는 카나리아 은행의 해시와 항목 수만 남긴다. 검토자 이름, 판정 파일과 지시문 해시를 남긴다. 이 판정은 사람 승인이 아니다.
5. **최종 원인은 감사 가능한 규칙으로 정한다.** 검토자의 원인은 사실이 그 원인을 뒷받침할 때만 최종이 된다(`lane_failure.SUPPORT`). 예: `pose_off_lane`은 가로선이 보이거나(모델 방향 across, keep transverse만 있음, 또는 VLM across) LiDAR 정면이 0.30 m 안이고 VLM이 선을 따라 보지 않을 때; `model_miss`는 모델이 근거리에서 선을 따라 표시하지 않았고, VLM이 선 없음을 확언하지 않았고, 노출이 정상이고, 가까운 벽+가로선이 아닐 때. 확신도 0.6 미만, 판정 없음, 사실과 어긋남은 사람 대기열로 간다.
6. **경로를 나눈다.** 최종 `model_miss`의 프레임만 라벨 후보가 된다. 후보는 `review_ingest`가 읽는 `verified-inputs.jsonl`(원본 세션, MCAP 해시, 카메라 프레임 순번, 이미지 해시, `annotation_source lane_failure_loop`)이고 초안 마스크 없이 사람 검수 대기로 들어간다(D-379·D-475·D-464의 승인 규칙은 그대로). `pose_off_lane`은 stuck 경로 인계 파일로, `keeper_logic`·`geometry_calibration`·`camera_exposure`는 인식 문제 목록으로 간다. 어느 것도 학습 자료에 자동으로 들어가지 않는다.
7. **AI PC는 고정 버전 추론만 한다.** VLM은 같은 인터페이스(Ollama 호환 엔드포인트, 또는 모든 답이 `unsure`인 대체 백엔드) 뒤에 둔다. AI PC에 VLM을 설치하거나 GPU를 쓰는 일은 그 PC 소유자의 동의를 받은 뒤에만 한다. 동의 전에는 모델 PC의 이미 설치된 고정 모델이나 대체 백엔드를 쓰고 그 엔드포인트를 결과에 적는다.

### Rejected

- VLM에게 원인을 묻기: 결정 질문에 상수 답을 냈다(D-492 V0).
- VLM을 겹쳐 그리기 품질 판정자로 쓰기: 망가뜨린 17장을 모두 통과시켰다(D-554).
- 실패 위치가 같다는 이유만으로 모델 문제로 보기, 실패 프레임을 모두 학습 후보로 넣기: 9dfk 벽 사례처럼 모델이 맞은 프레임이 틀린 라벨이 된다.
- 검토자 판정을 규칙 없이 그대로 쓰기: 카나리아로 검토 품질은 재지만 사건별 오판은 사실 대조로만 걸러진다.

### Consequences and verification

분류는 오프라인이며 로봇 동작을 바꾸지 않는다. 호스트 시험이 사실 계산, 규칙, 카나리아 거절, 후보·인계 파일 형식을 확인하고, 모델 PC 실행 기록이 9dfk 벽 사례가 `pose_off_lane`으로 끝나 라벨 후보가 되지 않음을 보인다. 라벨 후보의 사람 검수, 재학습, 고정 평가(D-475)는 각각 따로 증거를 남긴다. 실패 분류 결과는 주행 수용이 아니다.

**Related:** [D-492](D-492-d438-vision-tier-local-qwen-ai-pc-gated.md), [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-379](D-379-learning-data-pipeline-auto-labels-local-store.md), [D-459](D-459-pinky-persistent-label-review-application.md), [D-567](D-567-fleet-plan-parallel-lane-correction.md).
