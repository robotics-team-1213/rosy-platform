# 영상 reader의 원본 인계·실행 수용 계획

> **For agentic workers:** Execute the approved D-771 subplan task by task using
> `superpowers:subagent-driven-development`. Commit tests, obtain actual remote
> RED, implement, obtain remote GREEN and independent review. No local pytest.

2026-10-17 실행 예외: 사용자의 시뮬레이션 제외·나머지 계속 구현 지시에 따라,
원격 시험 PC에 연결되지 않는 동안에는 시험을 먼저 커밋하고 독립 정적 검토를 거쳐
후속 구현을 진행한다. 실제 RED/GREEN은 미실행으로 남기며 실행 수용·웹 활성화의
조건을 낮추지 않는다. 현재 범위와 완료 기준의 정본은 [전체 계획의 사용자 범위 조정](2026-10-16-integrated-learning-pipeline.md#사용자-범위-조정--시뮬레이션-제외)이다.

**Goal:** 실제 로컬/HF 원본을 예약된 staging으로 인계하고, 서명 reader 실행을 검증한
결과만 기존 자료 소유자가 reader 증거로 보존·조회하도록 연결한다.

**Architecture:** 원본·reader receipt는 acquisition owner가, 계산·파일 예약과 실제
프로세스·accepted outcome은 tools의 native reader owner가 소유한다. 같은 operation
DB의 원래 transaction으로 취소와 결과 수용 순서를 결정한다. 기존 registry,
controller snapshot, reader receipt와 공통 workflow schema를 유지한다.

**Tech Stack:** 기존 Python·SQLite·systemd/sd-bus·pidfd, 공통 compute/volume 원장,
고정 FFmpeg/FFprobe, descriptor 상대 경로와 immutable JSON 증거.

**Spec:** [D-771](../adr/D-771-integrated-learning-pipeline-ownership.md),
[reader 통합 계획](2026-10-17-video-reader-integration.md),
[전체 P0–P7](2026-10-16-integrated-learning-pipeline.md).

상태: 기존 사용자 실행 승인 범위의 세부 계획. V1의 순서·예산·controller writer·proof
binding 지적을 반영한 V2는 독립 architecture/critic 두 번째 검토에서 모두 승인됐다.
시험 명령의 decoder opt-in과 기존 runtime suite 보존도 보완했다. 아래 controller
publication의 inode-CAS 한계를 반영한 V3도 세 번째 좁은 독립 검토에서 모두 승인됐다.
T1·T2a 저장 공간 capability·T2b controller writer는 원격 검증과 독립 코드 검토를 마쳤다.
T3a native owner의 시작·중단·복구는 구현과 후속 정적 검토를 마쳤고 마지막 경계 수정의
원격 검증은 남아 있다. T3b worker/decoder는 구현·독립 정적 재검토를 마쳤고 실제 시험은
미실행이다. T3c 앱 생명주기 연결은 `07ad7723c`까지 구현·독립 정적 재검토를
마쳤고 실제 시험은 미실행이다. 다음은 T4–T5 결과 수용·웹 연결이다.
계획 승인은 실행·설치 수용 증거가 아니다.

## 결정 근거와 고정 경계

2026-10-17 후속 source 준비: 원래 실행 중인 reader 안에서 독립 source 검증을 마치는
방향을 검토했지만 전체 실행 소유자는 승인하지 않았다. 세 번째 독립 검토에서 고정
역할 phase 모델과 queued 취소 호환 문제를 제외하고, [S0a의 네 신규 codec/시험 파일](2026-10-17-reader-source-preparation.md)만
준비한다. 기존 원본 byte staging·거절 진입점·이력 profile None·취소 수용 조건은
유지한다. 아래 standalone helper의 256MiB 목표는 과거 제안이며 그 실행 자격은 없다.
후속 active 검증의 1CPU/1GiB/64task 및 앱 제어 예산도 아직 검증하지 않았다.
같은 OFD의 향후 보관은 원본 byte FD 인계와 다른 제안이며 현재 wire 예외를 열지 않는다.

2026-10-17 S1 후속 채택: 위 no-rights 규정의 예외를 원래 reader supervisor가 보유한
canonical work.lock OFD 한 개의 `retain_work_lock` 인계에 한정한다.
[S1 고정 계획](2026-10-17-reader-work-lock-custody.md)이 실제 송신자·매 fragment 수신·
앱 duplicate·pending/pin/seal·borrow/독립 quiet retirement의 정본이다. 정상 `6b28abe635`의
구현·실제 원격 회귀·11개 독립 변이·복원 control과 독립 소스/증거 검토를 마쳤다.
[S1 한정 검증 기록](../validation/learning-reader-work-lock-custody-2026-10-17/result.md)은
같은 work-lock 사용자 배제의 근거다. 원본 FD 전송 금지와 staging,
full source/native/resource/SQLite 및 웹 수용 조건은 유지한다. 아래 새 broker FD-transfer
금지는 원본 byte 전달에 계속 적용하며 이 보관용 단일 연산만 명시적으로 제외한다.

현재 registry에는 operation/scratch/result root만 있고 원본 root는 없다.
StartUnit은 웹 프로세스의 원본 FD를 서비스에 전달하지 않는다. 기존 byte owner에서
검증한 바이트를 예약 후 고정 경로로 staging한다. 새 broker FD-transfer protocol은
추가하지 않는다. staging은 디스크 복사 비용이 들지만 기존 서명 실행 경계를 유지한다.

원본 경로를 registry에 넣어 worker가 importer를 다시 구성하는 대안은 자격증명·
source owner 의미를 중복한다. raw worker/controller 영수증을 바로 reader 승인으로
쓰는 대안은 취소·마지막 권한 검사·실제 종료와 receipt 조회를 연결하지 못한다.

| 책임 | writer / 검증 주체 |
|---|---|
| 원본·고정 acquisition receipt·현재 접근 권한 | 기존 Local/HF acquisition owner |
| 원본에서 읽는 bounded stream·acquisition native identity | 새 owner 내부 입력 포트 |
| staging·쓰기 진행량·임시 공간 | 실제 ReaderResources의 소유 capability |
| 원 요청·claim/cancel metadata | 기존 ReaderExecutions |
| launch gate·실제 manager/process·결과 수용 | tools native reader owner |
| immutable accepted outcome와 receipt 연결 | 같은 native operation DB의 native owner |
| 기존 reader receipt 저장·historical lookup | Local/HF acquisition owner |
| 상태·마지막 증거 표시 | 기존 catalog/HTTP/UI |

actor·grants·credential·opaque RefUnit handle은 DB에 저장하지 않는다.
acquisition의 `native_execution`과 reader service의 physical identity를 구분한다.
일반 웹 입력은 등록 asset/profile/request ID만 사용한다.

## T1 — 실제 원본 소유자의 bounded 입력 포트

소유 파일: 새 `learning/curation/perception/local_reader_inputs.py`,
`learning_import_inputs.py`, `tools/perception/video_reader_inputs.py`와 최소한의
기존 receipt validator·`learning_imports.py` forwarding. imports는600줄 이하 유지.
구현 담당: HF/input worker, 원본 책임 검토: data reviewer.

포트는 다음과 같이 고정한다.

```python
inspect_reader_input(actor, project_id, asset_ref, profile_id) -> INPUT
open_reader_input(actor, project_id, asset_ref, profile_id, *, expected_input) -> context
# context.input: detached exact ReaderExecutionRequest.INPUT
# context.chunks(name): declared member, single pass, chunks <= 64 KiB
```

Local의 byte receipt는 `revision`, owner receipt는 전체 receipt의 canonical hash,
acquisition identity는 `local_acquisition/request_digest`다. HF는 원래
`manifest_sha256`, 전체 completed proof hash, job/current attempt/producing attempt다.
tools가 이 의미를 경로에서 재구성하지 않는다.

- [x] 실제 Local/HF acquisition을 사용해 신규 포트 RED를 확인한다. 잘못된 owner,
  requester·권한 철회·HF credential generation·lease 경합을 포함한다.
- [x] payload를 열기 전에4파일·각8MiB·합16MiB metadata preflight를 수행한다.
  기존 eager hash validator에는 최소 내부 metadata 검증 포트를 추가하고 기본 동작은 유지한다.
- [x] complete read·해시·크기·named FD identity·원 receipt/job·마지막 현재 권한을
  successful context exit에서 다시 검사한다. 부분 읽기는 완료로 수용하지 않는다.
- [x] router는 등록 owner를 유일하게 선택하고 실제 Accounts scope를 확인한다.
  경로·raw FD·credential·writable stream을 소비자에게 노출하지 않는다.
- [x] 기존 Local/HF receipt·R1·lazy import 회귀와 신규 streaming 회귀를 원격 검증한다.

T1 근거: `a9d09d436` 신규44건과 `2ad42c742` fresh callback4건의 실제 원격 RED 후
`42262a732` 신규·기존270건이 통과했다. `361615f7e`의 실제 중앙 Account 권한 철회
회귀1건도 통과했다. 두 실행 모두 skip0·0 NEW이며 독립 소스 검토를 통과했다.
중앙 회귀는 실제 source lease 정리 뒤의 철회를 검사하며 기존 cached 권한 조회가
계속 허용하는 상황에서 마지막 fresh 검사가 거절함을 확인한다.

source lease는 읽는 context 동안만 유지한다. `verify_operation`은 inspection만
사용하고 D-446 실행 잠금을 다시 잡지 않는다. staging 호출은 모든 source context를
닫은 뒤 서비스를 시작해 broker renewal과 source lease가 교착하지 않게 한다.
HF의 기존 `service.authorize`는 cached RosyAccounts일 수 있다. 새 owner 포트의
trusted `authorize_fresh` callback은 필수이며 cached fallback을 두지 않는다. 실제
원래 actor identity를 유지하고 모든 context close 뒤에도 fresh 권한을 확인한다.

## T2 — 실제 예약에서만 얻는 staging capability

소유 파일: `tools/perception/video_reader_resources.py`의 좁은 확장과 cohesive
`video_reader_storage.py`/budget helper. 공유 volume API 변경이 필요하면 먼저 실제
소비자와 perception 회귀를 검토한다. 구현 담당: resource worker.

```python
resources.staging(snapshot)  # canonical D-446 lock; original queued1
resources.worker_storage(snapshot, physical, *, lock_fd)  # actual inherited lock
resources.controller_storage(snapshot, physical, *, lock_fd)  # bounded control writes
# opaque capability: write_input(index, chunks), seal_inputs(), open_inputs()
# worker-only path supplies the pinned scratch FD internally to video_reader.verify
```

capability는 caller dict/path가 아니다. exact native ref/spec·실제 held compute와
volume claim/domain/generation·기존 quiet/launch 상태를 확인한 뒤 생성한다.
`operation_root/<job>`, `scratch_root/<job>`, `result_root/<job>`만 다룬다.
기존의 뜻밖 파일·불완전 staging을 자동 덮어쓰거나 새 복사로 우회하지 않는다.

- [x] claim 누락·부분 claim·다른 native identity·다른 볼륨·잠금 FD 오류가 파일 생성
  전에 거절되는 실제 원장 시험을 먼저 실행한다.
- [x] 고정 `inputs/{0..3}`를 O_EXCL/nofollow/private/nlink1로 기록한다. 원 manifest의
  이름→ordinal·크기·hash를 대조하고 각 파일과 부모를 fsync한다.
- [x] native ref/spec/request·byte/owner receipt digest·원본 이름과 고정 파일 hash를
  결합한 bounded canonical immutable manifest를 마지막에 발행한다.
- [ ] 완전한 동일 manifest만 중복 채택한다. partial/failed staging과 claim은 남기고
  quiet 확인 후 원 소유자가 정리한다. worker는 원본 root 없이 staging만 검증한다.
- [x] 쓰기 intent→공통 VolumeReservations.checkpoint CAS→fsync acknowledgement를
  기록한다. 이미 소비한 공간을 전체 잔고에서 다시 빼지 않는다. controller 초기·worker·
  controller finalizer는 같은 original claim의 최신 generation/진행량을 대조한다.

decode용 파일은 worker가 actual physical binding과 inherited lease를 확인한 뒤
한 번 생성한 네 O_TMPFILE slot(24/8/8/8MiB)을 사용한다. qualified Linux
`fallocate(FALLOC_FL_KEEP_SIZE)`로 실제 extents를 먼저 확보하고 fsync/fstat의
실제 allocated blocks만 checkpoint한다. 지원하지 않으면 fallback 없이 실패한다.
slot은 decoder phase 전체에 열린 상태로 유지하고 fixed-role private argv/pass_fds로
child에 전달한다. 새 broker/HTTP FD protocol은 만들지 않는다. tool 두 slot은 truncate/
punch 없이 offset을 되돌려 재사용하고 실제 written offset 길이만 읽어 stale tail을 제외한다.

`remaining reservation + measured still-pinned allocations`가 미래 전체 쓰기를
커버해야 한다. 다른 claimant에게 이 공간을 다시 노출하지 않는다. 할당 전 정적48MiB를
credit하거나 재시작의 JSON flag로 live FD credit을 복원하지 않는다. 부분 할당/CAS ack
유실은 claim을 유지하며 quiet cleanup 전 새 decoder/slot을 생성하지 않는다. native
중첩 프로세스의 inherited execution lease 수명도 실제 descendant 시험으로 확인한다.

T2a 근거: 실제 원장·Local/HF 원본·tmpfs 할당을 사용한 초기37건 RED 뒤 저장 공간을
구현했다. 열린 실제 FD의 FIFO/ABA·반복 해시·할당 중 renewal 결함은 추가10건 RED 뒤
`f86a7bb3c`327건 원격 통과로 보완했다. close/readmission 중 재진입·이전 scope 정리의
새 경합6건 RED 뒤 `c22615467`131건이 원격 통과했다. 두 GREEN 실행은 skip0·0 NEW이며 독립
재검토를 마쳤다. 부모 FD를 닫은 뒤 자식의 실제 flock 유지도 확인했다. worker는
`check_execution(..., storage=handle)`의 실제 live capability를 통해 할당 중 예약을
확인한다. 기본 resource 검사는 유지하며 broker가 JSON에서 anonymous FD credit을
복원하지 않는다. controller `write_receipt`는 아래 T2b 근거로 구현했고 decoder slot 연결은 T3b에 남아 있다.

T2b 근거: 실제 bounded writer와 signed controller 연결은 `128222426`353건,
foreign link 보존·복원은 `982cfdff4b`266건 원격 통과로 확인했다. worker가 실제48MiB
slot을 할당한 뒤 finalizer가 최신 generation을 확인하는 강화 시험도 `85273b444`2건
통과했다. 독립 검토에서 찾은 임시본 inode/바이트 대조 결함4건을 실제 RED로 재현하고
`ef0f4ca3f`에서 수정해 관련170건이 원격 통과했다. 모든 GREEN은 skip0·0 NEW이며
독립 재검토를 마쳤다. 별도 revision의 실행 결과를 하나의 전체 검사로 합산하지 않는다.
실제 자식의 `os._exit`로 초기 link·target 이동·최종 link 뒤 정리 없이 종료한6건도
intent·claim 보존과 세 번째 copy 거절을 확인했다. 실제 signed loader·원장·flock·
파일 작업의 증거이며 broker·systemd/배치 관측은 명시 fixture다. 실제 decoder·고정
service·native accepted outcome·자원 해제·웹 수용을 입증하지 않는다.

예약은 실제 qualified allocation unit B로 다음을 계산한다.

```text
64 MiB control cushion
+ scratch_bytes(B)                         # four anonymous files, 48 MiB raw
+ sum(round_B(each input.bytes))            # at most four files, 16 MiB raw
+ bounded manifest + worker result + controller replacement peak
+ bounded owned directory allocation
```

64MiB는 총 decoder budget이 아니다. 파일마다 반올림한다. SQLite/accepted history
증가와 보존한 증거도 실제 사용량·quota에 반영한다. 지원하지 않는 allocation/volume
조건은 거절하고 control cushion을 측정한 상한으로 표현하지 않는다.

입력 manifest는131072B, worker result envelope는16384B(기존 decode result는4096B),
controller JSON은16384B, filtered terminal capture는16384B, accepted document는
262144B로 제한한다. JSON 해석·파일 쓰기 전에 byte bound를 검사한다. 최초/교체 시
동시에 존재하는 복사본은 따로 계산한다. controller replacement peak는
`2*round_B(16384)`와 그 directory metadata다. 큰 증거를 자르거나 누락해 수용하지 않는다.

controller는 `execution_root/jobs/reader-<job>-<physical>.json`을 supervision 전과
finalizer에서 기록한다. 원래 세 output root와 별개로 이 실제 private directory와
ancestry·동일 reserved device·초기/최종 publication의 bounded 비용을 검증한다.
execution root 전체를 managed output으로 넣거나 다른 job을 정리·공간 credit하지 않는다.
고정 writer는 `deploy/site/model_code_reader_receipt.py`에 두고 설치 helper 목록과
signed CLI 시험도 같이 갱신한다. generic `atomic_json()`을 reader 경로에서 직접 쓰지
않는다. 초기 기록 전에 controller_storage가 held original claim/spec·inherited lock·
실제 자기 service/physical·private jobs directory/device를 검증한다. queued1 시점의
이 포트는 bounded control 쓰기만 허용한다. payload/worker claim이나 사용자 grant를
발급하지 않는다. opaque control capability의 `write_receipt(encoded_bytes)`만 사용하며
각 초기/최종 기록마다 새 context에서 최신 original claim generation을 조회한다.
final write는 기존 supervised finalizer의 live permit 안에서 수행한다. private
snapshot/registry의 HTTP 필드는 추가하지 않는다.

#### Controller publication의 보존·복구 계약

`stat` 뒤의 `os.replace`는 destination inode의 atomic CAS가 아니다. descriptor 상대
경로도 마지막 이름의 교체를 막지 않는다. 기존 `workflow_storage_metadata.py`의
immutable link/no-replace는 최초 게시에 재사용할 수 있지만 mutable replace의 stat은
이 한계를 해소하지 않는다. 정상 실행의 sole trusted publisher와 private directory를
유지하고, named publication 경계의 파일 교체 오류에서는 바이트 보존과 HOLD를 우선한다.

1. 초기 기록은 bounded O_EXCL 임시 파일을 fsync한 뒤 fixed target에 link/no-replace로
   게시한다. target이 먼저 나타나면 덮어쓰지 않고 intent·claim을 유지한다.
2. 최종 기록은 새 bounded 임시본과 intent를 먼저 보존한다. 현재 target을 같은 directory의
   고정된 소유 복구 이름으로 fd-relative `renameat2(RENAME_NOREPLACE)`로 옮긴 뒤,
   **실제로 옮겨진 inode**를 원 initial receipt identity와 대조한다. 이 syscall이 지원되지
   않으면 fallback 없이 거절한다. 복구 이름은 job/physical 및 실제 intent에 결합하며
   기존 복구 파일을 덮어쓰지 않는다.
3. 다른 inode가 옮겨졌으면 새 결과를 게시하지 않는다. target이 여전히 비었을 때만
   no-replace 복원을 시도하며, 충돌 시 옮겨진 바이트와 모든 후보를 보존하고 HOLD한다.
   복원에 overwrite rollback을 사용하지 않는다.
4. 옮겨진 것이 원 initial inode면 새 임시본을 비어 있는 target에 link/no-replace로
   게시한다. 이 경계에 다른 target이 생겨도 건드리지 않는다. directory fsync·실제 target
   identity·최신 claim CAS acknowledgement까지 확인한 뒤에만 publication 완료로 기록한다.
   known initial 복구본은 bounded 증거로 유지하며 자동 삭제하지 않는다. 정상 상태의
   old/new 두 inode와 잠깐의 hardlink 이름을 예산에 반영하며 hardlink를 복사본처럼
   중복 credit하지 않는다.

완료 전에는 소유한 임시 link를 제거하고 target·복구본 각각의 `nlink=1`을 검증한다.
unresolved 또는 이미 완료된 publication의 재실행은 세 번째 copy를 만들기 전에
거절한다. 다른 inode의 복구본은 삭제하지 않는다. 이 두-copy 상한과 HOLD 조건도
실제 filesystem·checkpoint 경계 시험에 포함한다.

이 절차는 원 이름이 잠깐 없을 수 있는 recoverable transition이며 연속적인 atomic
replacement가 아니다. arbitrary same-UID writer에 맞서는 namespace 보안이나 지속적인
외부 교체 중 원 이름의 연속성을 보장하지 않는다. unresolved intent·missing/conflicting
target·ack 유실은 성공이나 자동 재시도로 전환하지 않는다. 이후 native owner가 exact
intent/identity·실제 종료·quiet를 대조해 소유 복구만 수행하며 claim을 유지한다.
accepted outcome은 settled 실행 뒤 이 기록을 검증하므로 raw receipt가 잠시 없거나
후보가 남은 상태를 승인하지 않는다. close/fsync/CAS·첫 link·target 이동·두 번째 link
각 경계에 crash와 foreign target 교체를 주입해 바이트 보존과 미수용을 검증한다.

## T3 — native owner와 signed worker의 실제 연결

소유 파일: 새 `tools/perception/video_reader_runtime.py`, `video_reader_service.py`,
검토한 고정 service artifact와 기존 앱의 최소 composition. 구현 담당: root/지정 worker.
고정 template 작성은 설치 승인이 아니다.

T3a 체크포인트: 실제 원장·Accounts·로컬/HF·private bus·프로세스 경계를 포함한
`11cca34a1`325건은 원격 통과(skip0·0 NEW)했다. 이후 취소·역사 보존 수정
`23593b1d9`에서는200건 통과·2건 fixture 기대값 실패를 확인했고,
fixture 보완 `d026dd22d`의 대상2건은 통과했다. 이를 하나의 전체 GREEN으로 합산하지 않는다.
독립 검토의 마지막 입력 I/O 뒤 profile/routing 재확인과 SQL 해석 전 문서 byte 제한은
`63b2c0512`에서 수정해 정적 재검토를 통과했다. 추가32건의 실제 RED/GREEN은
시험 PC 연결 장애로 미실행이다. 시작·중단·복구 구현은 후속 작업에 사용하되,
실제 고정 service 수용·T3 전체 완료·VIDEO 활성화의 근거로 쓰지 않는다.

후속 실행 대조 — 2026-10-17: 위 추가32건의 미실행 상태는 이후 S1 증거로 보완됐다.
`reader-custody-extended-execution-6b28abe635.json`의 두 번째 invocation은
`test_video_reader_native_boundaries.py` 전체와 기존 owner 회귀를 선택했고 실제375건이
199.32초·skip0·0 NEW로 통과했다. [S1 고정 기록](../validation/learning-reader-work-lock-custody-2026-10-17/result.md)에
같은 SHA·원본 로그 해시를 보존했다. 이미 실행한32건을 다시 미실행으로 열지 않는다.
고정 service·full source producer/writer 배제·native 자원 자격과 VIDEO 활성화 조건은 유지한다.

T3b 체크포인트: 서명 worker·같은 원 queued snapshot·예약한 네 FD·bounded 불변 후보
결과 저장을 연결했다. 독립 검토의 디코더 자손 수명·storage close 중 renewal·FD inode alias와
필수 결합 시험 지적은 두 차례 수정해 `1e1c9440f`의 정적 spec·quality 재검토를 통과했다.
디코더 안에서만 자손을 수거하며 갑작스러운 종료·수거 불명은 failed/HOLD로 남긴다.
실제 signed loader→worker/broker·고정 codec·permit 뒤 취소·hostile/자손 시험은 작성됐지만
원격 접속 장애로 수집·실행하지 않았다. 부분 정적 승인은 실제 종료 수용·자원 해제·웹 수용이 아니다.

- [ ] 기존 operation queued1 생성/채택→actor attachment/이전 launch quiet→예약→
  staging→launch journal의
  시작/중복/취소/응답 유실 시험을 먼저 실행한다. 새 queue나 perception ticket은 만들지 않는다.
- [ ] 실제 공유 ManagerReferences의 `hold_profile('video_reader', job_id)`를 StartUnit
  전에 호출한다. launcher identity와 같은 transaction의 gate를 기록한 뒤 고정 실행기를 쓴다.
- [ ] attachment guard의 quiet는 launch 전 검사다. 서비스 시작 후 peer/InvocationID
  attestation은 이미 실행 중인 동일 service를 확인하며 quiet를 다시 요구하지 않는다.
- [ ] signed supervisor preparation permit→등록 worker hello/claim permit→실제
  `claim_owned` CAS running2→physical/resource check→worker pre_read 순서를 연결한다.
  supervisor permit이 worker phase를 대신하지 않는다. worker permit과 native claim 사이의
  실제 취소를 시험한다. `verify_operation`은 원 actor와 실제 owner selection을 재검증한다.
- [ ] worker는 fixed staging·모든 byte/hash와 inherited lock을 확인하고 명시 scratch FD로
  decode한다. 결과 발행/fsync/finalizer까지 기존 live permit·독립15초 expiry를 유지한다.
- [ ] launcher acknowledgement·실제 terminal capture·whole subtree quiet를 보존한다.
  HTTP disconnect·raw receipt·worker exit0·direct child reap을 종료 수용으로 쓰지 않는다.
- [ ] 중지·재시작은 원 identity만 대조한다. cleanup에는 새 user grant가 필요하지 않으며,
  불확실한 launcher/descendant·cleanup 실패는 claim과 reference를 유지한다.

실제 transient service 시험은 kernel/manager 관측을 증명할 수 있지만 RefUnit-before-
StartUnit을 대체하지 않는다. 완전한 고정 service 수용은 provisioned disposable manager
또는 구체적으로 검토한 임시 template 절차에서 수행한다. 운영 timer/장치/실계정은 건드리지 않는다.

T3c 정적 체크포인트: 하나의 application manager 참조에 reader·perception 소유자를
연결하고 imports 구성 뒤 복구한다. 원래 registry·파일/디렉터리 pin과 실제 owner/resources를
복구·listener 시작 전에 비교한다. reader-only·perception-only·혼합 구성과 실패 시 종료를
다루는 시험을 먼저 커밋했다. `07ad7723c`의 독립 정적 spec·quality 검토는 승인됐으나
의도64개 사례의 수집·실행, 실제 고정 서비스와 브라우저 수용은 아직 미실행이다.
이는 아래 결과 수용·원 소유자 보존·catalog 연결을 완료했다는 뜻이 아니다.

## T4 — 취소와 동일 transaction으로 결정하는 accepted outcome

소유 파일: 새 tools native-outcome helper, 실제 operation DB의 additive
`reader_native_outcomes(job_id PRIMARY KEY, receipt_revision, document)`와 nonunique
receipt index. 기존 metadata 상태와 reader receipt schema는 유지한다.

T4 원장 준비 체크포인트: 영구 control 예약·bounded outcome codec/SQL·수용/취소 순서와
모든 parent/child writer 전파는 `8be92c384`까지 구현하고 독립 정적 재검토를 마쳤다.
수용 전용 issued gate 조건과 실제 native 취소 시험의 최종 구성·활성화 순서를 보완했다.
새 시험의 수집·실행과 SQLite/이전 writer 자격은 미실행이다. production profile은
`None`이며 자동 활성화하지 않는다. source 검증용 공간은 예약했지만 아직 사용할
쓰기 포트가 없으며, 이것을 검증 helper나 전체 수용의 준비 완료로 해석하지 않는다.
source 검증·최종 수용·독립 과거 조회와 T5는 후속 구현이다.

### 2026-10-17 source 검증 라이브러리 준비 범위

다음 구현은 서명·archive·설치 tree를 검증하는 공통 읽기 전용 라이브러리와 실행 불가
경계를 준비한다. 별도 architecture·critic 검토 두 라운드에서 소스 준비만 승인했다.
실제 helper 실행 소유자와 자원 격리는 아직 없으므로 Task2 전체 완료로 판정하지 않는다.

소스 체크포인트 `420a680bc5`: 공통 바이트 signature/source API·설치 dependency와
실행 불가 경계를 구현하고 독립 정적 spec·quality 재검토를 마쳤다. 사전 검사 뒤 archive가
바뀌는 경우를 막기 위해 parser에 metadata를 반환하기 전에 검사 때 고정한 header/PAX
바이트와 겹친 범위를 비교한다. terminal zero 영역·고정 EOF·유한 read/seek도 검사한다.
누적 PAX와 보존 경로 상한 시험은 다른 상한에 먼저 걸리지 않고 목표 경계를 넘도록
보완했다. 새 crypto·parser·mutation 시험과 legacy 회귀는 수집·실행하지 않았다.
검사 metadata raw bytes의 계산 상한이 16MiB 미만이라는 사실은 Python 객체를 포함한
전체 피크나 실제 256MiB 실행 환경의 자격을 입증하지 않는다.

- `candidate_signing.verify_manifest_signature_bytes`는 기존 서명 domain과 엄격한 envelope
  검사를 공유하고 이미 선언된 cryptography의 Ed25519 바이트 검증을 사용한다. 임시 파일이나
  OpenSSL 대체 실행을 추가하지 않으며 기존 controller의 OpenSSL 동작은 유지한다.
- `model_code_source.verify_source_with_key_bytes`는 기존 실제 archive hash·inventory·설치
  tree 검증을 공유하고 검증한 원본 member 바이트를 반환한다. T4 전용 상한은 manifest
  4096B·서명 1024B·READY 128B·key 4096B이며 descriptor 크기 확인과 bounded read가
  parse/import보다 먼저다. archive 512MiB, raw header 20000개·일반 entry와 파생 node
  10000개, local PAX payload 4096B/누계 1MiB, 보존 경로 누계 2MiB 상한을 parser의
  metadata 축적 전에 적용한다. 기존 legacy 상한과 지원 동작은 별도로 유지한다.
- 새 source-verifier의 parent·helper 진입점은 첫 단계에서 고정 unavailable을 반환한다.
  환경 변수·호출자 객체·옛 reader claim·검증 라이브러리 직접 호출로 제품 실행을 우회하지
  않는다. 기존 compute 원장의 단일 held slot과 물리 binding은 새 helper를 발급하지 못한다.
- 후속 실행 소유자는 원래 reader 예약을 유지하면서 같은 호스트의 실제 공유 자원 회계와
  새 물리 subtree를 연결해야 한다. 제안 상한은 메모리 256MiB/swap 0, 주소 공간 512MiB,
  CPU 한 코어·50초, task 1개·FD 128개·wall 60초와 read-only/no-egress다. 이는 아직
  강제하거나 자격 검증한 환경이 아니다. 실제 발급·격리·전체 종료 증거가 없으면 실행하지 않는다.

영구 이력 control은 계속 `identity.json`만 허용한다. 예약된 검증 공간 65536B를 임의
쓰기 권한으로 사용하지 않고, `QUALIFIED_SQLITE_PROFILE=None`도 유지한다. 설치 copy-list와
서명 fixture에는 새 공통 dependency를 명시한다. 새 시험은 먼저 작성하되 실제 원격 실행·
최종 수용·독립 과거 조회·T5·고정 service 검증은 별도로 완료해야 한다.

### 2026-10-17 상세 설계 검토와 구현 순서

별도 architecture·critic 두 라운드는 다음 소스 준비를 승인했다. 실제 실행·저장소
자격 검증은 미실행이며 현재 `QUALIFIED_SQLITE_PROFILE=None`으로 활성화를 거절한다.
환경 변수·호출자 설정·저장된 문서만으로 이 자격을 대신할 수 없다.

1. 기존 private schema1 operation DB의 inode를 먼저 고정하고 실제 공유 volume 원장에
   영구 control 예약을 확보한다. 새 DB·빈 DB는 생성 전에 거절한다. 예약 뒤 control
   기록·outcome 확장을 만들며 중단된 조합이나 같은 경로의 다른 inode는 자동 복구하지 않는다.
   확장이 없는 기존 metadata 사용의 DB 생성 동작은 유지한다.
2. 저장한 증거 전체를 같은 DB의 bounded outcome에 보존한다. 초기 지원은 전체 DB 4MiB,
   outcome 256KiB이며 작은 이력용이다. rollback·검증 scratch를 별도 포함한 영구 예약을
   유지하고 용량 부족은 거절한다. 실제 SQLite/VFS·파일시스템 피크와 이전 writer 배제를
   검증하기 전에는 사용하지 않는다. 모든 parent/child writer에 연결별 한계를 적용한다.
3. 실제 종료·source 서명·전체 증거·현재 원본 권한을 검증한 뒤 같은 transaction에서
   수용/취소 순서를 결정한다. SQL 안에서는 외부 I/O나 권한 callback을 호출하지 않는다.
4. 과거 조회는 별도 read-only resolver로 현재 profile·등록 key·원 DB/영구 예약·취득
   custody를 확인한다. live owner·manager·writer나 삭제된 decoder/source/runtime 경로를
   다시 구성하지 않는다. 세 내부 수용/조회 포트 모두 새 프로세스에서 이 조회를 먼저
   시도한다. marker 없는 기록은 재부팅이나 파일 유무로 수용하지 않는다.

먼저 예약·원장·모든 writer 전파를 함께 구현하고, 독립 증거 검증, 최종 수용·과거 조회
순으로 이어간다. 영구 이력 예약은 작업별 정리·해제와 별개다. 임시 파일 정리 뒤 조회와
실제 고정 서비스의 전체 동선은 여전히 T5 수용 조건이다.

- [ ] 원래 ref/request/spec·physical binding/boot·staging manifest hash·worker/controller
  증거 hash·보존한 manager terminal capture·기존 sealed reader receipt를 결합한 bounded
  canonical document를 고정한다. writer와 native-proof verifier의 역할을 독립 검토한다.
- [ ] hash 비교에 더해 controller `source_proof` 전체와 source_commit/environment를
  실제 검증된 source expectation/retained source proof에 대조한다. 고정 script는
  `tools/perception/video_reader_service.py`, arguments hash는 기존 executor의
  `fingerprint([job_id])`다. reader ref/spec/physical/final version2와 exit_code0·finished,
  실제 supervisor/worker attestation, gate-issued/settled owned launch·retained manager
  identity·동일 physical의 fresh terminal capture와 whole-subtree quiet를 함께 확인한다.
  raw hash만 일치하는 forged source/args/foreign process·late result 각각을 mutation
  RED로 거절한다. decoder verified/unsupported/failed/unknown은 결과의 별도 status다.
- [ ] immutable candidate evidence를 먼저 기록한다. 현재 원본 custody/권한과 실제 종료를
  SQL 밖에서 확인한 뒤 running2/exact physical/uncancelled CAS로 marker를 한 번만 기록한다.
- [ ] cancel이 먼저 commit하면 acceptance를 거절한다. acceptance가 먼저 commit한 뒤의
  cancel은 그 역사적 outcome을 취소로 덮지 않는다. native cancel 경로가 marker를 같은
  transaction에서 확인한다. 현재 metadata-only cancel 포트를 그대로 호출하지 않는다.
- [ ] marker 없는 candidate는 소비하지 않는다. marker 후 acquisition persistence가
  끊기면 같은 결과를 재검증해 replay한다. 새 실행이나 다른 native ref로 대체하지 않는다.
- [ ] accepted evidence는 scratch 밖에 남긴다. cleanup·unit GC·reboot 후에는 immutable
  saved terminal evidence와 현재 custody/권한을 확인하며 살아 있는 옛 handle을 요구하지 않는다.
  미수용 candidate를 reboot만으로 성공시킬 수 없다.

## T5 — 원 소유자의 수용·readback·catalog·웹

- [ ] Local/HF의 `accept_native_executed_result(actor, project_id, asset_ref, profile_id,
  reader_native_ref)`는 구성된 owner의 accepted outcome을 직접 조회한다. caller result,
  receipt JSON·evidence path는 받지 않는다. 자체 custody/binding/권한을 확인하고 기존
  reader receipt를 immutable하게 보존한다.
- [ ] 모든 video receipt readback과 explicit revision lookup은 exact receipt revision의
  indexed deterministic accepted association을 조회한다. 동일한 canonical receipt가 여러
  실행에서 나와도 per-job history를 덮지 않는다. 무제한 history scan을 만들지 않는다.
- [ ] 기존 image lookup semantics는 유지한다. video catalog projection도 native readback을
  거치며 현재 권한 철회·stale generation·source change·late cancel 시험을 포함한다.
- [ ] 마지막 persistence/context-close I/O 뒤 현재 권한을 다시 확인한 후 응답·projection한다.
  거절 시 immutable history는 남고 현재 작업을 승인 표시하지 않는다.
- [ ] 실제 MP4 Local/HF→staging→signed worker→native acceptance→reader receipt→catalog→
  Chromium 동선을 검증한 뒤에만 설정된 video 선택지를 연다. unsupported/failed/unknown
  decoder 결과와 verified 결과를 구분하고 unknown을 성공 cache로 채택하지 않는다.

## 검증·복구·실행 순서

T1→T2→T3/T4→T5 순으로 각 소유 범위를 commit하고 원격 검증한다. 독립 가능한 T2의
budget/admission 거절 시험은 T1과 병행하되 실제 stream 통합은 T1 GREEN 후 수행한다.
각 단계는 새 오류·변경에 필요한 회귀만 확대하며 최종 안정 revision에서 전체 검사를 한다.

대상 suite 이름을 `test_video_reader_inputs.py`, `test_video_reader_storage.py`,
`test_video_reader_runtime.py`, `test_video_reader_outcomes.py`,
`test_video_reader_native_execution.py`, `test_learning_pipeline_video_browser.py`,
`test_video_reader_fixed_service.py`로 고정한다. inputs와 runtime은 이미 존재하므로
현재 회귀를 보존하며 확장하고, 나머지는 각 단계의 RED commit에서 만든다.
기존 operation/binding/resource/supervisor/signed
CLI/Local/HF/R1 회귀는 변경한 producer/consumer에 맞춰 함께 선택한다.

```text
python tools/remote/remote_pytest.py --sha <commit> --log-dir <external-dir> -- test/learning/perception/test_video_reader_inputs.py test/learning/perception/test_video_reader_storage.py -vv -rfE
python tools/remote/remote_pytest.py --sha <commit> --log-dir <external-dir> -- ROSY_RUN_VIDEO_READER_TESTS=1 test/learning/perception/test_video_reader_native_execution.py -vv -rfE
python tools/remote/remote_pytest.py --sha <commit> --log-dir <external-dir> -- ROSY_RUN_VIDEO_READER_TESTS=1 ROSY_RUN_READER_SERVICE_TESTS=1 test/learning/perception/test_video_reader_fixed_service.py -vv -rfE
python tools/remote/remote_pytest.py --sha <commit> --log-dir <external-dir> -- ROSY_RUN_VIDEO_READER_TESTS=1 ROSY_RUN_BROWSER_TESTS=1 test/learning/perception/test_learning_pipeline_video_browser.py -vv -rfE
```

모든 run 로그를 `test/known_failures.py`로 대조한다. fixed-service의 명시 opt-in은
disposable real-manager/private configuration·template·actual cgroup·pidfd·qualified
filesystem이 없으면 skip 대신 fail한다. source writer/runtime의 seam-only GREEN과
이 gate를 구분한다. Local/HF 각각 실제 signed fixed-service→decoder→accepted outcome→
native receipt→catalog가 실행되고 skip0인 증거를 확보해야 video 웹 실행을 연다.
해당 환경이 아직 준비되지 않으면 enablement는 닫힌 상태로 남긴다. 위 명령은 준비할
시험 목표이며 실행했다는 기록이 아니다.

2026-10-17 저장소·기록 검토에서는 재사용 가능한 격리 real-manager fixture를 찾지 못했다.
`test/learning/perception/manager_ref_bus_fixture.py`는 실제 sd-bus 전송과 Python manager 모델을,
`test/learning/perception/test_workflow_process.py`는 실제 subprocess/pidfd와 scripted unit 관측을 검증한다.
원격 runner의 user scope는 전용 unit search path나 cgroup delegation을 제공하지 않는다.
따라서 전용 시험 manager/bus·per-run unit 경로·격리된 cgroup 소유권과 종료/정리 조건의
provisioning·qualification이 실제 고정 service 수용의 선행 조건이다. 기존 운영 manager에
template을 설치하거나 transient service 결과로 이 조건을 대체하지 않는다. 이는 기록 검토이며
현재 호스트를 새로 점검하거나 변경한 결과가 아니다.

복구는 기존 operation/launch/claim/evidence를 보존한 채 exact owner/identity로 대조한다.
partial copy·lost acknowledgement·권한 철회·파일/DB 손상·저장 부족을 주입한다. rollback은
video 선택지를 닫고 기존 image/receipt를 유지한다. 원장·자료를 지우거나 새 attempt로
불확실한 실행을 숨기지 않는다. 실계정 게시·GPU 학습·설치/현장 수용은 별도 증거다.
