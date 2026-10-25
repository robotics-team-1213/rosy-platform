# 자료를 HF에 보관하고 로컬 사본을 회수하기

관리자는 Learning의 **수집·저장 공간 → 저장 대상·용량 설정**에서 준비·검증·활성화한다. JSON 파일 없이 시작할 수 있고 저장한 값은 프로젝트 DB에 유지되며 재시작 없이 반영된다. [D-884](../../../../docs/adr/D-884-learning-storage-pool-and-local-reclamation.md)와 [API reference v1.321](../../../../docs/reference/ROSY%20API%20&%20Protocol%20Reference.md)이 계약 정본이다.

## 화면에서 시작하기

1. **HF 계정 연결**에서 필요한 계정을 추가한다. 팀이 함께 쓰면 프로젝트 연결을 선택하고 실제 저장소의 읽기·쓰기 범위를 기록한다. **비공개 저장소 준비**에서 기존 저장소를 확인하거나 새로 만든 뒤 저장 설정으로 돌아온다.
2. **저장 대상 추가**로 연결·종류·저장소 이름을 선택한다. 위에 둔 대상을 먼저 배정한다. 같은 계정·조직의 실제 잔여 GiB·원격 여유분·측정 근거·시각·만료는 한 번만 입력한다. 다른 설정을 저장해도 측정 시각이 자동 갱신되지 않는다.
3. 로컬 여유분과 관리 cache 한도를 정하고 **저장 설정 저장**을 누른다. 저장은 신규 배정을 일시중지한다. 과거 작업과 회수·복원은 대상을 모두 제거해도 남는다. 보이지 않는 다른 사용자의 개인 대상은 유지되며 명시적으로 새 배정만 중지할 수 있다.
4. 작은 파일을 비공개 저장소에 보관한다는 동의를 확인하고 **소량 전송으로 연결 검증**을 누른다. 실제 쓰기·고정 revision 전체 읽기가 끝난 대상만 **새 보관 활성화**할 수 있다. 불확실한 결과는 기존 작업의 커밋 확인으로 복구하며 새 연결로 대신 쓰지 않는다. 전송 전 취소로 예약이 반환된 작업은 다시 준비할 수 있다.
5. **완료 자료 준비하고 보관**에서 등록된 전용 exports 폴더 또는 종료된 Isaac 결과를 선택한다. 출처·쓰기 종료를 확인하고 **준비하고 보관**을 누른다. 별도 JSON manifest 작성은 필요 없다. Isaac 결과는 기존 pinned owner의 FINAL 관측·artifact를 읽으며 SDK를 시작하지 않는다. 전송·검증 상태와 고정·회수·복원은 아래 작업 목록에서 이어간다.
6. 폴더 내보내기는 workspace DB의 형제 경로 `storage-data/exports`, 복원은 `storage-data/cache`를 기본으로 쓴다. 호스트에 이미 등록된 위치는 유지하며 UI가 임의 시스템 경로를 등록하지 않는다. 원본 저장소 버전·검수 DB를 exports로 쓰지 않는다.

중단된 Isaac 내보내기는 검증한 prefix만 이어 쓰고 바뀐 파일은 덮어쓰지 않는다. 완료 목록은 `storage-source.json.pending`에 쓴 뒤 원자적으로 게시한다. 이 이름은 예약된 메타데이터다. 게시 직후 정리 중 멈춘 경우에는 같은 inode의 pending alias만 제거하고 재검증한다. 같은 준비 요청은 기존 job을 재사용하며 불확실한 전송을 복제하지 않는다.

프로젝트의 게시·관리 권한, 허용된 연결·비공개 저장소, 유효한 quota가 필요하다. 전송 기능이나 SIM 실행기가 준비되지 않았으면 화면이 다음 운영 작업을 안내한다. 서버 환경·SDK binding 설치는 기존 호스트 운영 절차가 소유하며 앱이 임의 명령·패키지 설치를 받지 않는다.

## 운영 설정

기존 호스트 설정을 seed로 가져오거나 운영 환경을 준비할 때만 다음 절차와 [설정 예제](../learning-storage.example.json)를 사용한다. UI 저장 이후 파일을 고쳐도 DB revision을 덮어쓰지 않는다.

1. Learning의 **계정·외부 자료**에서 HF 계정을 연결한다. 공동 작업은 관리자가 허용한 project 연결을 쓴다. 토큰 대신 연결 ID만 설정한다. 개인 연결은 소유자의 개인 namespace만 사용한다.
2. 기존 private 저장소와 해당 자원(`dataset:namespace/repo` 또는 `model:namespace/repo`)의 읽기·쓰기 권한을 준비한다. 모델 profile은 model 저장소, 데이터/Isaac은 dataset 저장소로 배정한다.
3. `quota_owner`는 repo namespace의 소문자 이름이다. 같은 조직의 토큰·저장소는 quota 한 개를 공유한다. 실제 잔여 bytes, 출처, 측정·만료 시각(UTC Unix 초)을 기록한다. 측정값은 그 시각 이전 업로드를 포함해야 한다. 자동 실시간 조회로 표시하지 않는다. 다른 클라이언트의 쓰기는 실제 서버 용량 거절로 드러날 수 있다.
4. 등록 root를 소유자 전용의 비중첩·비링크 경로로 준비한다. 검수 DB·사람 정답·보정 원본과 분리한다. cache는 관리 사본 전용이다. source의 `reclaimable` 기본값은 false이며 완료된 관리 자료만 담는 root에 한해 명시적으로 켠다.
5. 승인된 기존 검수 앱 Python 환경에 `REVIEW_PYTHON -m pip install -r SOURCE/deploy/model_pc/requirements-learning-storage.txt`로 선택적 업로드 의존성을 준비한다. 로봇/Isaac SDK 환경에 설치하지 않는다. 환경 지문과 서명된 code release의 기존 설치·검증 절차를 따른다.
6. `pool.enabled`를 켜고 승인된 운영 절차로 적용한다. `cache_policy.enabled`는 별도이며 `max_bytes`는 관리 cache 상한이다. 예제의 disabled 값·0 bytes·만료 시각은 실수로 업로드하지 않도록 배정을 막는다. 실제 서비스 재시작·외부 쓰기·삭제는 별도 운영 승인 범위를 따른다.

무료 용량과 public 정책은 [HF 공식 저장 정책](https://huggingface.co/docs/hub/en/storage-limits)을 확인한다. 무료 용량의 지속 제공을 보장하지 않으며 자료를 자동 공개하거나 계정을 새로 만들지 않는다. 기존 단일 `remote_quota` 사전 점검은 호환용 순간 추정이고, 새 pool의 대상별 예약과 별개다.

## 완료된 입력 만들기

실행/episode 단위의 고정된 **별도 export 폴더**에 데이터만 둔다. 기존 content-addressed store 버전·검수 state·운영 원본에 marker를 덧붙이지 않는다. `storage-source.json`은 파일 전체의 bytes/SHA와 출처를 기록하는 보관 선언이며, 학습·시뮬레이션·실물 성공 승인이 아니다.

일반 dataset/model은 생산자가 파일 쓰기를 끝낸 뒤 다음 명령으로 완료 목록을 만든다. provenance JSON에는 출처·라이선스·고정 revision을 기록하며 비밀값은 넣지 않는다.

```text
python SOURCE/learning/curation/perception/storage_source.py seal /REGISTERED/RAW/episode-001 --profile dataset --provenance /PRIVATE/provenance.json
```

Isaac은 승인된 전체 source checkout에서 소유 실행기의 FINAL 기록과 등록된 산출물만 내보낸다. 실행/cleanup이 미확인이면 거절하며, SDK를 시작하거나 owner 원본을 지우지 않는다.

```text
python SOURCE/learning/curation/perception/storage_source.py isaac-export --run-root /EXISTING/ISAAC/RUN_ROOT --run-id FULL_RUN_ID --out /REGISTERED/RAW/isaac-episode-001
```

내보낸 observation·artifact bytes·snapshot과 manifest에 run/seed/source/asset/verifier 지문을 보존한다. 현재 Isaac 실행기는 output 256 MiB 상한 외에 시작 전 1 GiB 여유를 요구하고 실행 중에도 여유를 검사한다. 부족하면 기존 소유 child 종료 경로를 사용하고 성공으로 표시하지 않는다. 다른 프로그램까지 막는 물리 예약은 아니다. USD와 외부 asset 참조 closure는 이 보관 profile의 수용 범위가 아니다.

## 보관·공간 회수·복원

Learning 홈의 **원격 보관과 로컬 사본**에서 등록 위치, 그 안의 상대 폴더, 자료 종류를 고르고 **보관 작업 등록 → 전송·검증**을 선택한다. 여유 있는 허용 target을 새 작업에 고정한다. 전체 payload/readback 디렉터리를 추가 생성하지 않는다. 등록 시 해시를 읽으므로 큰 자료는 시간이 걸릴 수 있다.

- **로컬 정리:** remote 전체 SHA와 현재 권한을 재확인하고 작업 ID를 입력한다. cache 외 source는 `reclaimable: true`도 필요하다. 원격과 이력은 남는다. 추가·변경된 파일이나 바뀐 디렉터리는 삭제하지 않는다.
- **필요 자료 복원:** 같은 연결 세대·저장소·고정 revision만 읽는다. partial에 검증한 뒤 cache 사본을 게시한다. 부족한 공간·실패한 부분 자료를 학습 입력으로 노출하지 않는다.
- **고정 보관:** 사용 예정 자료를 회수에서 제외한다. native experiment trainer와 공식 native cycle은 완료 marker가 있는 입력 디렉터리의 공유 lease를 잡고 정리는 배타 lease를 요구한다. 공식 trainer·평가 자식도 lease를 상속하므로 감독 프로세스 종료 뒤 읽는 동안 보호한다. 별도 소비자는 `storage_files.consumer(path)` 또는 인증된 `StorageJobs.use(actor, id)`의 수명 안에서 읽는다. 수동 외부 소비자는 먼저 고정 보관한다.
- **캐시 공간 확보:** 프로젝트 전체 cache 크기를 합산하고 요청자 자신의 오래된 검증 cache만 회수한다. source root·pin·사용 중 자료는 건너뛴다. 공간 부족이면 막힌 상태를 남기며 복원은 worker 잠금 안에서 용량을 다시 점검한다. 게시 권한으로 여유 공간에 복원할 수 있고, 다른 사본의 실제 회수에는 관리 권한이 필요하다.

원격 단일 사본은 독립 백업과 다르다. 계정이나 원격 자료를 잃으면 복원을 보장할 수 없으므로 원본 정리 화면에서 확인한다. 검수 DB·사람 정답·보정 원본은 별도로 유지한다.

## 중단과 복구

- 전송 전 **대기 취소**는 예약을 돌려주며 원본을 유지한다. 시작됐거나 결과가 불확실한 예약은 자동 해제하지 않는다.
- commit 뒤 읽기만 실패하면 같은 작업의 **전송·검증**으로 같은 revision을 재검증한다. 계정을 바꿔 재업로드하지 않는다.
- `원격 결과 확인 필요`이면 HF의 `ROSY storage 작업ID` 커밋을 찾아 **기존 커밋 확인**에 전체 SHA를 입력한다. 원래 manifest의 실제 bytes가 맞을 때만 확정하며 원격 쓰기는 하지 않는다. 잘못된 SHA는 기존 보류 상태를 보존한다.
- 사진 등 파일이 많은 자료는 32개씩 기록한다. 확인한 묶음은 다시 쓰지 않는다. 중간 묶음을 복구하면 대기로 돌아가며 **전송·검증**으로 나머지를 같은 대상에 이어 쓴다. 전체 최종 revision 검증 전에는 로컬을 정리하지 않는다.
- 회수/복원 중 서버가 멈추면 같은 작업을 재시도한다. 격리된 정리 폴더와 검증된 게시 디렉터리를 원장과 대조한다. 미등록 파일이나 디렉터리 교체를 발견하면 임의로 지우지 않는다.
- 재연결로 generation이 바뀌거나 권한이 철회되면 다른 자격증명으로 이어가지 않는다. 이력과 자료를 보존하고 기존 권한 경계에서 운영 복구 범위를 정한다.

host 회귀, 실제 HF 왕복, Isaac SDK 실행, 모델 평가와 실물 수용은 각각 별도 증거로 기록한다.

## 착지 전 소스 검증 · 2026-10-26

- `07943e133d`: pool/jobs/hub/source 및 세 문서 하네스 시험 원격 72 passed, 0 skipped, NEW0. 같은 revision에서 실제 브라우저·화면 구조·API 버전 계약 21 passed, 0 skipped, NEW0. 취소 원자성, 다중 사용자 캐시 예산, 늦게 추가된 파일, 디렉터리 교체, 불명확한 묶음 복구와 학습·독립 평가의 소비자 lease를 포함한다.
- `cf7ad3f529`: 저장 모듈·OMX 전체 host suite·Isaac worker 497 passed / 20 skipped, NEW0. 이후 `4030c29401`에서 독립 평가 경로 보호를 추가하고 관련 저장·OMX·하네스 시험을 재실행했다. 의존성별 실제 학습 시험의 skip은 통과로 계산하지 않는다.
- FULL 선택을 축소하지 않고 `1e30ca7d1c`의 24개 invocation을 모두 원격 실행했다. 원시 결과는 33,776 passed / 2,222 skipped / 7 failed다. 이번 변경의 6개 실패는 SQLite descriptor 해제·로그/ADR/생성 index·화면 button 의미·API changelog 행을 수정한 뒤 위 72/21 시험으로 확인했다. 남은 G1 timing은 기존 quarantine 항목이며 `4030c29401` 단독 실행의 최초 실패 뒤 공식 1회 rerun에서 통과했다(NEW0 / FLAKY1). 원시 FULL 전체 통과로 표시하지 않는다.
- 독립 전체 리뷰와 후속 수정 리뷰에서 중대한 미해결 지적은 없다. 실제 HF 왕복·Isaac SDK·모델 fit·운영 데이터 회수·서명 artifact 설치·장치 수용은 수행하지 않았다. 운영 설정은 꺼진 예제를 제공하며, 실제 활성화는 별도 운영 작업이다.
- CE: 해당 없음 — 복구·권한·소비자 수명 판단은 D-884, 이 안내와 회귀 시험에 보존한다.

## UI 설정·준비 흐름 확장 검증 · 2026-10-26

기존 소스 `23513bac1d` 이후 UI 설정과 완료 자료 준비를 확장했다. `00e54f4c82`의 공식 영향 선택은 affected/no escalation이며 원격 3,563 passed / 326 skipped, NEW0다. 파일 누락 release 부정 시험·기존 검수/계정/API/문서·저장 전체 suite를 포함한다. skip을 해당 실행의 브라우저 또는 SDK 성공으로 계산하지 않는다.

`0e65a052fa`에서 명시적으로 브라우저를 켠 설정/기존 보관 HTTP·공용 입력 검증은 47 passed / 0 skipped / NEW0다. 320px 밝게·1440px 어둡게에서 JSON 없는 최초 설정, 실제 전송 의미의 provider 경계, 활성화, 준비·보관, 회수·복원, 재시작, 미저장 수정 보호를 확인했다. `007e6c3b5a`는 펼친 설정 폼에서도 가로 넘침을 검사하며 같은 두 흐름을 다시 실행해 2 passed / 0 skipped / NEW0다. 실제 캡처를 확인했고 신규 버튼의 >=44px 누름 면도 검사했다.

`b6600797a5`의 별도 저장 core/setup/source 시험은 92 passed / 0 skipped / NEW0다. 독립 리뷰에서 발견한 빈 대상 목록 이후 과거 복원, 취소 후 새 예약, 중단된 Isaac 내보내기, 기존 바이트 보존과 원자적 완료 목록 게시를 재현해 고쳤다. 파일 열기의 O_EXCL 누락을 실제 같은 길이의 바뀐 파일로 검사하고, 부분 marker와 게시 직후 link/unlink 종료 구간도 실제 파일로 확인한다. 최종 리뷰에 중대한 미해결 지적은 없다.

각 실행은 커밋된 격리 브랜치를 공식 원격 runner로 보내고 known_failures와 비교했다. provider 대역과 합성 FINAL RunStore는 SDK·실제 HF·실물 수용을 증명하지 않는다. 이 작업에서 운영 활성화·외부 쓰기·SDK/패키지 설치·운영 자료 삭제·착지·push는 하지 않았다. 실제 계정의 소량 쓰기/읽기는 운영자가 새 UI의 동의·검증 동작으로 실행한다. CE: 해당 없음 — 복구와 레이아웃 판단을 구현·회귀·주석·D-884/이 안내에 보존했다.
