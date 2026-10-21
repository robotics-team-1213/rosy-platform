## D-755 공통 학습 데이터와 다중 계정 협업 연동

**Status:** Accepted (2026-10-14, 사용자 요청에 따른 설계 결정. 구현·운영 활성화·외부 계정 연결·장치 수용은 미완료)

### Context

로봇암 시연, 주행 기록, 일반 영상, 라벨 검수와 AI 추론 결과를 여러 사람이 함께
축적하고 학습·평가·추론에 재사용해야 한다. 외부 데이터와 모델은 Hugging Face
등에서 가져오며 개인별 복수 계정과 팀 저장소를 구분해야 한다.
파일 확장자만 통일하면 시간·단위·라벨 의미·이용 권한이 사라지고, 공유 토큰 하나로
처리하면 누가 어떤 자격으로 가져오고 승인했는지 설명할 수 없다.

현재 D-449의 `contracts/learning`은 Episode·DatasetManifest·PolicyArtifact를
검증한다. `artifacts.py`의 Episode v1은 observation/action/events 참조를 모두
요구하며 OMX 시연은 SIM 전용이다. `learning/curation/omx/lerobot_export.py`는
LeRobot 0.4.4를 고정하고 실제 reader로 재개방한다. 일반 영상과 계정 협업 전체가
이미 구현됐다는 뜻은 아니다. Fleet의 기존 named user/session과 검수 앱의 접근
보호도 외부 OAuth 또는 프로젝트별 공동 검수 권한을 대신하지 않는다.

### Decision

#### 1. 공통 계약, 자료별 profile, 외부 형식 adapter

원본 bytes는 보존한다. JSON은 버전 있는 manifest와 참조 계약에 사용하고,
영상·마스크·MCAP·Parquet 등 내용은 적합한 기존 형식을 유지한다. 공통 계약은
`contracts/learning`, 수집·검수·변환은 `learning/curation`, 학습·평가·산출물은
기존 `learning/{training,evaluation,registry}` 책임을 따른다. 새 최상위 폴더나
범용 플러그인 프레임워크를 이 결정으로 만들지 않는다.

| 공통 의미 | 반드시 보존할 내용 |
|---|---|
| 원본과 계보 | 원본 ID·SHA256·수집 session, 원본/파생 관계, 외부 repo 종류·ID·고정 revision·파일 해시, 변환기/설정 revision |
| 시간 | capture/state/command/received 시각, clock domain, 동기화 오차·누락·실제 FPS; 수신 시각을 촬영 시각으로 치환하지 않음 |
| 라벨 | 안정적인 semantic ID, ontology revision, 표현 종류·좌표 기준·근거 구간, 작성자·검수자·승인 revision |
| 장치와 관측 | sim/real/external 출처의 구분, 카메라 identity·해상도·보정 revision·좌표계, 장치 profile |
| 행동과 결과 | 요청·owner 접수·관측된 실행을 구분, 단위·순서·절대/증분 의미, 성공 판정자·근거; 모르는 값은 unknown |
| 이용 범위 | 출처·license·동의 증거와 내부 열람/학습/추론/외부 공유 허용 범위, 프로젝트 소유권, 제한 또는 미확인 사유 |
| 추론 | 입력 원본/구간 참조, 모델·전처리 revision, 출력 schema·시각·지연·불확실성, 후속 검수 계보 |

표는 목표 의미 계약이다. 기존 exact-field validator에 임의 필드를 추가하지 않는다.
구현 시 새 버전 또는 별도 profile/sidecar와 명시적 migration을 정하고, 기존
Episode v1을 그대로 읽으며 원본 및 기존 canonical revision은 보존한다.
이 ADR은 새 REST 경로나 기존 wire 필드의 즉시 추가를 승인하지 않는다.

자료 profile은 최소한 로봇암 행동 시연, 주행 기록, 행동 없는 영상/이미지를 구분한다.
영상만 있는 자료는 시각 인식·영상 이해·구간 설명에 쓸 수 있다. 동기화된 행동과
상태가 없는 자료를 행동 모방 학습 자료로 내보내지 않으며 action을 0으로 채우지 않는다.
외부 영상의 장치·시계·실제/합성 여부가 미확인이면 그대로 기록하고 용도별 판정한다.
로봇암은 관절 이름/순서·rad/degree·절대/증분·그리퍼 위치/개폐 의미를 명시한다.
카메라별 시각과 상태/행동 정렬을 검사하며 주행 속도와 관절 목표를 같은 action으로
취급하지 않는다. 외부 task 문장도 성공 증거나 실제 실행 결과를 대신하지 않는다.

라벨의 표시 이름과 semantic ID, 학습 클래스 index를 분리하고 버전별 매핑을 보존한다.
AI 초안·사람 승인·추론 출력은 서로 다른 기록이다. 승인된 라벨의 수정은 새 revision이며
기존 학습 manifest를 덮어쓰지 않는다. 동일 원본 session의 인접 frame·재인코딩·재라벨은
같은 split 그룹으로 묶어 train/eval 누출을 막는다. 학습/추론의 RGB·crop·resize·좌표
변환·정규화·관절 순서는 같은 버전의 전처리 계약으로 재현한다.

#### 2. ROSY 사용자, 외부 로그인, 데이터 연결을 분리한다

**정정 (2026-10-21, D-757):** 사람의 로그인은 모든 앱과 같은 Rosy Account 하나다. 학습 앱의 자체 비밀번호와 HF 로그인, 학습 쪽 초대 단계는 제거했다. HF OAuth와 PAT는 데이터 연결로만 쓰고, 프로젝트 권한은 Account 원장의 `learning.*` 부여로 판단한다. 아래의 첫 로그인·초대 문장은 이 정정 이전 결정이다.

ROSY 내부 사용자 ID와 프로젝트 membership이 공동작업의 기준이다. 외부 계정은
provider의 검증된 issuer/subject에 연결하고 이메일·표시 이름 일치로 병합하지 않는다.
한 사용자는 같은 provider의 복수 계정과 여러 provider를 연결할 수 있다. 개인 계정
연결과 프로젝트 자동 작업용 연결을 구분하며, 후자는 지정 관리자가 관리한다.
조직 저장소 namespace는 계정 자체가 아니다. 사용 계정과 대상 namespace를 모두 표시한다.

Hugging Face OAuth/OIDC를 첫 로그인·연결 대상으로 한다. 이미 로그인한 사용자의
명시적 연결 절차 또는 초대된 사용자의 첫 로그인만 기존 내부 사용자와 결합한다.
검증되지 않은 외부 계정 로그인은 프로젝트에 자동 가입시키지 않는다. 동일 외부
subject가 다른 내부 사용자에 연결되어 있으면 자동 이전하지 않고 충돌을 표시한다.
연결 해제 시 마지막 로그인 수단을 잃지 않도록 다른 인증 수단의 확인을 요구한다.

Authorization Code + PKCE, 일회성 state와 OIDC nonce, issuer/audience/서명/만료,
등록 redirect URI를 검증한다. 로그인 신원 범위와 저장소 읽기 동의를 분리하고
추가 기능에 필요한 범위만 요청한다. 조직 membership 조회는 ROSY 역할 부여나
조직 저장소 읽기 허가로 간주하지 않는다. provider가 부여한 scope와 자원 접근을
실제 요청으로 확인한다. OAuth 등록/운영 callback과 비밀 보관 수단은 배포 전 요건이다.

OAuth가 지원하지 않는 연결은 해당 provider가 지원하는 제한된 읽기 자격증명을
서버에 등록하는 방식으로 추가한다. PAT는 데이터 접근 자격이며 ROSY 로그인 증명이
아니다. provider를 추가할 때마다 인증 방식·지원 자원·scope·권한 취소 동작을 검증한다.
지원하지 않는 연결을 UI에서 동작하는 것처럼 표시하지 않는다.

토큰/refresh token은 서버 측 암호화 비밀 저장소에 두고 작업에는 불투명한 연결 참조와
자격증명 세대만 기록한다. 브라우저 저장소·로그·manifest·공개 Git·학습 산출물에
토큰을 넣지 않는다. 전역 CLI 로그인이나 공용 HF_TOKEN 변경으로 계정을 전환하지 않는다.
각 요청과 worker에 선택된 자격증명을 명시적으로 주입하고 refresh를 연결별 직렬화한다.
만료·scope 변경·연결 해제는 새 요청과 대기 작업을 차단하고, 실행 중 전송은 취소하거나
다음 체크포인트에서 중지한다. 실패 시 다른 사람 계정으로 자동 재시도하지 않는다.

#### 3. 프로젝트 공동작업과 가져오기 권한

프로젝트 안에서 열람, 자료 가져오기/라벨 편집, 검수 승인, 구성원/연결 관리,
외부 게시 권한을 구분한다. 이는 요구 capability이며 기존 Fleet 운전 역할을
자동 확장하거나 새 wire 역할명을 확정하지 않는다. 공유 검수 토큰만으로 사용자별
승인을 기록하지 않는다. 팀은 자료와 승인 이력을 공유하고 개인 토큰은 공유하지 않는다.

개인 연결은 소유자 작업에만 쓴다. 프로젝트 연결은 관리자가 허용한 자원과 작업에만
사용하며 팀원은 비밀을 읽을 수 없다. 자료를 프로젝트에 가져올 때 해당 계정의 읽기
권한과 팀 내 이용 허용 범위를 각각 검사한다. gated 자료의 개인 승인은 팀 전체 승인으로
해석하지 않는다. license/팀 이용 범위가 미확인이면 공유 및 학습 투입을 보류한다.
연결 해제는 원본을 자동 삭제하지 않는다. 지속 이용 근거가 없거나 권한이 취소된
자료는 열람·새 학습·재배포를 보류하고, 파생 자료와 모델까지 영향 목록을 남긴다.
삭제/보존 처리는 권한 있는 관리자가 출처 조건에 따라 수행하며 감사 계보를 보존한다.

화면과 서버는 현재 프로젝트·ROSY 작업자·사용 외부 계정·대상 저장소·권한 범위를
같이 보여준다. 다음은 목표 UI 흐름이며 아직 구현된 화면을 뜻하지 않는다.

1. 프로젝트 참여/로그인 → 연결 추가 또는 기존 연결 선택 → 권한·만료·접근 확인.
2. dataset/model 종류와 namespace/repo, revision, 필요한 파일/크기/이용 범위 확인.
3. branch/tag를 immutable commit으로 해석해 고정 → 다운로드 → 해시/형식/출처 검증.
4. 용도별 적격성(인식/영상 이해/행동 학습) 표시 → 라벨 검수 → 고정 dataset 생성.
5. 변환 검증 → 학습/독립 평가 → 기존 registry 승인 절차. 추론 결과 재수집도 같은 경로.

가져오기 작업은 프로젝트·요청자·연결·고정 revision·선택 파일·변환 설정에 묶인다.
재시도는 같은 고정 입력을 사용하고 최신 branch를 다시 가져오는 것은 새 작업이다.
중단 파일은 검증된 완성 자료와 구분하고, 완료 시 원자적으로 등록한다. 동시 동일 요청은
중복 작업을 제어하되 프로젝트/권한 검사를 생략하지 않는다. 내용 해시가 같아도 다른
프로젝트의 접근권을 상속하지 않으며 비공개 cache와 임시 파일의 권한을 격리한다.

다운로드는 알려진 provider API/SDK와 허용 endpoint를 통해 처리한다. URL/redirect의
내부망 접근, archive 경로 이탈·크기 초과를 차단한다. 외부 dataset script, pickle 또는
모델 remote code를 가져오기 과정에서 실행하지 않는다. 모델을 등록해도 자동 적재하지
않으며 별도 검증된 실행 환경과 기존 승인 경로를 따른다.

라벨 편집·승인은 base revision을 검사해 충돌을 사용자에게 보여주고 조용히 덮어쓰지
않는다. 검수 배정은 최종 revision 검사를 대신하지 않는다. 독립 검수가 필요한 기존
규칙은 유지한다. 사용자·연결·자료 revision·행위·시간·결과를 감사 기록에 남긴다.
팀 탈퇴/역할 취소는 열린 화면과 대기 worker의 다음 권한 검사에도 반영하며 자료 ID를
알고 있다는 이유로 열람을 허용하지 않는다.

#### 4. LeRobot, Hugging Face Hub, Spaces의 역할

LeRobot은 행동 학습용 내보내기/가져오기 adapter다. ROSY 원본 계약을 외부 저장 형식에
종속시키지 않는다. 기존 0.4.4 exporter를 우선 재사용하고 버전 변경은 별도 호환 검증을
거친다. v3 Parquet/MP4/metadata와 episode 경계를 실제 reader로 다시 열어 frame 수,
시각, 관절 순서/단위, 다중 카메라 정렬을 확인한다. lossy 영상 오차 허용치는 기록한다.
지원 불가 field는 삭제하지 않고 원본/sidecar에 보존하며 변환 손실 보고서를 만든다.

Hub dataset/model 저장소는 고정 revision으로 가져온다. Dataset/Model Card에 원본,
라벨 정의, 검수 수준, split, 변환/전처리, 제한·license를 연결한다. 다운로드 허가와
재게시 허가는 별개다. 외부 게시를 구현할 때는 대상 계정/namespace·공개 여부·파일
목록·크기·권리 검사를 미리 보여주고 권한 있는 사람의 명시적 게시 동의를 받는다.

Spaces는 실행되는 앱이며 dataset/model 저장소와 구분한다. Spaces 로그인 기능을
ROSY 사용자 DB나 프로젝트 ACL의 대체물로 삼지 않는다. Space/외부 inference API에
영상이나 프롬프트를 전송하는 기능은 별도 데이터 외부 전송·비용·결과 provenance
결정을 요구하며 이번 최초 가져오기 범위에는 넣지 않는다.

#### 5. 기존 결정과 구현 순서

| 관계 | 결정 |
|---|---|
| D-449 | 원본·시계·단위·profile·승격 계약을 보완. 기존 Proposed 상태와 v1 wire를 소급 변경하지 않음 |
| D-427/D-429 | 기존 learning/contracts/operations 책임과 배포 경계 유지 |
| D-430/D-516 | 모델 PC의 학습·평가와 AI PC의 승인 고정 추론 구분; CORE/OMX 최종 실행 권한 유지 |
| D-464/D-745 | 기존 검수·dataset build·소유 실행기 제어를 재사용; 승인 부족을 계정 연결로 해제하지 않음 |

구현은 작은 단계로 수행한다. (1) 기존 계약/reader 영향 조사와 영상 profile·라벨 계보·
용도 검증, (2) 기존 인증/배포 책임 안의 프로젝트 사용자·계정 연결·읽기 전용 HF
가져오기, (3) 공동 검수 revision 충돌·철회·계보 조회, (4) LeRobot 실제 roundtrip과
학습/추론 전처리 일치 검증. 외부 게시·다른 provider·Space 실행은 이 단계의 근거를
재사용해 필요한 것부터 추가한다. 외부 인증 UI는 HTTPS·비밀 보관·실제 callback이
준비되어야 활성화한다. 기존 원본의 일괄 재작성과 기존 접근 경로의 무중단 대체를
가정하지 않고 migration/되돌리기 계획과 기존 사용자 회귀 검사를 먼저 작성한다.

### Alternatives

- 모든 자료를 LeRobot으로 통일: 행동 없는 영상과 검수/이용 권한 계보를 표현하기 어려워 제외.
- 개인별 형식과 단일 공유 HF 토큰 유지: 도입은 빠르지만 의미 불일치·권한 혼합·감사 불가로 제외.
- 공통 의미 계약 + 자료 profile + 필요한 provider adapter: 기존 저장/검증 코드를 재사용하며 선택.

### Consequences and Validation

프로젝트와 계정별 접근 검사, 출처 계보, 충돌 처리가 추가된다. 대신 같은 원본의 여러
용도와 여러 사람의 작업을 추적할 수 있다. 문서 승인으로 기능/데이터/장치 gate는 이동하지 않는다.
구현 완료는 다음 실제 시나리오와 영속 readback으로 판정한다.

| 수용 시나리오 | 필수 결과 |
|---|---|
| 사용자 A/B, 서로 다른 프로젝트와 HF 계정; A는 두 HF 계정 연결 | 로그인/연결 identity 유지, 계정 선택대로 접근, 타 사용자 토큰·자료·cache 접근 거절 |
| 초대 없는 로그인, 위조 callback/state, 이메일만 같은 외부 계정 | 자동 가입/계정 합치기 거절, 기존 로그인 수단 유지 |
| public/private/gated dataset 각각 가져오기 | 권한/이용 조건 구분, 개인 gated 승인으로 팀 공유 불가, 고정 revision/해시 readback |
| 다운로드 중 만료/연결 해제/팀 탈퇴, 서버 재시작 후 재시도 | 자동 계정 대체 없음, 부분 자료 미등록, 권한 재검사 및 같은 revision 재개 |
| A/B가 같은 라벨 수정·승인 | stale revision 충돌, 최신 근거의 승인만 적용, 과거 dataset 불변 |
| 영상만 있는 자료와 동기화된 암 시연 | 영상 이해는 조건 충족 시 허용, 행동 없는 모방 학습 거절, 단위/시계 오류 거절 |
| 기존 v1 자료와 새 profile, 재인코딩된 같은 session | 기존 reader 회귀 통과, 원본 SHA 불변, 같은 split 그룹 유지 |
| LeRobot 실제 reader 및 학습/추론 동일 입력 | frame/episode/단위/정렬·전처리 일치, 손실/누락 보고서 보존 |
| 모델/자료 가져오기 완료 | 등록/평가와 실행 승인 상태 별도 표시, 자동 로봇 명령·외부 게시 없음 |

현재 증거는 저장소 계약/변환기와 공식 문서 검토 및 이 ADR의 문서 검사에 한정한다.
실제 OAuth 등록·복수 계정 로그인·다운로드·공동 검수·GPU 학습·장치 시험은 후속 구현이다.
사람 승인 정답과 독립 평가 자료가 쌓이기 전에는 합성 시험을 실제 학습 품질로 보고하지 않는다.

### References

공식 문서 확인일: 2026-10-14. provider 기능과 scope는 구현 시 다시 확인한다.

- [Hugging Face OAuth/OIDC](https://huggingface.co/docs/hub/oauth): 로그인, scope 및 조직 접근 동의.
- [User access tokens](https://huggingface.co/docs/hub/security-tokens): 제한된 자원별 자격증명.
- [Gated datasets](https://huggingface.co/docs/hub/datasets-gated): 접근 승인은 개인별이며 조직 전체 승인 아님.
- [LeRobotDataset v3](https://huggingface.co/docs/lerobot/lerobot-dataset-v3): 저장 구조와 reader.
- [Dataset Cards](https://huggingface.co/docs/hub/datasets-cards): 자료 설명·용도·제한·license.
