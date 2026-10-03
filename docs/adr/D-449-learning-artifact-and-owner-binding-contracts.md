## D-449 학습 산출물은 출처·시계·단위·owner binding과 승격 증거를 공용 계약으로 보존한다

**Status:** Proposed (2026-10-04, active learning closure implementation; 구조·wire 초안이며 runtime 활성화·장치 수용 승인 아님)

### Context

D-427 후속 2와 wave 2b는 Episode·DatasetManifest·PolicyArtifact의 구체 스키마를
기다린다. 기존 OMX 시연은 검증/export까지 있으며 정책 학습·owner 실행과 연결되지
않았다. Pinky 인식 manifest와 Action 원장은 행동 정책 산출물을 대신할 수 없다.
이번 계약 초안은 로컬에서 검증하며 기존 wire·recorders·설치를 바꾸지 않는다.

### Decision

`contracts/learning`의 ROS·torch·LeRobot 없는 wheel `rosy-contracts-learning`을 둔다.
표준 라이브러리로 canonical revision과 상대 파일 경로/해시를 검증한다.
`root` 없는 검증은 구조 검증이고, root가 있으면 실제 파일 byte 수·SHA를 검증한다.
해시와 보고서 verdict는 신뢰·서명·물리 수용을 증명하지 않는다.

- Episode(`rosy.episode/1`): profile, device/robot_type, sim/real, clock_domain,
  task/skill, policy/model/calibration/camera_profile revision, 원본과 stream 파일,
  실제 장치 action/attempt 상관 키, status, 과제/Action 결과와 judge/evidence.
  null/unknown을 보존한다. mission/step/ER2 id는 장치 헤더에 만들지 않고 후속
  Fleet export join에서 별도 binding으로 기록한다. 원본 stream 안 capture/state
  시계와 received wall 시계를 바꾸지 않는다. profile별 sample 검증은 후속이다.
- DatasetManifest(`rosy.dataset-manifest/1`): 중복 없는 Episode revision 목록,
  변환 tool/config SHA, 파일 목록. 내용 변경은 새 canonical revision이다.
- PolicyArtifact(`rosy.policy-artifact/1`): OMX 관절 절대 목표(rad)와 Pinky base
  velocity 후보(m/s, rad/s)를 별도 profile로 둔다. joint/action 순서·관측 shape,
  장치/카메라/정규화 binding, limits, 주기·stale budget, reset 사건, HOLD 실패 의미,
  owner/controller/envelope revision, dataset revision·평가·tool·weight 파일을 묶는다.
  OMX local controller와 Pinky CORE Command Manager를 혼용하지 않는다.
  이 binding은 owner에게 명령을 보낼 API·권한·lease를 부여하지 않는다.
- PromotionRecord(`rosy.promotion-record/1`): 동일 policy revision의 인접 단계만
  기록한다(unregistered→L0→L1→L2→L3). L0는 offline/sim/owner/독립 과제 판정,
  L1은 추가 shadow/stop, L2는 추가 제한 사용 판정, L3는 추가 등록 범위 판정의
  pass 보고서를 요구한다. L2/L3는 별도 ADR·scope·승인 evidence를 요구한다.
  순수 검증기는 registry transaction/운영자 인증/배포/실행 승인기가 아니다.

기존 `rosy.perception.model/1`, 녹화기 세 형식, LeRobot v3 파일은 유지한다.
후속 변환기가 원본 bytes와 profile 검증을 보존하며 공통 Episode로 감싼다.
정책 학습은 이 계약을 내보내고, 평가/registry는 실제 보고서를 묶으며,
owner loader는 설치 고정 binding·lease·generation·stale·reset을 다시 검사한다.
최종 Motion Intent/DeviceControlPort 연결은 D-442와 엔벌로프 스킬 후속의
실제 결정에 맞춘다. 이 초안으로 final writer나 정책 dispatch를 켜지 않는다.

| 관련 ADR | 관계 |
|---|---|
| D-427 | 후속 2 스키마 초안과 contracts/learning 자리 구현. 2b의 기존 validator 이동/세 변환기는 아직 미완료 |
| D-429 | learning concern 산출물과 contracts 경계를 구분. 외부 runtime dependency 없음 |
| D-430 | safety 구현을 이동/변경하지 않음. owner binding은 final command·안전 승인과 별도 |
| D-299/D-399/D-442 | OMX owner·엔벌로프·Motion Intent 결정의 상태를 유지. 물리 owner 활성화 권한 없음 |

### Alternatives

기존 perception manifest를 행동 정책으로 확장하면 rad와 v/omega·owner 계약이
관측 모델과 섞인다. LeRobot config만 사용하면 ROSY 시계·현장 envelope·승격
근거가 빠진다. 공용 산출물 wrapper와 개별 profile을 선택한다.

### Consequences and Validation

canonical revision은 원본 파일 해시와 metadata가 바뀌면 달라진다. 손상·경로 이탈,
owner/단위/순서 불일치, stage 도약, unknown/failed 평가를 거절한다.
SOURCE/LOCAL 검증은 runtime enforcement·GPU 정책 학습·SIM/장치 결과가 아니다.
후속: OMX/Pinky/Pilot 변환, LeRobot 학습과 실제 offline/SIM 평가, registry 원장,
owner candidate admission/stop/reset, Fleet export join과 replay. 전체 목표는 active다.

### 구현 보강 — 2026-10-04 실제 OMX 시연 연결

초안 0.1.1은 PolicyArtifact cameras에 source/model RGB 크기·scale·camera identity와
CameraInfo SHA를 둔다. camera_profile_revision은 없으면 null을 유지하며, 카메라
정책의 L1 이상 기록에는 알려진 CameraProfile binding을 요구한다.
실제 보존된 LeRobot export를 snapshot/reader로 읽는 learning/training/omx ACT
연구 경로를 추가했다. owner/envelope가 미등록이면 연구 artifact로 명시하고,
실제 평가 부족·SIM/independent task 미확인에서 승격을 만들지 않는다.
실행 근거: docs/validation/omx-act-offline-2026-10-04.md.

### 구현 보강 — 2026-10-04 정책 원장 초안

learning/registry/policy는 immutable policy 파일 snapshot과 SQLite 단계 CAS,
canonical event chain을 둔다. 실제 ACT 보고서의 연구 조건을 재계산해 거절 이력을
기록한다. promote API는 policy/promotion/report hash에 묶인 scoped verifier의
HMAC receipt와 실제 pass JSON을 요구한다. 운영 신뢰 키/승인 verifier는 설치하지
않았고 원장 상태가 actuator 권한을 부여하지 않는다. DatasetManifest ingestion,
rollback의 stop/승인 계약과 owner 소비는 후속이다. 구조 제안 상태는 유지한다.
