# 서명된 준비 자료를 미검수 저장소로 인계하는 계획

> **For agentic workers:** Use `superpowers:subagent-driven-development`.
> Commit owned tests first; obtain actual committed-revision remote RED before
> product changes. Root owns docs/evidence and remote runs. No laptop runtime.

**상태:** 구조·critic이 같은 초안을 각각 독립 검토했고 세 회차 뒤 계획을 승인했다.
처음 네 지적은 경로/읽기·효과 범위·독립 proof·서명 fixture를 구체화해 해소했고,
마지막 PNG 내용 지적도 실제 signature 검사와 JPEG 위장 negative/변이로 반영했다.
계획 검토는 실행 증거가 아니다. [원본 준비](2026-10-17-first-camera-preparation.md)의
실제 GREEN·독립 spec/quality·변이·복원과 후속 실제 MCAP16건의 독립 감사를 마쳐
선행 조건을 충족했다. tests-only `45bd12a2e9`의 첫 실행은 FIFO 시험의 무제한 호출
위험을 확인해 기존 native 취소 경로로 종료했다(exit143·미완료, RED 수치로 세지 않음).
실제 child의 시간 제한·종료/회수·FD/저장 불변 검사를 넣은 tests-only `44d7cfc5c1`은
원격78 failed/8 passed18.21초·skip0·78 NEW다. root가 CWD shadow·bool/mode trap·
PNG 위장·bounded FIFO·실제 signed CLI의 옵션 부재 trace를 확인해 구현에 착수했다.
ZIP unflagged control의 background label 오류는 tests-only `62ec9213e4`로 고쳤다.
선행 FileNotFound 실패는 각 capture/race guard의 증거가 아니다.

후속 소스 `0ef4c1bebf`의 신규87건·기존133건·독립 proof/MCAP/권한178건(Windows2 skip)·
서명 controller160건이 실제 원격 통과했고 각 비교는0 NEW다. 클래스 결합 경합 지적은
두 실제 import의 RED1건 뒤 기존 store lock 안에서 결합을 다시 확인해 해소했으며 독립
spec/quality가 수정본을 승인했다. 같은 정상본에서 여덟 실제 독립 변이를 각 목표 trace로
증명했고 정확한 정상본 복원87건도 통과했다. 독립 최종 감사는 이 소스 증거를 수용했다.
Windows 검사는 미실행이며 전체 웹 수용은 남아 있다. 같은 소스의 REVIEW browser 선정은
229 passed·2 failed, skip0·2 NEW다. 픽셀 사진 위 AI 영역의 배치를 수정 중이며 첫 수정은
사진의 위치를 개선했지만 원래 두 높이 조건을 아직 충족하지 못했다. 운영 host와 영구 경로는 미정이다.

## 문제와 선택

기존 `dataset/pixel_label_job.py`와 `dataset/edge_capture.py`는 이미 서명된 mapped
entry다. controller는 child CWD를 `config.work_dir`로 고정하지만 importer는 primary
image를 process CWD에서 읽는다. shell의 `cd prepared`는 서명 실행의 CWD를 바꾸지 못한다.

기존 `edge_capture.py import --catalog-relative`를 명시적으로 선택하게 하고
`review_ingest.import_frames`의 `catalog_relative` 입력으로 전달한다. 생략/false는
기존 경로이고, 명시한 값의 type은 정확히 bool이어야 한다. controller·설정·공통 parser와
검수/학습 권한은 바꾸지 않는다. 전역 chdir·catalog 재작성·직접 checkout 실행은 사용하지 않는다.

기본 동작을 catalog-relative로 바꾸면 기존 CWD/ZIP/MCAP producer가 달라진다.
명시 옵션을 택해 이 호환성 비용을 제한한다. catalog 재작성은 원래 hash/계보를 바꾸고,
controller CWD 변경은 다른 작업의 실행 계약을 바꾸므로 채택하지 않는다.

## 소유권과 입력 범위

구현자는 아래 다섯 파일만 소유하며 각 파일은600줄 이하다. 추가 경로가 필요하면
구체적 이유를 먼저 root에 전달한다. 선행 작업의 pixel_label_job 소스/시험은 소유하지 않는다.

- `learning/curation/perception/review_ingest.py`
- `learning/curation/perception/edge_capture.py`
- `test/learning/perception/test_catalog_relative_import.py`
- `test/learning/perception/test_catalog_relative_import_capture.py`
- `test/learning/perception/test_catalog_relative_import_signed.py`

root는 ADR·문서·로그·index·외부 증거와 원격 실행을 맡는다. 공동 편집을 보존하고
소유 경로만 stage한다. reset/stash/clean/rebase/amend·broad add는 사용하지 않는다.

새 모드는 draft 없는 PNG/video 준비 자료만 받는다. 전체 row를 먼저 검사하여 MCAP,
mask, 비어 있지 않은 objects를 기존 prover·draft class 추론·ZIP/image 읽기와 저장 전에
명시적으로 거절한다. 빈 objects는 허용한다. 기존 옵션 없는 MCAP 평가 전용·indexed/
color draft·JPEG·절대/CWD 입력은 유지한다. 선언 session의 canonical화는 원래 선언
reference에만 적용하며 새로 resolve한 basename으로 시각/device를 만들지 않는다.

## 고정한 경로·읽기 계약

1. native POSIX Linux의 dir_fd/O_NOFOLLOW/O_DIRECTORY가 필요하다. 필요한 기능이
   없으면 새 모드는 선택 자료의 내용 읽기/저장 전에 닫히며 CWD fallback을 하지 않는다.
2. caller가 고른 절대 catalog 파일 또는 디렉터리가 root다. filesystem root부터
   no-follow directory descriptor로 선택 ancestry를 연다. 먼저 resolve해 symlink를
   숨기지 않는다. catalog leaf·implicit classes·내부 link도 거절하고 catalog root FD를 고정한다.
3. row image/source_video는 비어 있지 않은 portable 상대 경로다. 절대·Windows drive/
   UNC·backslash·모든 `..`·빈/dot-only leaf를 거절한다. 고정 root FD 기준으로 각
   component를 no-follow로 열고 마지막은 nonblocking/no-follow 및 regular-file fstat을 요구한다.
4. catalog/class/image를 같은 검증 handle에서 각각32MiB/1MiB/32MiB의 최대 limit+1
   바이트만 읽는다. dev/inode/size/mtime_ns/ctime_ns의 전후 변경과 상한을 거절한다.
   capture한 같은 bytes로 SHA·decode·freeze하며 내용을 다시 열어 읽지 않는다.
5. image는 저장 전에 `.png` suffix와 실제8바이트 PNG signature·IHDR 구조를 검사하고
   기존 SHA·실제 decode·dimension 검사를 통과해야 한다. 일반 cv2 decoder는 PNG 전용이
   아니다. 별도 PNG parser·bitdepth/class 정책은 만들지 않으며 기존 JPEG 동작을 유지한다.
6. 선택 namespace/root/file binding을 저장 전에 다시 대조한다. directory가 교체돼도
   고정 FD 밖의 공격자 내용을 읽지 않으며 stale binding은 거절한다. 성공 뒤 미래의
   directory 이동/교체까지 불변이라고 약속하지 않는다. 모든 소유 FD를 성공/실패에 닫는다.
7. video는 고정 root 안의 regular reference여야 한다. handle metadata만 확인하고
   video bytes의 hash/decode는 하지 않는다. 새 opt-in source에는 canonical 절대 참조를
   보존하되 원래 catalog bytes/hash·선언 session/group/SHA/ordinal은 유지하고
   `original_video_verified=false`다. import 전 이동을 지원하며 import 후 이동은 보장하지 않는다.
8. 기존 중복 source/사람 이력은 유지한다. 이전 상대 video 경로를 reimport로 migration하거나
   승인 source를 바꾸지 않는다. 새 source의 절대 참조와 기존 source 보존을 따로 검사한다.
9. 명시 body.classes는 기존 operator 선택 경로이며 catalog-relative로 재해석하지 않는다.
   새 모드에서는 같은 유한/no-follow capture를 적용한다. implicit classes는 고정 root에
   묶는다. 이미 class가 결합된 workspace가 요청 없는 adjacent class를 무시하는 동작과
   명시적인 class conflict 거절을 보존하며 class 의미를 바꾸지 않는다.

## 저장 효과·proof·권한의 한계

전체 row의 새 mode/flag/path/regular-file/suffix/PNG 내용/유한 bytes/SHA/dimension/
class-reference·class-conflict 거절은 bind_classes·원본 freeze·frame/representation/
mask/events 쓰기 전에 끝낸다. 이미 초기화한 빈 training ReviewStore와 파일 inventory를
기준으로 대조한다. controller job receipt는 별도 실행 기록이며 이 금지 효과에 포함하지 않는다.

기존 DB identity/legacy ambiguity/object 충돌 뒤 class/원본 파일이 남는 동작은 이 새
preflight 보장 밖이다. SQL frame transaction과 사람 이력은 유지하지만 DB 사전 검사·
migration·crash/disk 오류의 filesystem rollback은 추가하지 않는다. 실패 증거와 원본은 보존한다.

독립 source proof는 source.video를 자동으로 읽지 않는다. 기존 review_provenance가
별도로 제공된 proof JSON.video_path를 proof.parent 기준으로 읽고, review_dataset이
session/group/videoSHA를 결합해 승인 원본 PNG를 독립 decode와 비교한다. 기존 owner
회귀를 유지하며 여기서 proof·사람 승인·native receipt·reader_verified·admission·모델
READY를 만들어 연결하지 않는다. project-user의 `/api/import` 임의 경로 거절과 기존
local operator 인증/Origin 경계는 유지하며 `/api/learning`과 CORE/Fleet 권한은 늘리지 않는다.

## 실제 서명 fixture와 검증 순서

- [ ] 선행 작업 수용 뒤 정확한 base를 고정하고 소유 시험부터 커밋한다. root가 native
  원격에서 실제 RED를 읽기 전 소스를 바꾸지 않는다. 의존성 skip은 미검증이다.
- [ ] remote checkout의 실제 HEAD를 production rosy_model_code.build로 archive·임시
  Ed25519 서명한다. placeholder 파일/가짜 commit이 아닌 실제 코드이며 파일 hash를
  git object와 대조한다. controller isolated probe의 실제 환경 fingerprint를 사용한다.
- [ ] 임시 installed layout의 실제 Updater/signature/archive/immutable/source machinery를
  실행한다. GPU health·host idle 관찰만 명시 fixture로 대체하며 실제 work lock·entry/
  bootstrap/execute/importer/store를 mock하지 않는다. 빈 legacy root와 무관한 work_dir를 등록한다.
- [ ] 실제 source_expectation을 전달한 installed execute API로 mapped importer를 실행하고
  receipt의 source/environment/manifest/archive/sourceproof/script/entry·exit0를 대조한다.
  일반 controller CLI reimport도 실행하되 이 CLI에는 source_expectation이 없어 source_proof
  receipt가 없음을 구분한다. source_expectation용 CLI/public 옵션은 추가하지 않는다.
  변이마다 그 commit으로 재서명한다.
- [ ] 실제 codec/원본으로 만든 portable 준비 디렉터리를 이동한 뒤 가져온다. CWD에 잘못된
  shadow images를 두어 fallback을 잡고, catalog bytes/hash·정확 PNG·videoSHA/ordinal
  keys·새 절대 video 참조·한 group/component·class binding·pending/all255·완료/배경 false·
  승인 없음·unknown clock/device·원본 video 미검증을 확인한다.
- [ ] 승인 없음 확인 뒤 시험에서만 실제 human fill/approve API를 호출한다. reimport 뒤
  mask/version/status/source/approval/events를 보존한다. 기존 CWD source도 바꾸지 않는다.
- [ ] strict bool, 안전하지 않은 image/video, 내부/외부 final/parent link, 뒤쪽 row의
  suffix/SHA/dimension/class 오류와 기존 mode로는 유효한 MCAP/draft/object의 새 모드
  거절이 각 목표 검사에 도달한다. DB/class/원본/파일 전체 snapshot의 무변경을 대조한다.
- [ ] 올바른 SHA·dimension의 실제 JPEG를 `.png`로 둔 뒤쪽 row가 PNG 내용 검사에서
  거절되는지 확인한다. 선행 valid PNG와 unflagged JPEG control을 포함한다.
- [ ] parent validation/open 사이 실제 directory→외부 symlink 교체를 주입한다. 읽은
  FD inode를 관찰해 외부 bytes0과 최종 stale 거절을 확인한다. 성장 파일은 limit+1
  이하 capture·metadata 변경 거절과 FD baseline 복원을 확인한다.
- [ ] 실제 signed entry/dependency 훼손 또는 manifest 불일치가 import 쓰기 전에 거절된다.
  임시 signed CODE READY/installed fixture는 허용하지만 운영 서비스·GPU 자격은 NOTRUN이다.
- [ ] 선행 pixel/edge/import·review_cycle/draft·독립 PNG/video/full fixed-eval/disjoint>=2·
  MCAP 평가 전용·현재 권한/admission·collaboration 경로 거절·signed source 회귀를 원격 실행한다.
  MCAP 도구 누락과 플랫폼 skip은 통과로 세지 않는다.
- [ ] 같은 GREEN에서 독립 변이: catalog anchor 제거의 signed CWD-shadow 실패,
  전체 lexical containment 거절 제거의 valid `../outside.png` 실제 외부 FD 읽기,
  새 source.video를 상대 참조로 저장했을 때 정확 값/CWD oracle 실패, PNG 내용 검사만
  제거한 JPEG 위장 수용 실패를 확인한다. capture/race/growth guard도 실제 목표 RED/변이로
  증명한다. 선행 다른 거절을 목표 증거로 세지 않고 정확한 정상 control을 복원한다.
- [ ] 독립 spec 뒤 quality·root의 실제 trace 감사·새 고정 검증 기록·D-771/log/master를 갱신한다.
  전체 브라우저 무경로 흐름·실제 운영 프로젝트·사람 자료·모델/학습/평가·HF/복원과
  비시뮬레이션 목표 완료는 별도다. 시뮬레이션·운영 설치·GPU/HF 전송·장치·merge/push는 수행하지 않는다.
