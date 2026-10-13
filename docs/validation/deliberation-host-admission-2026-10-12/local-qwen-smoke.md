# 실제 호스트 수용과 로컬 Qwen 스모크

- Source validator commit SHA `742a72bed96aae1cc995297366036ef9e56b6924`.
- 사용자 SSH 재실행 결과: `PASS_HOST_OFFLINE_ONLY`, `OFFLINE_HOST_ONLY`, 13개 검사 모두 true. 취소·시간 초과 자손 종료, namespace, cgroup, 빈 환경과 고정 경로, 전용 계정, read-only runtime을 확인했다.
- 후속 readback: 설치된 preflight SHA256 `6649d2f85bbae99432aba2325893250de9963aed8927dc1743d7df09445d56ac`, 전용 UID 997 / GID 984, 단독 그룹. root 실행 수용 자체는 사용자 터미널 출력 증거다.

사용자가 로컬 Qwen 무료 호출을 첫 대상으로 선택했다. AI PC의 기존 loopback 모델 서비스를 대상으로만 요청했다. 적재 모델 `qwen3-vl:8b-instruct`, digest `0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319`를 요청 전후 확인했다. 사용 옵션은 num_ctx=8192, num_predict=256, temperature=0, seed=42다. HTTP timeout 25초, 응답 16KiB 상한, 외부 제공자 호출 0회다.

합성 관측 부족 사건에서 실제 모델 응답은 strict JSON schema와 기존 `rosy.decision.deliberation.opinion`의 사건·generation·input_hash·선택·증거 검증을 통과했다. 최초 호출 2.021초 / 128 생성 token, 반복 검증 2.210초 / 130 token이며 3초 freshness 안에 완료했다. 응답은 reobserve 및 insufficient_evidence였다. 이는 모델 정확도 지표가 아니다.

같은 모델에 새 합성 사건으로 실제 호출하여 기존 Supervisor에 전달했다. 결과는 `HOLD / UNRESOLVED_OBJECTION`, calls=1, choice=null, action_admissible=false, cost_complete=true / cost_usd=0.0이다. 다른 profile 함수는 호출 시 실패하도록 두었고, 관측 부족 응답에서 두 번째 호출이 없음을 assert했다. 다중 모델 독립성이나 합의를 시험하지 않았다.

- Terminal result: SSH exit 0; `PASS_LOCAL_MODEL_TRANSPORT_ONLY` 및 `PASS_SYNTHETIC_SUPERVISOR_HOLD`.
- Raw receipt: `X:/DevTemp/projects/rosy-platform/2026-10-12--023355--deliberation-host-admission--4a3286/logs/qwen-supervisor-smoke.jsonl`.
- Raw SHA256: `f0fc9f100aa3f73a3c918359cb1b5cf44954b45926da88b551dea63c90166ad7`.
- 재현 입력/실행 script: 같은 세션 `scratch/qwen-supervisor-smoke.py`. 기존 Decision 소스를 고정 commit에서 별도 임시 경로에 stage하여 사용했다.

이번 모델 요청은 기존 AI PC loopback 서비스의 수동 transport smoke다. 네트워크 차단 sandbox의 제공자 접속을 승인하거나 자동 worker에 연결하지 않았다. 호스트 OFFLINE 수용과 모델 transport 수용은 별도 증거다. 실제 Pinky 사건·사람 정답 기반 독립 평가·FIELD는 미확인이다.

별도 실제 CLI inventory: Claude Code 2.1.274, OpenCode 1.18.35. OpenCode run help에는 --pure가 있고 현재 번역기의 --standalone은 없다. 버전별 실행 번역과 설정·tools·token cap·격리 실행 수용은 병렬 작업의 별도 관문이다. 개인 credential이나 provider 설정은 읽지 않았다.

## V2 설치·무호출 readback

2026-10-12 후속 실제 AI PC readback은 frozen source `cfcba82ddf`의 별도 V2 준비 경로를 확인했다. 앞의 실제 구버전 transport 성공을 V2 성공으로 바꾸지 않는다. Qwen V2 시도 표식이 남아 있으며 이전 `QWEN_V2_PROVIDER_FAILED`의 실제 응답·원인은 미확인이다. 표식을 삭제하거나 모델 요청을 재시도하지 않았다.

시스템 Python에는 pydantic이 없지만, 기존 `import-check-venv`에서 합성 V2 입력의 순수 검증은 차단한 HTTP 경계까지 도달했다. 같은 전용 interpreter의 자식 모듈은 모듈 누락 없이 잘못된 입력에 redacted HOLD를 반환했다. 이 두 진단은 네트워크·모델 호출 0회다. 시스템 interpreter의 의존성 누락은 이번 진단 결과이며 이전 실패의 원인으로 단정하지 않는다.

별도 `/api/ps` 메타데이터 요청 1회에서 `qwen3-vl:8b-instruct`와 위 고정 digest의 resident 조건을 확인했다. 결과는 PASS_RESIDENT_METADATA_ONLY, 모델 호출 0회·runtime_admitted=false·field_accepted=false다. 실제 생성·응답 JSON·정확도·보정·운영 수용을 입증하지 않는다.

GLM V2 root 설치 디렉터리는 없고 관리자 준비 스크립트는 남아 있다. 스크립트 SHA256은 `5ec4699eed5625c58a7e5ec623b7eab23a1fe750148c0be756c130f5f3218e11`이다. 스크립트는 manifest·offline wheels·root 소유 runtime·import probe·오프라인 preflight만 처리하고 credential importer나 provider 호출을 실행하지 않는다. `sudo -n true`는 password required로 거절돼 관리자 터미널 실행이 필요하다. 사용자에게 기존 OpenSSH 준비 명령과 마지막 JSON/PREPARE_EXIT readback을 요청했다. 비밀번호·키·토큰은 요청하지 않았다.

이번 readback 요약은 세션 `logs/v2-runtime-readiness.json`에 있다. source 최신 병합과 이 구버전 frozen runtime의 준비 상태는 별도다. 실제 Qwen/GLM V2 품질·동작·배포·현장 수용은 HOLD를 유지한다.
