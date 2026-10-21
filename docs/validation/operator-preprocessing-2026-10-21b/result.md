# D-831 인용·Unicode 경계 재검증

2026-10-21, source commit `5d90c8d670faadd95b54fac41d0a7a24c071ae95`. [이전 기록](../operator-preprocessing-2026-10-21/result.md) 이후 인용된 NFD 등록 이름 충돌과 동작·부정·지시어의 검색 누락을 보완했다. 검색용 NFC/공백 사본을 사용하고 원문·모델 입력은 보존한다. 유의미한 공백을 가진 등록 이름이 있으면 혼합 조합형도 보존하도록 입력 사본 정규화를 생략한다. 실행 권한과 새 Discord worker 차단은 유지한다.

## 검증

- `dddacf86e8` 인용 NFD 회귀 RED5/37 → `648808c2c5` GREEN42.
- `3b71f69319` 혼합 조합형 이름 공백 RED1/42 → `5d90c8d670` GREEN43.
- 독립 계약 검토는 source `5d90c8d670`의 관련 지적이 해결됐고 새 blocker나 권한 확대를 보고하지 않았다. 검토자는 테스트를 직접 실행하지 않았다.
- 기존 고정 Qwen 모델·digest·8192/1024 설정은 이전 기록과 같다. Model PC에서 위 SHA에 `test/test_operator_preprocessing_benchmark.py test/test_operator_model_acceptance.py -s` 실행: **3 passed in 81.70s**, 비교군19/19·Console26/26·Discord46/46. 중간 source `648808c2c5`도 같은 세 suite를 통과했다.

최종19개 비교군 입력14,431토큰·생성511, 호출 p50 546.96ms/p95 650.79ms. baseline 입력14,426 대비 **절감 없음**. 관측 시각의 숫자도 토큰화되어 같은 질문 구성의 입력 토큰이 약간 달라진다. 19개 단일 실행의 nearest-rank 지연은 성능 보장이 아니다. Discord46개 입력121,495토큰이며 같은46개 변경 전 측정은 없다.

시스템 TEMP `operator-preprocessing/model-final/`에 로그와 SCP 사본을 보존했고 SHA256을 검증했다.

| 파일 | 무결성 값 |
|---|---|
| `measurement.json` | SHA256 `4631e9c4b84b5c58164470cd1e39adc0a9233a43aa6d437e6680cdd6b9ebb1ac` |
| `discord-proof.json` | SHA256 `bc66ad449027175281cd9348d1fc4c87063ed191e220db5c8d7651cb5f621eaa` |
| `operator-proof.json` | SHA256 `7dbb46d7b1fa118652a705bbb134c7df45ac96f699d4ebe753ed85bcb463cdb9` |

## 착지 시도

첫 main 병합의 D-831 Accepted/Proposed 색인 중복을 `312ad849f2`로 정리했다. 두 번째 착지는 추가 인용 NFD 지적 때문에 Ctrl-C로 중단했고 main을 갱신하지 않았다. source `35acf5b1dd`의 관문250 passed, Fleet6085 passed/323 skipped, 기본 관제 브라우저118 passed를 확인했다. 추가 브라우저는 중단 당시 미완료로 완료 수에 넣지 않는다.

중단 후 원격 플랫폼 작업의 최종 로그는 12976 passed/1155 skipped/4 failed였다. 하나는 이전 기록의 해시 행에 무결성 표기가 없어 비밀값 탐지기가 지적한 것으로, `fcf2eb6957`에서 값·시험 결과를 바꾸지 않고 SHA256 표기만 보완했다. 나머지는 station-camera lifespan 시간 초과와 platform G1 시간 제한 2개다. 별도 재현 및 main 비교는 TEMP `platform-failure-recheck/`, `platform-main-recheck/`에 보존하며 이 기록에서는 통과나 기존 실패로 간주하지 않는다.

최종 영향 회귀·main 착지는 이 기록 이후 `tools/land.py --tests auto --no-prune`로 수행한다. TEMP `operator-preprocessing/landing-3.txt`와 `rosy-land/feat-operator-preprocessing/`의 최종 판정으로 확인한다. 모델 receipt는 위 SHA의 증거이며 이후 SHA의 보호 설치 승인이 아니다.

새 자연어 확인 API·보호 운영 설치·push·실음성·장치/현장 수용은 미실행이다. 새 Discord profile은 제안만 기록한다. 정확한 호출 전 토크나이저 없이 응답 후 입력7168/생성1024 검사만 제공한다.
