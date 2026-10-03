## D-427 ROSY Platform은 middleware·operations·learning 세 파트와 공용 contracts·integrations로 최상위를 나눈다

**Status:** Accepted (2026-10-03, 사용자 승인 — "B 목표 + C로 시작"). 구조·의존 규칙의 수용이며 코드 이전·패키지 개명·설치 변경·실기 gate 변화는 없다. 이번 변경은 문서뿐이다.

**부분 보강 (2026-10-03, D-429 Accepted):** [D-429](D-429-five-concerns-control-port-and-site-devices.md)가 §1·§2를 보강하고 §3을 확장한다. integrations는 소유 모듈의 `api`까지 import할 수 있고, 사이트 장치(신호등·도크 펌웨어와 owner)는 middleware가 아니라 `operations/site_devices`에 둔다. §3 표는 층별 판단 표로 넓히고, `fleet/ai`는 `rosy.decision`으로 개명한다(D-231 유일 예외). middleware의 로봇 정의, 세 파트, 이전 순서는 유지한다.

**이전 동결 (2026-10-03):** 수용 시점부터 D-413 §1의 최상위 `modules/`, D-425 §4의 최상위 `apps/`·`ui/`로 **새** 소스 이전을 시작하지 않는다. 이미 그 경로에 있는 파일(main 기준 49개)과 진행 중 브랜치는 착지 후 §6 B 순서에 맞춰 D-427 경로로 옮긴다. 새 이전은 §2 import 규칙 시험(후속 1)이 main에 들어온 뒤 시작한다.

**이행 기록 (2026-10-04):** 아래 "이행 기록" 절 참조.

### Context

사용자는 저장소가 "다 몰려 있어서 구조가 보이지 않는다"고 했다. 또 플랫폼이 로봇 자체의 미들웨어에서 학습(모방학습·강화학습)까지 가는 범용 구조여야 한다고 요청했다. 두 세션(ros-e1, ros-d2)이 D-290·D-399·D-413·D-425, 아키텍처 문서 00·10·11·12, `docs/reference/ROSY_Platform_Architecture_Design_v0.2.md`와 현재 코드를 대조했다.

- 분류 체계가 세 겹이다. 옛 `src/{contracts,runtime,products,drivers,site,hmi,sim}`, D-413의 `modules/integrations/apps/profiles`, D-425의 `apps/site`·`apps/device`·`ui/`가 함께 있다. main `c8373fb9c` 기준으로 새 루트(`git ls-files modules apps integrations profiles`)는 49파일, `src/`는 2,153파일이다. 이전은 약 2% 진행됐다.
- 이름이 실제 책임과 어긋난다. `src/runtime`(994파일)은 거의 전부 Pinky 장치 코드다. `runtime/gateway`는 Pinky CORE이고 `apps/gateway`는 Fleet이다. Fleet 이미지가 `src/runtime/sensing/map/map_v2_fleet/`의 자산을 복사한다.
- 비전 문서(00 §8)는 device middleware → distributed runtime → Physical AI platform을 전략으로 둔다. 문서 12는 Teach → Record → Train → Deploy → Execute → Evaluate 고리를 둔다. 그런데 학습 관련 파일 약 150개가 `tools/perception/{dataset,model,training,store}`, `data/teleop`, `src/sim/isaac_sim`, `src/products/omx/adapter/{demonstration,lerobot_export}.py`, Pilot 녹화에 흩어져 있다. 녹화 형식도 셋이다(`rosy.recording.session/1`, D-411 Pilot 녹화, `rosy.omx-demonstration.v1`).
- 없는 것: PolicyArtifact·DatasetManifest 타입, 정책 registry와 승격 게이트(인식 intake는 shadow에서 끝남, D-373), 엔벌로프 스킬(D-399 후속 1), 강화학습 env·reward, OMX·Pinky 행동 정책 학습.
- D-209 §4(Accepted)는 "`src/vla`와 `learning/` 패키지는 만들지 않는다"고 정했다. D-186(Accepted)·D-207(Proposed)도 "학습 패키지를 `src/`에 만들지 않는다"고 한다. 반면 D-413 §1은 modules가 학습의 데이터·규칙을 소유한다고 했고, v0.2 §2.1은 `modules/learning`을 둔다. 두 줄은 이미 긴장 관계였다.
- 외부 사실(2026-10-03 조사): LeRobot 최신 v0.6.1은 Python 3.12+·PyTorch 2.7+가 필요하다. 데이터셋은 LeRobotDataset v3.0이고, HIL-SERL(SAC, 사람 개입, 보상 분류기)로 실물 RL을 지원한다. ROS 2 공식 브리지는 없다(huggingface/lerobot RFC #4368 open). 학습 정책을 안전 기능으로 인정하는 표준 근거는 찾지 못했다.

### Decision

#### 1. 플랫폼의 세 가지 일을 최상위 파트로 세운다

| 파트 | 한 줄 정의 | 소유 |
|---|---|---|
| `middleware/` | 어떤 로봇이든 같은 계약으로 안전하게 움직인다 | 명령 파이프라인(Action Gateway → Arbiter → Safety Guard → Motion Executor → 단일 writer), `execution/local`, skills, 장치 위 인식 백엔드, 녹화기, 장치별 owner 조합, 로봇 화면·Pilot·얼굴, drivers, firmware |
| `operations/` | 여러 로봇·셀을 하나의 작업으로 묶는다 | Fleet 원장·admission·dispatch(`execution/site`), world, processes, vision, decision(숙고형 추론), 사이트 실행 조합, Console·Cam |
| `learning/` | 경험에서 배운다 | 수집 대상 추출, 데이터셋, sim·real 공통 env와 reward, 학습(인식·모방·강화), 평가, 승격 증거 기록, 학습·평가 worker |

공용층은 셋이다.

- `contracts/`: 파트 경계를 넘는 wire·산출물 형식만 둔다. 대상은 ROS IDL, 공유 wire schema, Device Action API wire, Episode, DatasetManifest, PolicyArtifact, ModelProfile, VerifierArtifact, Skill envelope spec이다. 모듈 내부 API(`world.api`·`skills.api`·`execution.api`)는 D-413 §3대로 소유 모듈에 남는다. ModelToolCall/Result는 D-392 §6대로 Fleet 내부 계약이므로 `operations/decision`에 둔다.
- `integrations/`: 외부 기술 연결이다. D-413 §4의 `integrations/robots/<model>`을 유지하고 `models/<provider>`, `policies/lerobot_inference`, `policies/lerobot_training`, `simulation/{gazebo,isaac}`, `storage/`를 둔다.
- `shared/web/`: D-425 §3·§4의 공용 UI 키트다. 두 파트의 화면이 함께 쓰므로 파트 밖에 둔다.

`profiles/`(설치 고정), `deploy/`, `tools/`, `test/`, `docs/`는 최상위에 남는다.

목표 트리:

```text
contracts/  integrations/  shared/web/
middleware/   core/ skills/ perception/ recorder/ apps/device/{pinky,omx,sim} ui/{robot,pilot,face} drivers/ firmware/
operations/   fleet/ world/ processes/ vision/ decision/ apps/{fleet,vision} ui/{console,cam}
learning/     curation/ datasets/ envs/ training/ evaluation/ registry/ apps/{worker,cli}
profiles/  deploy/  tools/  test/  docs/
```

트리는 책임 예시다. 비어 있는 미래 폴더를 만들라는 목록이 아니다.

#### 2. 의존 방향을 구조 시험으로 강제한다

| 소비자 | 허용 import | 금지 |
|---|---|---|
| contracts | 외부 런타임 의존 없음(ROS IDL·스키마 생성 도구 제외) | 모든 파트·integrations |
| integrations/* | contracts | 모든 파트, 다른 어댑터 |
| shared/web | contracts | 모든 파트 |
| middleware | contracts, shared/web(ui만), integrations/{robots, policies/lerobot_inference, simulation(sim owner만)} | operations, learning, integrations/models, lerobot_training |
| operations | contracts, shared/web(ui만), integrations/{models, storage(원장 export)} | middleware(HTTP/WSS API로만), learning |
| learning | contracts, integrations/{models(오프라인), policies/lerobot_training, simulation, storage} | middleware, operations |

산출물은 코드 import 없이 흐른다.

- middleware → learning: Episode(녹화기), shadow 비교 기록.
- operations → learning: Fleet 원장 export(Mission/Step/Action/attempt/proposal 상관 기록).
- learning → 나머지: `profiles/`와 release lock으로 고정된 PolicyArtifact·ModelProfile·VerifierArtifact만. `learning/registry`는 증거와 승격 판정 기록이며 런타임이 조회하는 서버가 아니다.

LeRobot 연결은 추론과 학습으로 나눈다. 장치 설치에 학습 프레임워크가 따라오지 않게 하기 위해서다(v0.2 §9.2, D-356: 장치는 onnxruntime만). 안정 경계는 `PreTrainedPolicy.select_action`과 우리 PolicyArtifact다. 커뮤니티 ROS 2 브리지는 권한 경로로 쓰지 않는다.

#### 3. 숙고형 추론(VLM·ER2)은 별도 파트가 아니라 operations/decision이다

ER2·VLM은 Fleet의 옆 소비자다(D-326 §2). 움직임·그리퍼·Action 제출·취소·정지 도구는 없다(D-392 §4). 최상위 파트로 만들면 D-399 §1이 걷어낸 "단일 AI Runtime 상자"가 되살아난다. 그림에서 맨 위 Decision 띠로 그려도 내려가는 화살표는 Fleet admission 하나다. learning으로는 데이터·평가 화살표만 있다.

| 종류 | 예 | 자리 | 출력 |
|---|---|---|---|
| 숙고형 | Gemini ER2, VLM, (현재) VLA | operations/decision | Mission·Task 제안 |
| 반응형 | ACT, Diffusion, RL 정책 | middleware/skills (엔벌로프 스킬) | 엔벌로프 안 Motion Intent |
| 판정기 | 성공 분류기, VLM 심판 | 산출·평가는 learning, 등록(D-332) 후 온라인 GOAL_CONFIRMED는 operations(D-328 §4) | 성공/실패 증거 |
| 인식 | LaneUNet, YOLO | middleware/perception | 관측 evidence |

ER2는 Skill 이름(capability)만 고른다. 정책 버전은 고르지 않는다. learning이 PolicyArtifact를 승격하면 장치 capability가 늘고, Fleet 도구 catalog가 그것에서 파생된다(D-392 §3). 이것이 두 파트의 유일한 정방향 결합이며 런타임 import는 없다.

다음 조건을 유지한다.

1. `POLICY_DISPATCH_ENABLED=False`를 유지한다(D-326 §3, D-392 §7).
2. 두 루프는 중첩하지 않는다. ER2 피드백은 terminal 이벤트 뒤 새 턴이다(D-357 §4). 엔벌로프 이탈은 ER2와 무관하게 HOLD다.
3. ER2의 이미지 점·박스는 operations가 해석한 Task 파라미터로만 내려간다(D-331 §3).
4. stop과 세대 변경은 ER2 턴과 늦은 결과를 무효화한다(D-357 §6, D-358 §4).
5. 제안한 모델과 판정하는 모델은 같지 않다.

#### 4. learning의 계약과 공통 승격 사다리

- **Episode(`rosy.episode/1`)** 하나로 세 녹화 형식을 묶는다. 기존 형식은 이 계약의 profile이 된다.
  - 헤더: device, robot_type, sim/real, clock_domain, task, skill, policy·model·calibration·camera_profile revision, 출처 해시.
  - 상관 id: 장치가 실제로 받은 것만(현재 action_id·attempt_id). mission/step id·ER2 proposal_id·turn_id는 learning/datasets가 Fleet 원장 export와 오프라인 join한다.
  - 스트림: observation, action(의미·단위 명시), teleop intent, events(개입·HOLD·stop).
  - 결과: task_outcome과 판정 출처.
- **DatasetManifest:** 불변 원본 Episode revision 목록, 변환 설정, 파생 content_sha. 원본은 바꾸지 않고 파생만 새로 만든다(D-373·D-379 store 규칙 계승).
- **PolicyArtifact:** v0.2 §9.2의 고정 항목을 함께 담는다. 장치 구성, 관절 순서, 카메라 배치, 정규화 stats, 행동 공간·단위, 제어 주기, 엔벌로프 버전, controller·tool 버전, dataset revision, 평가 보고다. 정규화 불일치는 오류 없이 결과만 망가뜨리므로 로드할 때 검증한다. `rosy.perception.model/1`은 이 계열의 인식 profile이 된다.
- **ModelProfile·VerifierArtifact:** 숙고형 모델과 판정기의 승격 단위다.

세 종류 산출물은 같은 사다리를 쓴다.

| 단계 | 의미 | 기존 대응 |
|---|---|---|
| L0 | 오프라인 재생·sim 평가 | D-378 R0, D-205 replay gate |
| L1 | 섀도: 실물에서 판단만, 실행 안 함, 비교 기록 | D-378 R1, D-356 shadow |
| L2 | 사람 확인 하 제한 사용 | D-378 R2 |
| L3 | 등록 범위 내 자동 | 별도 밸브 ADR |

운전 중 가중치 교체와 정책 혼합은 금지한다. 롤백은 한 명령이다(D-356).

#### 5. 강화학습은 같은 파이프라인 안에서만 한다

- env는 Gymnasium 계약(`reset → (obs, info)`, `step → (obs, reward, terminated, truncated, info)`)을 쓴다. 관측·행동 공간은 대상 스킬의 PolicyArtifact와 같다.
- 엔벌로프 이탈은 `terminated=True`와 실패 보상으로 끝낸다(info에 HOLD 사유). `truncated`는 시간 한도만이다. 이탈을 truncated로 두면 정책이 경계를 비용 없는 끝으로 배운다.
- 백엔드는 sim(sim 장치 owner가 같은 middleware 파이프라인을 돌림)과 real(장치 API, 학습 모드) 둘이다. 학습 env는 별도 안전 로직을 갖지 않는다. 학습 중에도 행동은 같은 엔벌로프와 Safety Guard를 지난다.
- 사람 개입은 Arbiter의 MANUAL 우선순위로 처리하고 Episode events에 기록한다.
- 보상: sim은 ground truth를 쓴다. 실물은 사람 표시와 오프라인 학습한 성공 분류기(VerifierArtifact L0/L1)를 쓴다.
- 생산 경로에는 학습 루프를 두지 않는다. 실물 학습 중인 장치는 Fleet이 사용 불가로 본다. 물리 E-stop은 항상 독립 경로다.
- 실물 RL의 선행 조건은 다음 순서다. 모두 충족하기 전에는 어느 경로로도 실물 RL을 하지 않고 sim만 쓴다(6단계).
  1. OMX 로컬 owner 수용(D-299 Proposed)
  2. D-399 후속 1(엔벌로프 스킬 계약)
  3. D-399 후속 5(MANUAL 선점)
  4. OMX 리더 팔을 MANUAL 입력으로 여는 ADR(D-399 §6)
  5. 장치를 학습 모드로 넘기는 진입·해제·lease 계약 ADR(누가 진입을 승인하고, Fleet의 사용 불가 표시와 어떻게 연결되는지. D-390 lease는 sim 한정)
  6. 독립 E-stop 실측
- D-299의 네이티브 LeRobot 모드는 시연 녹화용으로만 남는다.
- sim→real은 real-to-sim 정렬부터 한다. 알려진 차이는 카메라 pitch 실측 11.8° 대 명목 8°(D-379), 흰 벽·카펫 대 sim 바닥이다. 그다음 보정된 domain randomization과 sysid를 거쳐 L0~L2로 올린다.
- 첫 대상 순서 제안: OMX 모방학습(ACT, 시연 export 존재) → OMX HIL-SERL 미세조정 → 인식 루프가 L2에 오른 뒤 Pinky 주행 정책.

#### 6. 즉시 시작하는 것과 나중에 하는 것

- **지금(C):** 폴더는 옮기지 않는다. 세 파트와 공용층의 소유 매니페스트, §2 import 규칙 시험을 추가한다. 기존 경로를 각 파트에 대응시킨다.
- **이후(B):** 어차피 해야 하는 `src/` 이전의 목적지를 이 ADR의 경로로 잡는다. D-413의 한 흐름씩 원칙을 따른다. 순서는 learning(작고 독립적) → contracts의 Episode·DatasetManifest·PolicyArtifact와 녹화 변환기 → operations → middleware이며, Pinky CORE는 마지막(이미지 빌드·deploy 경로)이다.
- 패키지 이름, ROS 패키지·노드·토픽 이름, API 경로, 공개 wire는 바꾸지 않는다(D-231, v0.2 §6.4). source root만 옮긴다.
- 이미 D-413 경로로 진행 중인 작업은 목적지를 다시 정한다. 2026-10-03 기준 `feat/rosy-cell-c3-gazebo`가 `modules/`·`apps/`·`integrations/`·`profiles/` 아래 6파일을 바꾸고 있다.

### 기존 결정과의 관계

| 기록 | 처리 |
|---|---|
| D-209 §4 (Accepted) | "`learning/` 패키지는 만들지 않는다"를 대체한다. 학습·채점이 로봇 이미지 밖이라는 취지는 유지한다. learning은 장치 설치에 들어가지 않는다 |
| D-186 (Accepted), D-207 (Proposed) | "학습 패키지를 `src/`에 만들지 않는다"를 같은 범위에서 정리한다 |
| D-413 (Accepted 2026-10-02) | §1 최상위 `modules/`를 파트 안 2단계로 부분 대체한다. §3 "계약은 소유 모듈에"는 유지한다. integrations·profiles·두 원장·고정 셀 우선 이전은 유지한다 |
| D-425 (Accepted 2026-10-03) | §4의 최상위 `apps/`·`ui/`를 각 파트 안으로, `ui/shared/web`을 최상위 `shared/web/`으로 부분 대체한다. 1~3항의 화면 소유·공유 경계는 유지한다 |
| D-315·D-317 | 폴더가 실행 권한을 증명하지 않는 원칙을 유지한다. 파트는 책임이고, 설치 단위와 대부분 겹치지만 배치 판정은 deploy·package 증거로 한다 |
| D-299 (Proposed) | 네이티브 LeRobot 모드는 시연 녹화용. 실물 RL은 §5 학습 모드 |
| D-399 (Proposed) | §2 AI 두 부류를 계승한다. 후속 1·5가 §5의 선행 조건이다. 후속 1은 같은 호스트 밖 추론을 위한 D-231 §4 개정 여부도 다루므로 학습 정책의 추론 위치와 직결된다 |
| D-170·D-177 | Episode가 mission/step id를 직접 기록하려면 Device Action 상관 키 결정이 필요하다. 그 전에는 오프라인 join |
| D-322 | Isaac Lab 학습 보류를 유지한다(Isaac Lab 3.0은 2026-10-03 기준 Early Access) |
| D-290·D-296·D-326·D-331·D-392 | 이름·역할·ER2 제안 전용·도구 allowlist를 유지한다 |

D-209·D-413·D-425 본문에 부분 대체 표기를 추가했다(2026-10-03 수용).

### Alternatives

- **A. D-413/D-425 그대로:** 이동 계획은 바뀌지 않는다. 하지만 최상위가 12개로 남고 세 파트가 폴더에 보이지 않는다. 사용자 문제("구조가 안 보인다")를 풀지 못한다.
- **C만(폴더 유지, 소유 view):** 이동 비용과 worktree 충돌이 없다. 그러나 폴더만 봐서는 파트를 알 수 없다. 이 ADR은 C를 즉시 시작 단계로 채택하고 B를 목표로 둔다.
- **호스트 기준 3분할(device/site/shared):** 현재 배포 모양과는 맞는다. 하지만 기록 → 학습 → 배포 고리가 모든 호스트를 가로지르므로 learning이 세 조각으로 찢어진다.
- **ER2·VLM 전용 최상위 파트(cognition/agent):** 실행 권한 없는 제안자를 구조상 최상위 지휘자로 보이게 한다. D-326·D-392·D-399와 어긋난다.
- **저장소 여러 개로 분리:** 장치·Fleet·화면이 공유 계약과 양 끝 시험에 의존하므로 계약 버전 맞추기가 새로 생긴다. D-413의 한 흐름씩 원칙과도 충돌한다.

### Consequences

- 폴더가 플랫폼의 세 가지 일과 의존 방향을 보여준다. 새 로봇은 `integrations/robots/<model>`과 `middleware/apps/device/<model>`, 새 공정은 `operations/processes/<공정>`, 새 학습 방식은 `learning/training/<방식>`으로 늘어난다.
- 학습 정책·ER2 모델·판정기가 같은 승격 사다리와 증거 형식을 쓴다.
- 어제·오늘 승인한 D-413·D-425 목표 경로를 다시 바꾸므로, 이행 계획과 진행 중 작업의 목적지를 갱신해야 한다.
- 공용 UI 키트가 최상위 `shared/web/`으로 하나 늘어난다.
- 구조 시험이 없으면 이 규칙은 문서로만 남는다. 시험이 먼저다.

### Validation and Follow-up

이번 문서의 수용 조건은 ADR·Log 행의 일치, 번호 충돌 부재, harness lint다. 코드·폴더·wire 변경은 없다.

후속:

1. 소유 매니페스트와 import 규칙 시험(C). 현재 경로를 세 파트·공용층에 대응시키고, 위반을 현 상태 목록으로 고정한 뒤 줄여 간다. operations에서 비-LLM 판정기(성공 분류기 등)를 추론하는 경로(onnxruntime 등)는 별도 결정으로 남긴다.
   - 착지(2026-10-03, `test/d427-ownership-manifest`): 매니페스트 `tools/harness/platform_parts.yaml`, 시험 `test/architecture/test_platform_parts.py`. 현 위반 9건을 `KNOWN_VIOLATIONS`에 고정했다.
2. contracts의 Episode·DatasetManifest·PolicyArtifact 초안과 세 녹화 형식 변환기.
3. D-399 후속 1(엔벌로프 스킬) ADR.
4. learning 이전 계획(`tools/perception/*`, OMX export, `src/sim/isaac_sim`).
5. 강화학습 env 계약 ADR(관측·행동 공간, reward, 리셋, 개입 기록, 학습 모드 진입·해제·lease).

**References:** [D-209](D-209-perception-folder-and-learned-backend.md), [D-290](D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-326](D-326-agent-loop-boundary.md), [D-392](D-392-provider-neutral-model-tool-contract.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-413](D-413-platform-modules-integrations-apps-profiles.md), [D-425](D-425-app-surface-ownership-shared-boundaries-and-source-layout.md), [v0.2 설계](../reference/ROSY_Platform_Architecture_Design_v0.2.md), [12 학습 파이프라인](../architecture/12_ROSY_Dataset_and_Learning_Pipeline.md)

### 이행 기록 (2026-10-03~04)

이 절은 사실 기록이다. 위 Decision 본문은 바꾸지 않는다. 기준은 `origin/main` `0b277ae38`(2026-10-04)와 push 전 로컬 브랜치 `refactor/d427-bulk` `ed2b24c7d`다. 실행 계획은 [소스 이전 계획](../plans/2026-10-03-d427-source-migration.md)(rev 4)과 [이동 뒤 남은 일](../plans/2026-10-04-d427-post-migration-follow-ups.md)(rev 1)이다. 경로는 D-226에 따라 기록 시점 그대로 적는다.

#### 착지한 장치 (origin/main)

| 장치 | 커밋 | 내용 |
|---|---|---|
| 소유 매니페스트와 import 규칙 시험 (후속 1, §6 C) | `54379a99c`..`541a30fa7` | `tools/harness/platform_parts.yaml`, `test/architecture/test_platform_parts.py`. 현 위반 9건을 `KNOWN_VIOLATIONS`에 고정했다 |
| wave 0: 이동 상태 필드와 옛 경로 검사 | `147c16383`..`a916a1880` | 패키지당 leaf 목표, root마다 `wave`, partly moved root의 `deferred`, 이동 뒤 `legacy`. `KNOWN_VIOLATIONS` key를 `d427_target`으로 바꿨다. `test_moved_roots_leave_nothing_behind`가 옛 경로의 tracked 파일과 옛 경로 문자열(슬래시, `$VAR/`, 조각 결합, `../`)을 잡는다. harness append-only 검사가 옮긴 `logs.md`를 따라간다. learning ROS root에 `device_install_exception`을 단다 |
| wave 0: `colcon_roots` 한 목록 | `4bdcf4684`..`d9d993fc8` | 매니페스트 `colcon_roots`를 CI, native payload(`build-native-payload.sh`), SD 이미지(`build-image.sh`·`customize-rootfs.sh`), release 영향 판정, 개발 스크립트가 읽는다. ROS 패키지 이름 27개를 `test_ros_package_names_are_frozen`(`test/architecture/test_colcon_roots.py`)이 고정한다 |
| wave 0: D-429·D-430 기입 | `fd3732767`..`589068df7` | concern 태그, safety 하위 root·`safety_modules`·`safety_anchors`, 사이트 장치 목표 `operations/site_devices`, D-429 §4 api 규칙, ER2 사이트 장치 구동 이름 거부, D-430 분리·행동 시험, CI `Safety-Review` trailer 검사. 상세는 [D-430 상태 정정](D-430-safety-as-a-separate-concern.md) |

#### Wave 상태

| Wave | 목적지 | 상태 | 커밋 |
|---|---|---|---|
| 1 | `learning/training/perception`, `learning/envs/isaac`, `learning/curation/omx` | origin/main | 1-pre `0ad071752`, `b8dc56916`, `50ddfa2cd`, `c606975a2`, 후속 `58b56171f`·`8dda13eec` |
| 2a | `contracts/skill` (배포 `rosy-contracts-skill`) | origin/main | `b715512f2` |
| 2b | Episode·DatasetManifest·PolicyArtifact 자리 | 막힘. 후속 2(스키마 설계)를 기다린다 | — |
| 2c | `rosy-execution-local` 분리 → `middleware/execution/local` | origin/main | `eaab6b3c0` |
| 3a | `operations/{world,processes/palletizing,apps/fleet,execution}` | origin/main | `8bcbbc53e`..`ba7b49e67`, index 재생성 `b96c5c0d2` |
| 3b | `operations/{vision,apps/games,processes/cell,ui/cam}`, `operations/site_devices/{dock,signal}`, `operations/vision/signal_observer` | `refactor/d427-bulk`, push 전 | root별 7커밋 `57c694912`..`6616e4c3a`, AGENTS `c50124aab` |
| 3c | `operations/fleet` | 같은 브랜치, push 전 | `e9f19b687`, 잔여 수정 `9e1147027` |
| 4a | `middleware/skills/{api,manipulation}`, `middleware/apps/device/omx/agent` | 같은 브랜치, push 전 | `e60dc3da7`, `f5e9d3340` |
| 4b | `shared/web`, `middleware/ui/{robot,pilot,face}` | 같은 브랜치, push 전 | `3c4372d58`, `188d6af6f` |
| 4c | `middleware/drivers/*`, `middleware/apps/device/{pinky,omx}/*`, `middleware/core/navigation`, `integrations/simulation/gazebo` | 같은 브랜치, push 전 | `4075c26b1`, `379eb39fb` |
| 4d | `contracts/{foundation,ros_idl}`, `middleware/core/{gateway,services,events,api_web}` | 같은 브랜치, push 전 | `62fdf79c0`, `040707cda` |
| 4e | `middleware/perception` | 같은 브랜치, push 전 | `805011387`, `caaa2a586`, rebase 잔여 `ed2b24c7d` |
| 5 | 빈 `src/`·`modules/`·`apps/` 삭제, `colcon_roots`에서 `src` 제거 | 시작 전 | — |

- 3b–4e의 SHA는 2026-10-04 `0b277ae38` 위로 rebase한 뒤의 값이다. push 전이므로 다시 바뀔 수 있다. 일괄 이동 스크립트는 `tools/harness/d427_move.py`(같은 브랜치 `155cdff30`)다. 후속 계획이 적은 `965c7874a`(3c)·`8767146af`(스크립트)는 rebase 전 SHA다.
- `refactor/d427-bulk`의 매니페스트는 pending root가 0개이고 `colcon_roots`가 `[src, learning, operations, middleware, contracts, integrations, shared]`다.
- origin/main의 `colcon_roots`는 `[src, learning, operations]`다.
- `KNOWN_VIOLATIONS`: 9(`541a30fa7`) → 8(`bef8a0819`, D-429 §4 api 규칙) → 5(`b715512f2`, 2a). 1c는 1건을 교체해 수를 유지했다(계획 Q6). 2b가 착지하면 4건이 된다. bulk 브랜치에서도 5건이다.

#### 사용자 과정 결정 (2026-10-03)

다음 결정은 §6 B의 실행 방법을 바꾼다. ADR 본문과 실행이 조용히 어긋나지 않도록 여기 적는다. 원문은 이전 계획의 "결정 기록"과 루트 `AGENTS.md`다.

1. **미병합 브랜치는 wave를 막지 않는다.** 옮길 경로를 건드리는 미병합 브랜치에는 snapshot tag `archive/<branch>`를 달고 브랜치는 남긴다. 브랜치 주인이 이동 뒤 rebase한다.
2. **image wave는 release 창을 기다리지 않는다.** wave마다 ARM64 native payload(`build-native-payload.yml`)와 SD 이미지(`build-pinky-image.yml`) CI 빌드로 패키지 목록·rosdep 범위가 같음을 증명한다. 로봇 배포는 이전이 끝난 뒤 다음 정규 release에서 한다(D-191 취지).
3. **기계적 wave는 자동 gate만으로 착지한다.** safety 코드를 옮기는 wave는 독립 리뷰를 받는다. 일괄 이동분은 착지 뒤 rename 리뷰 한 번으로 받고, 일괄 커밋에도 `Safety-Review:` trailer를 넣는다(CI가 요구한다).
4. **3b 뒤 남은 wave는 스크립트로 옮긴다.** `tools/harness/d427_move.py <wave>`, wave당 이동 커밋 하나와 잔여 수정 커밋.
5. **루트 `AGENTS.md` "D-427 이동 기간 규칙":** (1) 우선순위 폴더 이동 > main CI > 안전 > 기능, (2) 이동 중 그 wave 경로 동결, (3) main checkout에서 작업하지 않고 `.worktrees/`에서만, (4) push 전 순서 fetch → rebase → `rosy_harness.py generate` → pre-push, force-push 금지, (5) 새 코드는 `d427_target`에만, (6) 구조를 바꾸는 ADR은 D-427·D-429·D-430과의 관계를 표로 적는다. 같은 절에 (7) safety 태그 경로 변경의 trailer·독립 리뷰가 있다. 2·5항은 이동이 끝나면 지운다(후속 계획 P1-4).

#### §6 원문과 달라진 점

- **이름.** 패키지 이름과 ROS 패키지·노드·토픽 이름은 바뀌지 않았다. `test_ros_package_names_are_frozen`이 27개 이름을 지킨다. 예정된 예외는 D-429 §5의 `fleet.ai` → `rosy.decision` 개명(D-231 예외) 하나다. 이 carve는 3c(`e9f19b687`, 커밋 메시지 "the fleet.ai carve to rosy.decision is not done here")에 들어가지 않았고 아직 남아 있다(후속 계획 P2-1).
- **deferred 하위 root.** 부모 패키지와 함께 옮겼고 떼어 내기는 미뤘다(계획 Q2). bulk 브랜치 경로 기준이다.
  - `operations/fleet/fleet/ai` → `operations/decision`(D-429 §5 carve)
  - `operations/fleet/fleet/server/web` → `operations/ui/console`(D-425 Task 9)
  - `integrations/simulation/gazebo/launch` → `middleware/apps/device/sim`(gz_sim 분리 후속)
  - `integrations/simulation/gazebo/scripts` → `tools/sim`(gz_sim 분리 후속)
- **observer 중첩.** 3b의 신호 관측기 root `operations/vision/signal_observer`가 ROS 패키지 `rosy_vision` 폴더(`operations/vision`) 안에 있다. `__init__.py`가 없어 wheel에 들지 않을 뿐이다. 위치는 후속 계획 P2-4에서 다시 정한다.
- **contracts 순서.** §6 B 순서는 contracts가 operations 앞이다. 2a의 `contracts/skill`만 그 자리에서 옮겼다. `contracts/foundation`·`contracts/ros_idl`은 CORE 이미지 입력이라 4d에서 CORE와 함께 옮겼다.

#### 열린 증거

- **ARM64 payload·SD 이미지 동등성:** 기록이 없다. origin/main에 `docs/validation/d427-source-migration/`이 없고, wave 0 8번의 기준선 빌드 증거도 없다. 그때까지 `ARTIFACT_EQUIVALENT`를 주장하지 않는다(후속 계획 P1-2).
- **safety rename 리뷰:** 대기 중이다. bulk 커밋의 trailer는 "independent rename review pending"이다. 대상은 3b 펌웨어, 3c Fleet 정지 경로, 4c OMX local stop, 4d CORE safety 파일이다(후속 계획 P1-3).
- 로봇 배포(P1-7)와 장치 수용은 이 이전의 출구가 아니다.
