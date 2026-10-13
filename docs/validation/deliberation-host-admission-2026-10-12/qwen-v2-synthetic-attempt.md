# Qwen v2 합성 연결 시도와 진단 경계

2026-10-12, AI PC의 비특권 임시 환경에서 승인된 로컬 Qwen 연결을 확인했다. 운영 서비스나 Fleet worker를 활성화하지 않았다. v2 import closure의 동일 소스 snapshot과 hash 고정 Python venv를 사용했다.

## 실제 관측

- 고정 loopback `/api/ps`에서 `qwen3-vl:8b-instruct`, digest `0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319`, context 8192를 검사했다.
- 합성 사건 `synthetic-pinky/v2-codec-smoke/g1`, `line_follow`, `human/reobserve`, 원래 사건 input hash와 v2 schema를 고정했다. 입력은 2,843 bytes였다. 자유 도구·실제 로봇 명령·사람 또는 현장 데이터를 사용하지 않았다.
- 자식 제공자 프로세스를 1회 실행했다. 호스트 최대 31초, 내부 30초와 출력 1,024 토큰 제한이며 자동 재시도는 없었다. 호출 전 새 파일의 `O_EXCL`과 fsync로 사용 표식을 기록했다. 표식을 삭제하거나 같은 시도를 재실행하지 않았다.
- 실제 결과는 exit 1, `HOLD / QWEN_V2_PROVIDER_FAILED`였다. 유효한 모델 응답·사용량·판정 receipt는 확보하지 못했다. upstream 모델 호출이 실제 실행됐는지는 이 출력만으로 확인할 수 없다. 비용·정확도·실제 처리·물리 종결은 미확인이다.
- 이어 모델 호출 없이 HTTP 함수를 거절 stub으로 교체한 진단에서 입력 검증이 `HTTP_BOUNDARY_REACHED_NO_MODEL_CALL`까지 진행됨을 확인했다. 별도의 빈 입력 자식 import 진단은 exit 1, stderr 없음, 기존 `LOCAL_PROVIDER_FAILED` envelope였다. Ollama system journal 조회에는 해당 기록이 없었다. 이 검사로 실제 시도의 HTTP 또는 응답 실패 원인을 확정하지 않는다.

스크립트와 임시 환경은 비공개 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/scratch/qwen-v2-*`와 AI PC의 해당 임시 stage에 둔다. 영속 root 설치나 서비스 계정 격리의 증거로 사용하지 않는다. GLM 첫 호출 표식과 제공자 키는 접근하지 않았다.

## source 진단 보강

기존 CLI는 모든 예외를 동일 envelope로 변환하므로 경계를 구분할 수 없었다. 원래 state/reason/exit를 유지하고 추가 `failure_kind`를 `TIMEOUT`, `TRANSPORT`, `VALIDATION`, `INTERNAL`의 고정 enum으로만 출력하도록 보강했다. 예외 문구·제공자 원문·환경·endpoint는 출력하지 않는다. 이 변경은 실제 실패 원인의 수정이나 호출 성공을 주장하지 않는다.

시험을 먼저 추가한 `446c05b511`은 적격 AI PC 10.2GB에서 예상한 4 NEW였다. `6ce30937e7`의 관련 3개 파일 시험은 같은 자원 하한을 충족한 AI PC에서 64 passed, exit 0이다. 로그는 위 세션의 `logs/qwen-diagnostic-red/run-1.txt`와 `logs/qwen-diagnostic-green/run-1.txt`다. 실제 모델 호출 없이 예외 분류·원문 비노출·단일 호출을 검증했다.

운영 admission·calibration·현장 수용은 HOLD다. 다음 연결 시험에는 제공자 요청 경계와 검증 결과의 제한된 receipt를 남겨 원인을 구분해야 하며, 이번 표식을 초기화해서 재호출하지 않는다.

독립 source review의 timer 정리 지적을 반영했다. 성공·실패 반환 모두 타이머를 해제하고 기존 signal handler를 복원한다. 회귀를 먼저 추가한 `311e101b37`에서 예상한 5 NEW를 확인한 뒤 commit `fa583898b6`의 관련 3개 파일이 적격 AI PC 9GB에서 65 passed, exit 0, known-failures 신규 실패 0건과 lint를 통과해 로컬 main에 착지했다. 고정 로그 복사본은 위 세션의 `logs/qwen-timer-integrated-green/run-1.txt`이며 독립 source 재검토의 중요 지적은 해소됐다. 이 수정 뒤 실제 모델을 다시 호출하지 않았다.
