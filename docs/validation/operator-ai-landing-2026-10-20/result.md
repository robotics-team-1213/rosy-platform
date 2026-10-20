# 관제 운영자 AI 착지 검증 — 2026-10-20

이전 [운영 구조 검증](../operator-ai-operations-2026-10-20/result.md)의 후속 기록이다. 이전 결과는 보존한다. **소스 착지 관문은 통과했으며 운영·장치·음성 현장 수용은 수행하지 않았다.**

## 소스와 병합

- 검증·착지 commit: `6c1e5a5267708db06e13675160674726a1ff0577`.
- 기준 main commit: `7b2ffac91f59d42fefe292c5be5d18e9cc2ab5be`. `tools/land.py --tests auto --no-prune`의 대기열·안전·커밋별 크기·원격 시험 관문을 통과해 로컬 main에 33개 커밋을 반영했다. 원격 push는 수행하지 않았다.
- D-810/D-821, API v1.290과 main의 스테이션 충전 계약·초기화 인자를 함께 보존했다. 공유 main의 다른 세션 파일은 수정하지 않았다.
- Fleet CLI/app의 측정 제한은 885/937이다. 공통 브라우저 서버를 `test/console_browser_site.py`로 분리해 기존 큰 시험 파일을 3884→3835줄로 줄였고 기존 fixture import 경로를 유지했다.
- 독립 검토는 초기화·API 이력·모델 입력/오류 처리와 최종 fixture 분리를 확인했다. 크기 제한 지적을 수정했으며 최종 분리 범위의 Important/Critical 지적은 없었다. 실행 증거는 아래 시험 결과다.

## 실행한 검증

pytest는 모델 PC·AI PC의 커밋 스냅샷에서 실행했다. 노트북에서 pytest를 실행하지 않았다. 모든 FULL/브라우저 실행이 이 SHA에서 끝났으며 캐시 통과로 대체하지 않았다.

| 범위 | 결과 | 원본 위치 |
|---|---|---|
| FULL 22개 실행 | **30,196 통과, 실패 0, 건너뜀 1,953** | `$TEMP/operator-ai/final-full-6c-green/run-1-{1..22}.txt` |
| 실제 Chromium을 켠 브라우저 회귀 4개 실행 | **532 통과, 실패·건너뜀 0** (118/101/162/151) | 같은 폴더 `run-1-{23..26}.txt` |
| 구조·계약 선행 검사 | 250 통과, 경고 40 | 같은 폴더 `run-g1-1.txt` |
| 수정한 공통 서버·세션·복원·추적 집중 검증 | 21 통과, 건너뜀 0 | `$TEMP/operator-ai/root-console-fixture-imports-green/run-1.txt` |
| 실제 고정 모델, 독립 model_pc 평가 | **한국어 9 + 영어 10, 19/19 통과**, pytest 시험 1개 | `$TEMP/operator-ai/final-model-bilingual/run-1.txt`, `evaluation.json` |
| Console Node 전체 | 343 통과, 실패·건너뜀 0 | `$TEMP/operator-ai/merge-console-node.txt` (UTF-16LE) |

Node 실행 commit은 `476a8345c35cd80d455d1dad15a9ce2520b76ea2`다. 그 뒤 최종 소스까지 바뀐 것은 시험 파일·fixture·크기 제한표뿐이며 제품 JavaScript는 동일하다. 위 집계는 실행별 결과이며 중복 실행이나 subtest를 고유 시험 수로 합산하지 않는다. 브라우저 묶음에는 HTTP 자산 회귀 1개가 포함된다.

FULL과 브라우저 26개 로그의 요약·SHA-256은 [run-metadata.json](run-metadata.json)에 있다. 각 실행의 known-failures 비교는 NEW/known/flaky 모두 0이다. 린트는 오류 0, 기존 경고 32이며 안전·커밋별 크기 검사를 통과했다. 로컬 착지 기록은 `.git/rosy-land/6c1e5a5267708db06e13675160674726a1ff0577.json`이다.

실제 모델은 기존 `qwen3-vl:8b-instruct`, digest `0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319`를 사용했다. 새 가중치를 내려받지 않았다. 최종 원본 평가 파일의 SHA-256은 `ff7ea0f6f210050cf70586c9e7adf071b8047c6a4ea23e727e4e2454221f9d29`다. 고정 개발 사례의 분류·거절·근거 계약 검증이며 일반 언어 정확도나 음성 품질 점수가 아니다.

## 발견한 실패의 판정

공통 시험 HTTP 서버는 파일명을 추측해 `assistant.js`를 찾았으나 실제 등록 경로는 `assistant/panel.js`였다. 그 404로 Console 초기화가 중단돼 세션/복원 10건과 추적 화면 4건이 실패했다. 모든 등록 자산을 HTTP로 읽는 회귀가 `79a0a60199`에서 404로 실패했고, 운영 서버의 `CONSOLE_ASSETS`를 사용하는 수정 뒤 최종 21개 집중 검증과 532개 브라우저 회귀가 통과했다. 기존 시험을 삭제·약화하거나 timeout을 늘리지 않았다.

실패한 이전 통합 SHA `476a8345c3`의 원본은 `$TEMP/operator-ai/merge-full-476-red`에 보존했다. 그 실행의 FULL 22개는 30,196 통과·1,952 건너뜀이었지만 추가 브라우저 실행은 14개 실패했다. 원인을 확인한 뒤 구버전에서 같은 실패를 반복하던 브라우저 작업 2개는 중단(exit 143)했으며 통과로 계산하지 않았다.

이전 기록의 JPEG recorder/native updater 종료 실패 2건은 기준 SHA, 집중 검증, 이번 통합 FULL에서 재현되지 않았다. 실패 시 PID/부모/프로세스 그룹/상태/명령을 남기도록 진단을 추가했다. **과거 실패의 원인을 확정하거나 flake·알려진 실패로 등록한 것은 아니다.** 최신 소스의 전체 시험 통과와 과거 원인 미확정을 구분한다.

## 운영 수용의 한계

- 기존 Discord의 실제 Bot 인증·설정 채널 조회와 신원 일치 확인, 공존 회귀는 이전 기록에 있다. 실제 Gateway READY·MESSAGE_CREATE, 메시지 송수신·결과 통지를 확인한 것으로 확대하지 않는다.
- 보호 설정 설치·서명된 사이트 배포·ARM64 payload·실제 장치 동작·관제 PC 마이크/STT/TTS 품질·현장 수용은 수행하지 않았다. 모델 평가가 이 증거들을 대신하지 않는다.
- 실행 연결은 기본 OFF다. 명시적인 운영자 좌표 요청만 기존 Task owner로 넘기며 모델 응답은 실행 권한을 갖지 않는다. UNKNOWN을 자동 재전송하지 않는다.

설치·rollback·실행 접수 절차는 [운영 안내](../../../operations/fleet/docs/operator-assistant.md), 후보 모델·라이선스와 실측 항목은 [모델 조사](../../../operations/fleet/docs/operator-models.md)를 따른다. 모듈의 장치/현장 gate는 올리지 않았다.
