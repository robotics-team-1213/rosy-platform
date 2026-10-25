# 자료를 HF에 보관하고 로컬 사본을 회수하기

관리자는 [설정 예제](../learning-storage.example.json)를 Git 밖 private 설정으로 복사해 기존 `--storage-config`에 연결한다. [D-884](../../../../docs/adr/D-884-learning-storage-pool-and-local-reclamation.md)와 [API reference v1.321](../../../../docs/reference/ROSY%20API%20&%20Protocol%20Reference.md)이 계약 정본이다.

## 운영 설정

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
- **고정 보관:** 사용 예정 자료를 회수에서 제외한다. native experiment trainer는 완료 marker가 있는 입력 디렉터리의 공유 lease를 잡고 정리는 배타 lease를 요구한다. 별도 소비자는 `storage_files.consumer(path)` 또는 인증된 `StorageJobs.use(actor, id)`의 수명 안에서 읽는다. 수동 외부 소비자는 먼저 고정 보관한다.
- **캐시 공간 확보:** 활성 정책에 따라 오래된 검증 cache만 회수한다. source root·pin·사용 중 자료는 자동 회수하지 않는다. 공간 부족이면 막힌 상태를 남기며 복원은 worker 잠금 안에서 용량을 다시 점검한다.

원격 단일 사본은 독립 백업과 다르다. 계정이나 원격 자료를 잃으면 복원을 보장할 수 없으므로 원본 정리 화면에서 확인한다. 검수 DB·사람 정답·보정 원본은 별도로 유지한다.

## 중단과 복구

- 전송 전 **대기 취소**는 예약을 돌려주며 원본을 유지한다. 시작됐거나 결과가 불확실한 예약은 자동 해제하지 않는다.
- commit 뒤 읽기만 실패하면 같은 작업의 **전송·검증**으로 같은 revision을 재검증한다. 계정을 바꿔 재업로드하지 않는다.
- `원격 결과 확인 필요`이면 HF의 `ROSY storage 작업ID` 커밋을 찾아 **기존 커밋 확인**에 전체 SHA를 입력한다. 원래 manifest의 실제 bytes가 맞을 때만 확정하며 원격 쓰기는 하지 않는다. 잘못된 SHA는 기존 보류 상태를 보존한다.
- 사진 등 파일이 많은 자료는 32개씩 기록한다. 확인한 묶음은 다시 쓰지 않는다. 중간 묶음을 복구하면 대기로 돌아가며 **전송·검증**으로 나머지를 같은 대상에 이어 쓴다. 전체 최종 revision 검증 전에는 로컬을 정리하지 않는다.
- 회수/복원 중 서버가 멈추면 같은 작업을 재시도한다. 격리된 정리 폴더와 검증된 게시 디렉터리를 원장과 대조한다. 미등록 파일이나 디렉터리 교체를 발견하면 임의로 지우지 않는다.
- 재연결로 generation이 바뀌거나 권한이 철회되면 다른 자격증명으로 이어가지 않는다. 이력과 자료를 보존하고 기존 권한 경계에서 운영 복구 범위를 정한다.

host 회귀, 실제 HF 왕복, Isaac SDK 실행, 모델 평가와 실물 수용은 각각 별도 증거로 기록한다.
