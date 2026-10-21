# D-831 전처리 소스·실제 모델 검증

2026-10-21, Model PC의 기존 고정 `qwen3-vl:8b-instruct`, digest `0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319`. 모델 다운로드·보호 설치·Discord 메시지·장치 명령은 실행하지 않았다.

최종 모델 시험 source는 `d7fedbc9ab232057f708da385f3aacdcb97e2d72`. 원격 runner에 `ROSY_RUN_OPERATOR_MODEL_TESTS=1 ROSY_OPERATOR_EVALUATION_OWNER=model_pc ROSY_OPERATOR_SOURCE_COMMIT=<SHA> test/test_operator_preprocessing_benchmark.py test/test_operator_model_acceptance.py -s`를 전달했다. 결과는 **3 passed**, 기존 Console 비교군 19/19, 확장 Console 26/26, 새 Discord profile 46/46다. 이는 테스트 입력의 의미 분류·정형 후보 증거이며 실제 음성·운영 채널·장치 수용이 아니다.

## 전후 측정

같은 19개 ko/en 질문·사실 구성과 고정 모델·8192 context/1024 생성 예산을 사용했다. 관측 시각과 전처리 profile은 각 실행에 맞게 달라진다. 지연 분위수는 19개 단일 실행의 nearest-rank이며 성능 보장을 뜻하지 않는다.

| 항목 | baseline `267fdf1ef8` | 채택 source `d7fedbc9ab` |
|---|---:|---:|
| 의미 통과 | 19/19 | 19/19 |
| 실제 입력 토큰 합계 | 14,426 | 14,427 |
| 실제 생성 토큰 합계 | 517 | 505 |
| 전체 broker 호출 p50 ms | 571.72 | 536.16 |
| 전체 broker 호출 p95 ms | 725.70 | 687.03 |

입력 토큰은 1개 증가했다. **토큰 절감 성공으로 보지 않는다.** 질문 사본 제거는 한국어 CONTROL을 CLARIFY로 바꾸었고 과도한 Discord 정책 축약도 여러 의미·인자 검증을 실패했다. 원문 JSON 질문과 정규화한 읽기용 사본은 유지하며 인증 식별자와 전처리 해시만 모델 문맥에서 제외했다. Discord 46개 입력 토큰 합계는 121,495이며 비교 가능한 변경 전 46개 측정이 없어 전후 절감을 주장하지 않는다.

## 원격 RED→GREEN·검토

- `267fdf1ef8`: 전처리 미구현 RED18/1 → `c9866fcad8` GREEN27.
- broker/Fleet/보호 설치·신규 profile 검증을 순차 RED→GREEN으로 확인했다. `32de556655` 연결 범위 166 passed.
- 독립 검토 지적: 서로 다른 `North  gate`/`North gate`를 정규화해 잘못 선택할 가능성, 장소-only STATUS의 잘못된 빈 로봇 표기. `ebdb96c9ed` RED3/33 → `8454618b94` 전처리·보호 설치 123 passed.
- NFD 한글 등록 이름+유의미한 공백의 결합 사례: `a230df6b3d` RED1/36 → `d7fedbc9ab` GREEN37.
- 독립 계약 재검토는 `d7fedbc9ab`의 이름 보존·새 profile 실행 worker 차단·기존 Console 거래 경계에서 남은 blocker를 보고하지 않았다. 검토자는 실제 모델/장치 시험을 직접 실행하지 않았다.

실제 모델 실패 이력도 보존한다: `48ae0bb409` Console 비교군/확장 통과, Discord 4개 실패와 입력 토큰 17,152; `32de556655` 비교군18/19·Console25/26·Discord5개 실패; `84f20be750` 비교군18/19·Console25/26·Discord14개 실패. 이 결과는 승격 증거로 쓰지 않았다.

## 증거 위치와 hash

개발 호스트 시스템 TEMP의 `operator-preprocessing/` 아래에 원격 로그를 보존한다. 실제 주소·키·운영자 신원은 공개하지 않는다. 사본은 SCP 후 SHA256을 확인했다.

| 상대 위치 | SHA256 |
|---|---|
| `model-baseline/measurement.json` | SHA256 `e6fb9f5ac7ceb96d9eeee827c7b8f69f5e95f2c425afaea7ef2a5e1a7d0f8876` |
| `model-candidate-4/measurement.json` | SHA256 `a34e3ba23f5891f6df97aaa66960371e504b92a755bcc28edcec10d97223fa7f` |
| `model-candidate-4/discord-proof.json` | SHA256 `55689228e2517815a2f1da549e7ce15e0c608d49f245dd2747e5d28a309187ef` |
| `model-candidate-4/operator-proof.json` | SHA256 `1ee320d3b3da1dab6e8cba9115670a1216dd6ee0723ff036064ec0326fb3d194` |

시험 로그는 `model-baseline/run-1.txt`, `model-candidate{-2,-3,-4}/run-1.txt`, `review-red/`, `review-green-2/`, `nfd-review-{red,green}/`다. baseline 및 후보별 UUID basetemp는 Model PC의 승인된 `rosy-test` 루트에 보존했다. receipt는 해당 SHA에 결속된 시험 산출물이며 이후 SHA/운영 설정의 승인을 대신하지 않는다.

최종 영향 회귀와 로컬 main 착지는 이 기록 커밋 뒤 `tools/land.py --tests auto --no-prune` 정식 FIFO 관문에서 수행한다. 해당 실행 로그와 결과는 시스템 TEMP `operator-preprocessing/landing.txt` 및 도구가 기록한 `rosy-land` 디렉터리로 분리한다. 이 동결 기록의 모델 결과를 이후 병합 SHA의 실제 모델 실행으로 바꾸어 표기하지 않는다.

## 남은 범위

새 자연어 확인 API·확인 만료/후보 수명은 미구현이다. 새 Discord profile은 원장/응답의 제안으로만 닫고 기존 Console의 명시적 좌표 접수를 유지한다. 정규식 차단은 보수적인 보조 수단이며 완전한 형태소 분석기가 아니다. 정확한 호출 전 토크나이저는 없고 실제 응답 입력7168/생성1024 검증만 있다. 보호 snapshot 설치·서명된 운영 배포·원격 push·마이크·STT/TTS 모델 품질·장치 실행/완료는 이 시험의 증거 범위에 포함하지 않는다.
