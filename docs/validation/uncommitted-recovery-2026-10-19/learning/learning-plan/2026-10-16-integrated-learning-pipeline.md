# 통합 Learning 파이프라인 구축·검증·공수 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement the approved sub-project plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로컬·HF 자료/모델 확보부터 전처리·검수·학습·독립 평가·모델 보존/게시까지 기존 Learning 웹에서 추적하고 실행한다.

**Architecture:** 공통 workflow 원장과 참조 카탈로그가 기존 import·검수·학습·평가·registry 소유자에 작업을 인계한다. 원본 파일 형식, 고정 revision, 기존 승인·실행 권한은 소유 모듈에 남긴다. 인지 흐름을 먼저 종단 연결하고 native IL과 제한 SIM RL을 단계별로 추가한다.

**Tech Stack:** 기존 Python 서비스·정적 web components·SQLite·systemd 실행기·별도 CPU/GPU 환경, 기존 HF 연결/전송·LeRobot·Isaac adapter. 기존 loader와 호환되는 환경을 고정하며 제품 런타임에 학습 의존성을 설치하지 않는다.

**Spec:** [D-771 ADR](../adr/D-771-integrated-learning-pipeline-ownership.md).

**상태:** 2026-10-16 사용자가 전체 목표 완주와 목표 갱신을 지시하여 실행을 재개했다. 기준 소스 `436d52a55`, 브랜치 `docs/integrated-learning-plan`. 기존 P0–P7 범위를 유지하며 전체 종단 파이프라인은 아직 완료하지 않았다. 목표 도구는 다시 활성 상태다. 실행 목표와 완료 판정은 아래 전체 범위와 단계별 수용 기준을 따른다.

**목표 재확정 — 2026-10-17:** 사용자 요청에 따라 녹화·로컬/HF 데이터 관리·라벨링·전처리·학습·독립 평가·모델 산출/보존을 기존 웹에서 이어 실행하는 P0–P7 전체 완주를 추적한다. 목표 도구의 활성 항목명은 `re`이며 활성 목표의 objective를 수정하는 포트는 없다. 이름 변경을 위해 미완료 목표를 완료 처리하지 않는다. 이 문서의 Goal·완료 기준이 실행 범위의 정본이다. 저장소·worker 회귀와 실제 HTTP→worker→모델 등록의 제한된 수용을 확인했다. 현재 우선순위는 R2 decoder 종료 소유권 보완과 owner·catalog·웹 연결, 실제 데이터/평가/기반 모델 계보의 연결이다. 이후 R3–R5 reader, IL/RL adapter, 독립 평가·registry·HF 게시/복원과 P7 수용까지 이어간다.

### 완료 기준과 실행 순서

완료는 ADR 작성이나 공통 기반 구현만으로 판정하지 않는다. 기존 Learning 웹에서 아래 흐름을 실행하고 원격 검증 증거를 남긴 뒤 P0–P7 수용 조건을 모두 대조한다.

1. 로컬·HF 자료와 모델을 확보하고 원본, 고정 revision, 권리, 저장 공간과 계보를 관리한다.
2. 자료 종류별 실제 reader 검사, 전처리, 사람 라벨 검수, 분리된 학습·평가 데이터셋을 연결한다.
3. 인지 학습을 먼저 연결하고 native IL과 기존 제한 SIM RL에 같은 작업 추적·자원 예약·취소·재시작 규칙을 적용한다.
4. 독립 평가 결과를 모델 산출물·환경·데이터 revision과 함께 registry에 보존하고 선택적 게시·복원을 검증한다.
5. 실제 브라우저 동선, 권한 회수, 실패·응답 유실·취소·재시작을 시험한다. 운영 설치·실물 활성화는 별도 승인 경계로 남긴다.

현재 우선순위는 완료한 PNG/JPEG reader·카탈로그·웹 연결에 이어 기존 인지 전처리·검수·학습 소유자를 하나의 실행 흐름으로 묶는 것이다. 기반 보완이 끝난 항목을 반복 검증하는 대신 새 실패나 변경이 있는 범위만 추가 검증한다.

### 구현 체크포인트

- 공통 asset-ref 계약과 프로젝트별 SQLite 카탈로그, workflow submit/adopt·취소·결과 검증을 구현했다. 현재 API와 한계는 [catalog](../../learning/registry/catalog/README.md), [pipeline](../../learning/pipeline/README.md)에 기록한다.
- 등록된 Linux 로컬 root에서 원본을 보존하고 파일 hash·복사본을 검증한 뒤 atomic finalize하는 acquisition owner를 구현했다. 부분 산출물과 실패 lock은 명시 복구 대상으로 남긴다.
- 기존 HF importer에 프로젝트/요청자/request key별 영속 매핑, queued attempt, 실제 종료 확인과 취소 CAS를 추가했다. read-only owner 검증은 manifest·선택 파일·media 증거를 다시 읽으며 현재 실행과 원본 산출 attempt를 구분한다.
- 기존 인증 Learning 웹에서 등록 root 선택→원본 보존 복사→실제 hash 검증→카탈로그 조회를 연결했다. Chromium에서 응답 유실 재시도와 로그아웃 후 입력 제거까지 검증했다. byte 검증과 reader 미확인을 따로 표시한다.
- `442785599`의 공통 workflow·실제 HF owner adapter·기존 import/복구 회귀와 `8b3f8a1d4`의 카탈로그 결합·모듈 검사는 원격 exit 0, known-failure 비교 0 NEW다. 취소/완료 경합과 목적지 store 변경을 재현한 뒤 수정했다. 외부 HF 호출은 fixture이며 실제 계정 전송이나 GPU 학습 증거가 아니다.
- `23df1071c`의 HF 실행 생성·조회·진행·취소, 원 요청자 권한, 실제 기존 executor→owner 검증→자산 등록 HTTP 회귀는 원격 exit 0, 0 NEW다. `a7ab8fe1c`의 로컬/HF Chromium 동선과 기존 키보드 실행 제어 14건도 원격 통과했다. 계정 전환과 유실 응답 재시도, 취소 종료 대조를 포함한다.
- `1e6a94248`의 공통 볼륨 예약 원장과 실제 importer 연결, 손상 row·부분 파일 재개·깊은 경로의 준비 전 예약·현재 설정 로딩·기존 회귀와 구조 검사는 원격 exit 0이다. 같은 볼륨의 여러 importer를 합산한다. `812904a55`의 실제 로컬 복사 연결도 원격 174건, 0 NEW를 확인했다. 독립 검토에서 추가 발견한 명시 null 설정 우회와 서로 다른 native lease의 owner ID 충돌은 실패 시험으로 재현하고 `196248d6b`·`8593aceb0`에서 수정했다. 실제 HF/local 양방향 경합·손상 domain 원장·기존 회귀·구조 검사가 원격 exit 0, 0 NEW이며 독립 재검토를 통과했다. GPU/CPU 예약은 아직 연결하지 않았다.
- `73b666fb7`의 선택적 native 제출 취소 포트는 준비 입력 저장 뒤 native commit 전 장애를 다룬다. 같은 키의 취소 기록을 원 소유자가 영속화하고, 이후 동일 키의 제출을 차단한다. 실제 HF 포트는 `fc98537d0`에서 연결했고 공통 workflow·native HF·웹 회귀 241건이 원격 통과, 0 NEW이며 독립 재검토를 통과했다. 현재 HF 연결 세대·실행 바인딩 변경 시 workflow 취소가 거절되는 경우는 후속 stop 계약에서 해소해야 한다.
- `f8da53a6b`의 nullable reader 증거 투영·원자적 catalog v2 전환은 기존 workflow/웹을 포함한 403건 원격 회귀와 독립 검토를 통과했다. `f67313a90`의 실제 PNG/JPEG 제한 프로세스·메타데이터 사전 검사·sealed reader receipt·로컬 증거 보존도 관련 통합 회귀 exit 0, 0 NEW다. 증거 저장 중 원본 변경을 다시 확인하며, 역사 조회는 예약을 회수하지 않는다. HF reader와 native 증거→catalog→웹 버튼도 연결했다. `70f88ed40`의 native/local/HF bridge·workflow·Chromium 67건과 `417ab2846`의 실제 계정·executor를 통한 HF HTTP·로컬 계정 전환·브라우저·구조 검사 207건이 원격 통과했고 0 NEW다. R2–R5 reader와 학습 연결은 남아 있다.
- 공통 모듈 등록과 HEAD 파일 크기 검사는 통과했다. 개발 이력의 중간 커밋에 파일 크기 위반이 남아 있어 전달 브랜치의 이력 검사는 별도로 필요하다. 전체 CI·운영 수용으로 표시하지 않는다.
- 후속 stop 계약에서 HF의 원 요청·attempt 조회와 취소를 시작 자격 검증에서 분리했다. 연결 세대·코드/환경·store 변경 후에도 원 작업만 취소하고 실제 lease 종료를 대조한다. 정상 queued 인계·결과 수용에는 현재 자격 검사를 유지한다. `a9c0e199b` 관련89건 원격 회귀와 독립 검토를 통과했고 0 NEW다. 앞선 미해결 stop 항목은 이 구현으로 해소했다.
- 인지 실행 연결용 실제 systemd/proc/cgroup 관측·정확한 supervisor pidfd 종료 포트는 `03a61b990`의 티켓·선택 cycle 포함104건 원격 회귀, 0 NEW와 독립 검토를 통과했다. 서명 소스 보존·엄격 실행 검사는 `90a2c8fff`에서 실제 자식 실행·변조38건 및 기존 실행기 회귀를 통과했다. 환경 검사 중 소스 변경 결함은 RED 후 수정했다. 이 포트들의 웹 단일 티켓·권한 broker·자원 연동은 아직 남아 있다.
- 후속 live Account broker·제한 Unix socket은 `3a997b1aa`에서 process/ticket 포함117건 원격 회귀, 0 NEW다. 실행 감독·결과 기록 중 권한 만료는 `6880b51d5`의16건 원격 회귀를 통과했다. 독립 검토에서 발견한 실제 client/broker의15초 기산 시점 차이는 실제 소켓 통합 시험으로 재현하고 `469003744`에서 수정했다. 같은 revision의 고정 단일 티켓 CLI·감독·기존 실행기·소스 증거224건과 `bf48ccb8c`의 binding/ticket/구조138건이 원격 통과, 0 NEW다. native owner·자원·worker·웹의 실제 연결은 계속 구현 중이며, 이 포트 시험으로 인지 학습 종단을 완료 표시하지 않는다.
- `078162cb9`의 worker·trainer guard44건과 정확한 물리 실행의 종료 결과·process·native owner75건이 원격 통과, 0 NEW다. worker는 실제 native Job의 train/export receipt와 모델·manifest·parity를 함께 봉인한다. candidate 읽기 전용 수용 포트는 18건의 미구현 RED 후 `d4994659e`에서 구현했으며, worker·종료 결과를 포함한61건이 원격 통과, 0 NEW다. 같은 원본 범위의 dependency/folder/구조/harness/network 계약172건도 통과했다. native 완료 CAS, 서비스 수거 전 종료 증거 확보, [쓰기 진행량 예약](2026-10-17-perception-storage-progress.md), 웹 연결이 남아 있다. 시험의 학습 수치·GPU·systemd 관측 대체 경계는 실제 학습 또는 설치 수용 증거가 아니다.
- 다음 작업은 [종류별 reader](2026-10-16-acquired-asset-readers.md)와 [로컬 확보 예약](2026-10-16-local-acquisition-admission.md)의 독립 검토 보완·GPU/CPU 공통 예약, [인지 native 실행 연결](2026-10-16-perception-native-workflow.md)이다. 인지 학습 종단, IL/RL adapter, 게시/복원과 전체 브라우저 E2E는 미완료다. 아래 단계 체크박스는 일부 기반 구현만으로 완료 표시하지 않는다.
- 후속 `16cc0a819`의 마지막 검증 I/O 뒤 권한 재확인·완료 CAS·권한 회수 후 terminal 정리106건, `3ed438cad`의 실패 뒤 scratch 정리·입력별 읽기 lease52건이 원격 통과, 0 NEW다. 실제 검수 재구성·입력 복사는 `555a6f9e6`에서 연결했다. 교차 검토에서 찾은 마지막 context 정리 실패 뒤 성공 표시 결함은 두 건으로 재현하고 `1ccf3252b`에서 수정했다. 검수·완료 회귀181건 통과와 Windows 전용2건 skip, 0 NEW를 확인했다.
- `da1eba74b`의 격리 CPU 환경에서 실제 PyTorch checkpoint·ONNX 저장/재적재와 용량 상한 거절4건이 원격 통과, 0 NEW다. 격리된14개 wheel과 실제 import·native 파일의 hash를 기록했고 기존 환경은 유지했다. 실제 trainer 경로 전체, GPU 학습 또는 설치 모델 PC 수용 증거로 확대하지 않는다.
- native reference 유지·종료 증거 보존의 orphan proof 복구는 `4302ff050`의117건 원격 회귀를 통과했다. 공통 인지 adapter의 완료 후 출력 훼손과 취소 대조는 `ccc7f9a6f`의 관련53건을 통과했다. `86d7edd66`의 실패 증거·active reference 복구 포트는 기존 완료/ticket/process를 포함한206건 원격 회귀, 0 NEW다. 교차 검토에서 찾은 공개 재부팅/취소 복구 경로와 앱 시작 시 실제 복구 호출은 별도 회귀로 보완 중이다. 원격 관측 fixture 결과를 설치 서비스 또는 실제 GPU 학습 수용으로 확대하지 않는다.
- bounded metadata 쓰기·저장소 예약84건과 실제 CPU trainer의 checkpoint/ONNX 저장 경로를 연결했다. 초기 worker 통합 `7721f71a4`144건의21건 실패는 supervisor 갱신·쓰기 guard 비용·시험 대기 경합·일반 학습 오류 처리에 걸쳐 수정하고 아래147건으로 다시 검증했다. P2/P3 전체는 미완료다.
- `9d865ab62`의 실제 앱 runtime·기존 HTTP 원장·native owner 완료 검증·모델 catalog·Chromium37건은 원격 exit 0, skip 0, 0 NEW다. 요청자별 현재 권한, private 선택 항목과 공개 응답 분리, 실제 reference 재부착, 시작 실패 rollback과 caller 소유 Jobs 보존을 포함한다. 모델 파일과 systemd 관측은 명시 fixture 경계이며 실제 worker의 학습 산출물이 웹까지 이어졌다는 증거는 아직 아니다. worker 저장소 통합의 실패를 계속 해소하고 R2 동영상 reader는 별도 tests-first 단계로 진행한다.
- 저장소 통합의 후속 `bd83f0a1b`147건은 원격 통과, skip 0, 0 NEW다. 실제 CPU trainer의 저장·상한·실패 경계6개 시나리오도 `96049836d`에서 통과했다. 일반 학습 오류가 저장소 장애 latch로 오분류되어 원래 실패 상태 기록을 막는 결함은 재현 후 수정했다. `69d04c687`의 웹→동일 native worker→원래 Job/outcome→검증→모델 등록 및 실행 중 Account 권한 회수2건도 원격 통과, skip 0, 0 NEW다. 수치 학습·kernel/systemd 관측은 명시 fixture 경계다. 추가 브라우저 회귀의 사진 배치2건은 변경 없는 main `664b101fa`에서도 실패했다. reader/키보드 시험의 로딩 경합을 보완한 `23ce61d26`13건은 원격 통과, skip 0, 0 NEW다. R2 decoder/receipt와 기존 R1 회귀 `e8a11bc57`182건도 통과했으나 후속 검토에서 발견한 child reaper 경합은 별도 실제 RED 후 보완 검증 중이다. R2 owner·catalog·웹 연결은 아직 남아 있다.

### 설치 환경 확인 — 2026-10-16, 읽기 전용

private host 목록의 모델·AI·현장 PC를 SSH로 조회했다. 서비스 시작/중지, 설정 변경, 학습 실행은 하지 않았다. 장치 주소·계정·private 경로는 기록하지 않는다. 시점 관측이며 예약 또는 미래 가용성 증거가 아니다.

| 확인 대상 | 관측과 구현 영향 |
|---|---|
| 모델 PC | Python 3.12.3, systemd 255.4, cgroup v2. RTX 5080 Laptop GPU, 약 16 GiB. 기존 `rosy-review-pipeline.timer`는 enabled/active waiting, service는 inactive였다. 새 단일 티켓 template은 not-found다. 제출 활성화 전 기존 timer의 명시적 인계가 필요하다. |
| 검수 소유자 | `rosy-review-v13.service` active/running, review bridge와 release-update timer active/waiting. GPU 학습 인계가 이 검수 bridge를 중단시키지 않아야 한다. |
| 기존 model-code 원장 | sequence 29, pending=false, 기록된 source `faea4101cd68cbc45896ec74a564dae3927122e4`, environment `97fab2525162e8b93ae730e6c1426ca7c84e07afc0821856ba4e31dccb1412eb`. state bytes SHA256 `7be9eae08e0ae9caad26003b89c46f250869e9a5e25c9cf98dfec1ddf6b7b108`. 이는 원장의 선언을 읽은 것이며 설치 소스 전체·서명·현재 환경을 새로 검증한 증거가 아니다. |
| AI PC | Python 3.12.3, systemd 255.4, cgroup v2, 같은 GPU 계열. 조회 순간 GPU 사용량 약 10 GiB; 기존 Learning timer와 새 template은 not-found였다. 공유 GPU를 전용 학습 자원으로 간주하지 않는다. |
| 현장 PC | Python 3.14.4, cgroup v2. 조회한 Learning unit은 not-found였다. GPU 학습 실행 대상으로 삼지 않는다. systemd 버전 조회는 미확인이다. |

원본 JSON은 개발 PC의 저장소 밖 `rosy-learning-pipeline/installed-baseline-20261016.json`과 `installed-learning-owner-20261016.json`에 보관했다. P0의 실제 데이터 규모·NAS/HF quota·권한·새 owner 설치·자원 인계 확인은 남아 있다.

## Global Constraints

- 기존 MediaManifest/Episode/DatasetManifest/PolicyArtifact와 perception manifest를 유지하며 exact-field schema에 임의 필드를 추가하지 않는다.
- 일반 영상에서 행동값·시계·camera calibration을 추정해 채우지 않는다. unknown은 검증까지 유지한다.
- train/eval은 session/source group과 원본 계보로 분리한다. 학습 시작·결과 수용에 현재 검수·권한을 다시 확인한다.
- 원본·이전 dataset·model을 덮어쓰지 않는다. 작업 실패의 부분 산출물과 원장은 보존한다.
- Learning이 Fleet 원장·CORE 최종 명령·OMX owner 권한을 얻지 않는다. 모델 게시·승격·설치·활성화를 구분한다.
- 외부 파일 게시에는 사용자/프로젝트/선택 연결·대상 repo·파일 manifest가 결합된 명시 요청이 필요하다. 본 계획 작성은 외부 게시 요청이 아니다.
- 기존 D-446 실행/자원 잠금과 D-742 현재 검수 전달을 보존한다. 검수 bridge는 GPU 학습과 독립적으로 갱신한다.
- 노트북에서 pytest를 실행하지 않는다. 커밋된 작업 브랜치를 `tools/remote/remote_pytest.py`로 검사하고 `test/known_failures.py`로 NEW를 확인한다.
- 새 holder·API·권한·계약은 module ownership·ADR/API reference·호환성 시험을 함께 확정한다. merge/push·운영 배포는 별도 요청 범위다.

## Review Focus

1. 웹 재시작·응답 유실 뒤 기존 worker가 계속 돌 때 중복 학습/게시가 시작되지 않아야 한다 — P2/P7.
2. 원본의 재인코딩·클립 분할·라벨 철회가 평가 누수나 과거 모델의 조용한 재승인을 만들지 않아야 한다 — P1/P3/P6.
3. 사용자 A의 HF 연결/ambient cache가 사용자 B의 게시·다운로드에 사용되지 않아야 한다 — P1/P6.
4. 데이터·checkpoint·변환 임시본이 같은 볼륨을 사용할 때 동시 작업 예약과 crash 복구가 용량을 이중 계산하지 않아야 한다 — P2/P6.
5. native OMX, SIM ACT, 위치 기반 RL, 카메라 기반 RL의 서로 다른 단위·입력·평가가 한 성공 상태로 합쳐지지 않아야 한다 — P4/P5/P7.

## 1. 제품에서 완성할 사용자 흐름

사용자는 먼저 과제와 모델 역할을 선택한다. 예를 들어 현재 구역 인지, 객체 검출,
OMX 시연 모방, 제한된 SIM 제어를 구분한다. 데이터·기반 모델을 검색/등록한 뒤
호환성·준비 상태·보관 위치를 보고, 전처리 recipe와 라벨 검수를 이어서 수행한다.
승인한 데이터셋 revision으로 실행할 수 있는 학습 recipe만 보여 준다.

실험 화면은 입력 모델/자료/환경, 대기 이유·진행·로그·실제 attempt를 표시한다.
완료하면 평가 기준선과 비교하고, 모델 상세에서 원본 녹화까지 역추적한다.
선택한 모델을 로컬에 보존하거나 private HF로 게시하고, 운영 적용은 기존 수용 흐름에 인계한다.

| 화면 영역 | 사용자에게 답해야 하는 질문 | 첫 구현 |
|---|---|---|
| 프로젝트·과제 | 무엇을 학습하며 성공 기준은 무엇인가? | task/profile·목표·평가 세트·담당자 |
| 자료·저장소 | 어떤 데이터가 어디에 있고 어떤 단계에 쓸 수 있는가? | 로컬/HF 출처, 검증·사본·용량·전송 상태 |
| 전처리·검수 | 어떤 변환과 라벨을 누가 만들었고 무엇이 남았나? | 기존 객체/픽셀 UI, 작업·원본 연결, 시연 검토 |
| 데이터셋 | 어떤 승인 snapshot과 split으로 고정했나? | 내용 revision, source group·클래스 분포·제외 이유 |
| 실험 | 어떤 코드·모델·데이터·GPU로 실행되고 왜 멈췄나? | recipe, worker 관측, retry/cancel, 로그·metrics |
| 모델 | 무엇을 확보·학습했고 어느 환경에서 쓸 수 있나? | 역할·파일 묶음·평가·부모 계보·게시·수용 상태 |

표의 영역은 사용자 정보 구조다. 반드시 6개 신규 독립 앱/서버를 만든다는 뜻은 아니다.

## 2. 재사용과 새 구현의 경계

| 기존 경로 | 재사용할 책임 | 추가 작업 |
|---|---|---|
| `learning/curation/perception/learning_imports.py`, `learning_accounts.py` | 계정·고정 HF 입력·native import 작업 | 공통 작업과 native ID 연결, 크기 제한 확장, reader adapter |
| `learning/curation/perception/storage_inventory.py` | 등록 root 관측·사전 점검 | 예약 원장 연결·미확인 표시·snapshot 추세 |
| `learning/curation/perception/review_app.py`, `review_app_web/` | 기존 Learning 웹·검수 라우팅 | 자산/실험/모델 흐름·계보·실제 작업 상태 |
| `learning/curation/perception/review_*.py`, `learning/training/perception/review_pipeline.py` | 검수 권한·snapshot·dataset 준비 | 통합 adapter와 단계 결과 참조 |
| `learning/registry/perception/store.py`, `learning/registry/policy/` | 고정 산출물·원장·HF bundle | 카탈로그 참조·소유자 권한 유지·게시 adapter |
| `learning/curation/omx/`, `learning/training/omx/`, `learning/training/pinky/` | 개별 형식·단위·실행기 | capability별 IL adapter·시연 상태 UI |
| `learning/envs/isaac/`, `tools/sim/isaac/` | 제한 SIM 진단·정책·trace | 기존 진단의 공통 실행·결과 adapter |
| `deploy/model_pc/` | 서명 코드·systemd·host 설정 | 작업 인계·재조정·배포/복구 runbook |
| `contracts/learning/` | 기존 자료·정책 의미 | 새 sidecar/참조 계약의 호환성 검증 |

새 후보 holder는 `learning/pipeline/`와 `learning/registry/catalog/`다. P0에서 기존
module registry와 dependency 규칙에 맞춰 등록한다. 전면 폴더 이동·범용 plugin framework는
첫 연결에 필요하지 않다. CLI 도구의 실제 작업은 유지하고 adapter는 인계·상태·결과를 다룬다.

## 3. 단계별 산정과 의존성

1인일은 개발·검토·자동 검증을 포함한 엔지니어 1명의 집중 작업일이다. 기존 모듈을 재사용하는
가정의 초기 범위 추정이며 실측 견적이 아니다. P0에서 실제 배포·용량·host 환경과 충돌을 확인해
재산정한다. 데이터 수집·사람 라벨링·실제 GPU 학습 대기·정책 품질 개선은 별도로 계산한다.

| 단계 | 납품 범위 | 의존 | 기본 인일 |
|---|---|---|---:|
| P0 | 계약·현황·소유권·첫 과제와 수용 fixture 고정 | 없음 | 3–4 |
| P1 | 자료·모델 참조 카탈로그, 로컬/HF 확보·reader 검증 | P0 | 7–10 |
| P2 | 공통 run/attempt·native owner 인계·자원 예약·재조정 | P0, P1 참조 계약 | 8–12 |
| P3 | 인지 전처리·라벨·dataset·학습·평가 종단 연결 | P1, P2 | 8–12 |
| P4 | native OMX / SIM ACT / Pinky 연구 adapter와 시연 흐름 | P1, P2, P3 패턴 | 7–10 |
| P5 | 기존 제한 Isaac RL 진단의 실행·평가·trace 통합 | P2, P3 패턴 | 6–9 |
| P6 | 계정 결합 HF 게시·reader 왕복, 보존·영향·복원 | P1, P2; 모델 검증은 P3 | 6–9 |
| P7 | 공통 화면 완결·기존 자료 이행·장애/E2E·운영 runbook | P3–P6 | 7–10 |
| **합계** | **지원하는 3개 학습 계열의 통합 첫 릴리스** | | **52–76** |

25% 통합 여유를 포함해 **65–95인일**로 잡는다. 담당자 1명은 약 13–19주,
숙련된 개발자 2명과 검수/ML 담당의 협업은 선행 관계·통합 대기를 고려해 약 9–13주다.
후자는 2명 공수를 단순히 반으로 나눈 약속이 아니다. 검수·ML 담당의 실제 라벨 작업 인일은 제외다.

첫 인지 종단 릴리스는 P0–P3와 P6의 private 게시/왕복 부분(3–5인일)을 먼저 묶는다.
기본 29–43인일, 여유 포함 **36–54인일**, 위 2명 조건에서 **5–7주**를 초기 목표로 잡는다.
웹의 기본 진행·오류·검수 동선은 각 P에 포함되며 P7까지 미루지 않는다.

| 추가 범위 | 추가 기본 인일 | 선행 조건 |
|---|---:|---|
| D-769의 새 Pinky Gazebo 학습 실행기·평가기 | 10–18 | 인지/주행 진단·applied action·stop/reset 계약 수용 |
| OMX SIM RL 조사·과제/보상/환경 설계 | 3–5 | 기존 OMX 과제·rig·시연·baseline 확정. 구현은 조사 후 별도 산정 |
| 두 번째 대용량 저장 provider(NAS/S3/HF Bucket 중 하나) | 4–7 | 원본 보존·snapshot·인증·복원 조건 결정 |
| MLflow 실험 비교 adapter | 3–5 | 공통 run/metric 계약. 기존 registry 단계는 계속 정본 |

추가 범위를 본 합계에 중복 계산하지 않는다. 특히 기존 Isaac 연결을 완료했다고 Gazebo/Fleet RL이나
OMX RL까지 완료로 선언하지 않는다. 첫 릴리스 범위는 구현된 adapter의 종단 동작과 장애 복구다.

## 4. 단계별 실행·수용 작업

### P0 — 계약과 실제 기준선

소유 경로: `docs/adr/`, `docs/plans/`, `tools/harness/platform_parts.yaml`, `contracts/learning/`.
소비: D-771와 기존 ADR·소스·설치 설정. 산출: 승인된 참조/adapter 계약·module 책임·표본 fixture·하위 실행 계획.

- [ ] 현재 설치 버전·서비스/타이머·자료 root·DB·GPU 잠금·import 제한을 읽기 전용 점검하고 소스와 차이를 기록한다.
- [ ] 첫 인지 과제와 기존 모델·평가 세트를 선택한다. local/HF 표본·외부 계정 연결의 실제 접근성을 확인한다.
- [ ] asset ref, run/step/attempt, native job reference, observation/event, resource reservation의 버전·writer·CAS 규칙을 확정한다.
- [ ] owner별 register/inspect/start/status/cancel/collect/verify 포트와 지원 capability를 명시하고 exact API/schema를 별도 계약 변경으로 기록한다.
- [ ] P1–P7을 각각 실행 가능한 작은 계획으로 분해한다. 서비스 인계·되돌림과 개발자별 소유 파일을 고정하고 공수를 재산정한다.

수용: 모든 자산·상태에 쓰기 소유자가 하나 있고, 첫 과제의 시작 자료부터 산출 모델까지 필요한 경로·권한·입력이 확인된다.
실계정/실데이터가 없으면 해당 live 수용을 미확인으로 남기고 합성 fixture 개발과 구분한다.

### P1 — 자산과 확보

소유 경로: 후보 `learning/registry/catalog/`, 기존 imports/accounts/curation, `contracts/learning/`.
소비: P0 참조 계약·기존 owner manifest. 산출: 고정 자산 참조·사본 위치·형식 검증·권한 상태.

- [ ] 기존 native revision을 바꾸지 않는 catalog projection과 owner adapter를 구현한다. 전체 색인 재구축을 검증한다.
- [ ] 관리자가 등록한 root에서 local staging·hash 검사·atomic 등록을 수행하고 원본 변경·링크/경로 이탈을 거절한다.
- [ ] 기존 HF native job ID와 공통 run을 연결한다. 미완성 전송·unsupported 형식을 acquired/pending으로 표시한다.
- [ ] image/video, Episode/LeRobot, model bundle의 서로 다른 reader/loader 검사를 연결한다. 기존 import 크기 한계를 실측 표본으로 재설계한다.
- [ ] 자산 목록에서 출처·용도·가용 사본·미검증 이유·기반 모델 호환성을 확인한다.

핵심 시험: `catalog_rebuild_keeps_native_revision`, `source_changes_during_local_copy`,
`actionless_media_cannot_enter_il`, `import_revoked_connection_no_fallback`, `partial_import_not_registered`.
완료는 파일 다운로드만이 아니라 종류별 reader 증거가 있는 준비 상태와 미지원 이유를 정확하게 보여 주는 것이다.

### P2 — 작업과 자원

소유 경로: 후보 `learning/pipeline/`, `deploy/model_pc/`, 기존 `learning_control.py`와 import job adapter.
소비: asset ref·실행 capability. 산출: workflow 상태·native invocation 연결·자원 예약·실제 종료 확인.

- [ ] durable run/attempt·의존 단계와 사용자/project 권한을 구현하고 입력/recipe/worker code/environment를 고정한다.
- [ ] 기존 importer queue와 systemd service의 native identity를 기록한다. 관측→위임/스케줄 소유 인계를 명시적으로 수행한다.
- [ ] 중복 요청·timer 동시 발화·취소·응답 유실에서 native 실행이 한 번만 시작되도록 조정한다.
- [ ] CPU/GPU/디스크 예약을 기존 잠금과 결합한다. 검수 대기 중 GPU를 놓고 authority bridge는 계속 갱신한다.

CPU/GPU의 첫 구현은 [공통 host compute admission](2026-10-16-learning-compute-admission.md)의
DB 전체 단일 슬롯을 사용한다. 기존 D-446/GPU 잠금과 실제 서비스 한계·여유 관측을 결합하고,
native IL·Isaac도 같은 슬롯에 연결한다. CPUQuota/MemoryMax나 파일 잠금만으로 예약 완료를
표시하지 않는다.
- [ ] coordinator/worker 재시작 시 native 실행·receipt·output을 대조한다. unknown을 성공/실패로 추정하지 않는다.

핵심 시험: `timer_and_http_start_one_attempt`, `web_restart_reattaches_worker`,
`worker_commit_before_ack_reconciles`, `stop_available_with_corrupt_ledger`,
`shared_volume_reservation_no_overcommit`, `stale_attempt_cannot_publish`, `bridge_refresh_during_gpu_job`.

### P3 — 첫 인지 종단 흐름

소유 경로: `learning/curation/perception/`, `learning/training/perception/`,
`learning/evaluation/perception/`, `learning/registry/perception/`, 기존 Learning 웹.
소비: local/HF asset refs·run/attempt·현재 검수 결정. 산출: frozen dataset·실제 모델 bytes·평가·모델 ref.

- [ ] 녹화 수신→변환→frame 선택→초안 라벨→기존 검수의 단계를 같은 작업/계보에 연결한다.
- [ ] 현재 검수 snapshot·클래스와 session/source group split을 고정하고 파생 중복에 의한 평가 누수를 거절한다.
- [ ] 기존 ReviewPipeline에 인계해 학습·평가·재적재·변환 산출물을 수집하고 registry ref로 등록한다.
- [ ] 실패 단계부터 지원되는 재시도, 라벨 수정 후 새 dataset/run 생성, 완료 모델에서 원본 역추적을 UI로 제공한다.
- [ ] 실제 독립 표본으로 전 과정을 실행하고 GPU 결과·판정·한계를 기록한다. 모델 품질 거절도 정상 종단 결과로 보여 준다.

핵심 시험: `reencoded_clip_cannot_leak_to_eval`, `review_revoked_before_admission`,
`changed_receipt_cannot_resume`, `trained_artifact_reloads`, `model_lineage_reaches_capture`.
P6의 게시 부분을 함께 적용하면 첫 릴리스의 local→HF 고정 commit→loader 왕복까지 수용한다.

### P4 — 시연·모방학습

소유 경로: `learning/curation/omx/`, `learning/training/omx/`, `learning/training/pinky/`, policy registry, 기존 웹.
소비: 검증된 Episode/native dataset·학습 환경. 산출: profile별 학습 결과·정규화/processor·독립 평가·policy ref.

- [ ] 기존 [OMX 통합 설계](2026-10-15-omx-learning-operations-design.md)의 시연 검토·native LeRobot 준비를 재사용한다.
- [ ] native 공식 CLI, SIM ACT, Pinky comparison을 별개 adapter로 등록한다. native 입력을 SIM rad 계약으로 해석하지 않는다.
- [ ] 구간·행동/관측 시각·joint 순서/단위·카메라/rig·성공/실패 검토 결과를 dataset에 결합한다.
- [ ] checkpoint capability에 맞게 재시작하며 기존 ACT 실패는 새 output/attempt로 기록한다.
- [ ] 정책·pre/postprocessor·정규화 파일을 새 프로세스에 재적재하고 연구/실물 수용 상태를 구분한다.

핵심 시험: `native_actions_rejected_by_sim_adapter`, `episode_group_split_preserved`,
`act_retry_new_output`, `processor_bundle_reloads`, `training_does_not_activate_robot`.
실물 시연 수집·정책 성공률 개선은 통합 개발 완료와 별도다.

### P5 — 제한 SIM RL

소유 경로: `tools/sim/isaac/`, `learning/envs/isaac/`, 공통 pipeline adapter, 기존 웹.
소비: 고정 SIM 환경·task/reward/seed·필요한 인지 model ref. 산출: 실제 학습 update·정책·독립 eval·trace/video.

- [ ] 현재 실행 가능한 Isaac 진단의 capability와 실제 전제 조건을 등록한다. 미구현 Gazebo/OMX 기능은 실행 선택지로 열지 않는다.
- [ ] 환경/지도/보정/인지 모델·보상·reset·종료조건 revision과 train/eval seed를 run에 기록한다.
- [ ] 소유 runtime에서 stop/reset·epoch·실제 적용 action을 확인하고 학습/고정 평가를 분리한다.
- [ ] 정책·trace·video·실패 이유와 학습 없는 baseline 결과를 같은 실험에 연결한다.
- [ ] D-769 새 Gazebo runner는 별도 구현/수용 작업으로 계획하고 기존 진단의 성공을 대체 증거로 쓰지 않는다.

핵심 시험: `frozen_eval_cannot_update_policy`, `reset_requires_stop_receipt`,
`rejected_action_not_credited`, `camera_and_pose_results_distinct`, `rl_cancellation_releases_owned_resources`.

### P6 — 게시·보존·복원

소유 경로: `learning/registry/policy/hub_sync.py`, accounts/import adapter, catalog, storage inventory, 배포 runbook.
소비: 검증된 asset/model bundle·선택 HF 연결·권한. 산출: 고정 게시 commit·reader receipt·영향 목록·복원 증거.

- [ ] payload hash·대상·가시성·계정을 결합한 게시 preview와 명시 요청을 구현한다. ambient credential fallback을 없앤다.
- [ ] 기존 bundle/parent commit/readback을 재사용하고 실제 dataset reader/model loader 결과를 byte 검증과 별도로 기록한다.
- [ ] 게시 후 응답 유실 재시도는 같은 commit을 재검증한다. 부분 게시/취소 상태와 외부 commit을 이력에 남긴다.
- [ ] 역계보 영향 조회·권한/라벨 철회 hold·참조 보호를 구현한다. 정리 실행은 기존 파일 소유자가 수행하며 첫 릴리스는 preview/보호부터 수용한다.
- [ ] metadata와 참조 파일의 일관된 백업을 별도 위치에 복원하고 hash/reader·계보·권한을 검사한다.

핵심 시험: `changed_preview_invalidates_publish_request`, `publish_uses_selected_account`,
`readback_bytes_not_reader_acceptance`, `revoked_source_holds_descendants`,
`referenced_original_not_reclaimed`, `backup_restore_retains_lineage`.
일반적인 원본 자동 삭제 UI와 대규모 저장소 재배치는 후속이다. P6는 공간 현황·보호·복원과 기존 소유자 정리 인계까지 포함한다.

### P7 — 사용자 수용과 운영 전환

소유 경로: 기존 Learning web·배포/runbook·각 모듈 test 및 `docs/validation/`.
소비: P1–P6 지원 adapter. 산출: 재현 가능한 종단 시나리오·장애 복구 증거·버전별 배포/되돌림 안내.

- [ ] 일반 사용자가 서버 경로/SSH 없이 local/HF 자료→검수→학습→평가→모델/게시를 완료한다.
- [ ] 기존 report link와 자료를 읽기 전용으로 색인하고 누락 provenance는 unverified로 유지한다.
- [ ] 프로젝트/사용자별 자료 격리, 권한 만료, 동시 검수, 느린 응답·빈 상태·실패·재연결을 브라우저에서 검증한다.
- [ ] worker 강제 종료, DB/파일 손상, 저장 부족, HF 단절, 코드 배포 중 변경을 주입해 run 상태와 실제 프로세스를 대조한다.
- [ ] 기존 state를 백업한 뒤 제한 프로젝트에 배포하고 rollback을 검증한다. 실제 계정/GPU/자료 기반 수용은 별도 증거로 남긴다.

핵심 시험: `project_isolation_end_to_end`, `browser_pipeline_without_paths`,
`worker_release_change_requires_rebind`, `offline_local_run_pending_publish`, `restore_then_reconcile`.

## 5. 검증과 증거

위 test 이름은 구현할 행위의 명세이며 현재 존재·통과한 시험 이름이 아니다.
P0의 module 등록에서 각 테스트의 소유 파일을 확정한다. 구현 순서는 실패를 드러내는 시험,
최소 구현, 해당 suite 원격 실행·NEW 확인, 작은 커밋, 통합 회귀다.

```text
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<topic> -- <affected-test-paths>
python test/known_failures.py X:/DevTemp/<topic>/run-1.txt
python tools/harness/rosy_harness.py lint
```

기존 회귀는 `test/learning/perception/`, `learning/registry/policy/test/`,
`learning/training/omx/test/`와 각 owner suite를 해당 변경에 맞춰 선정한다.
공유 contracts/module registry 변경은 저장소 FULL CI 조건을 따른다. fake worker/provider
시험, 실제 격리 브라우저, 모델 PC GPU, private HF 왕복, 실물 owner 수용은 서로 다른 증거다.

## 6. 운영·데이터 비용 산정

초기 용량은 `보존 원본 + 검수/파생본 + 고정 dataset + model/checkpoint + backup + 동시 임시본`으로
계산한다. 측정된 피크에 여유 25%를 초기 가정으로 더하고 실제 수집 추세로 조정한다.
기존 storage_inventory의 root별 수치를 단순 합산해 같은 볼륨의 여유 공간을 중복 계산하지 않는다.

GPU 소요는 `표본 측정 시간 × 실험 수 × 재시도/비교 수`로, 라벨 공수는
`표본 검수 시간 × 검수 단위 수 × 재검수 비율`로 산정한다. IL은 frame 수만이 아니라 episode 길이와
성공/실패 다양성, RL은 sim step/초와 환경 수를 측정한다. 아직 측정하지 않은 GB·GPU 시간·원가를
확정 수치로 제시하지 않는다. HF 실제 quota/요금·계정 권한과 NAS 보유 여부는 P0에서 확인한다.

## 7. 검토 결과와 다음 결정

데이터/저장·계정 담당 관점과 실행/복구·로봇 경계 관점의 독립 검토를 대조했다.
기존 importer의 자체 queue/예약을 보존하고 공통 workflow가 native ID를 참조하도록 한다.
카탈로그는 기존 store/registry의 두 번째 writer가 되지 않는다. 원본 정리와 권한 철회는
파생 모델 영향 조회를 먼저 제공한다. 실행 계층은 단일 scheduler 인계와 실제 종료 확인을 요구한다.

추정의 전제는 기존 모델 PC와 내부 팀용 웹, 로컬+HF 우선, 기존 인지 모델과 제한 SIM RL 재사용이다.
첫 구현 결정은 P0의 참조/adapter 계약과 첫 종단 과제이며, D-771을 기준으로 P0의 상세 계약과 함께 확정한다.
이 계획의 검토는 소프트웨어 착수 범위이며 외부 게시·운영 전환·로봇 활성화 승인과 구분한다.
