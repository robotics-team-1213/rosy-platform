# P1 생성물 분류·Graphify 결과 이관

**날짜:** 2026-10-13 · **분류 시작 기준:** commit `5d70a4fc1` · **브랜치:** `docs/folder-artifacts-p1`.

근거는 [실행 계획](../../plans/2026-10-13-folder-responsibility-cleanup.md)의 P1이다. 범위는 생성물 19곳의 분류와 종료 확인 가능한 Graphify 결과 이관이다. 제품 소스 이동, worktree 제거, build/install 정리, 장치 작업은 하지 않았다.

## 결과

- Graphify 생성물 **4곳/418파일/34,837,896바이트(33.22 MiB)**를 X: 세션으로 이관했다.
- 파일마다 destination SHA-256·크기를 확인한 다음 같은 source bytes를 다시 검사해 원본을 제거했다. 원본 418개와 비어 있는 4개 출력 root가 없고 destination bytes가 그대로임을 확인했다.
- `graphify god-nodes --top 1 --json`의 이관 전/후 결과가 동일했다. `.graphify_root`와 `.graphify_python` 등 기존 metadata bytes를 보존했다. 표시된 source root는 기존 CORE scope이며, 분류 시점의 main commit이 그래프를 생성한 revision이라는 증거는 없다.
- 나머지 **15곳은 HOLD**로 보존했다. 알려지지 않은 actor/session, 협업 상태, lock, 자격 필드, overlay를 단순 cache로 처리하지 않았다.
- 설치 Graphify의 `GRAPHIFY_OUT`을 세션 X: 절대 경로로 해석하는 것을 확인하고 [후속 출력 안내](../../reference/analysis-artifact-locations.md)를 추가했다. 전역 설정은 변경하지 않았다.

| 우산 기준 source | 파일 | 판정 | 근거/목적 |
|---|---:|---|---|
| `graphify-out` | 9 | TRANSFERRED | report/graph/manifest와 cache, source marker·도구 경로 |
| `rosy-platform/graphify-out` | 1 | TRANSFERRED | Graphify stat cache |
| `rosy-platform/middleware/graphify-out` | 1 | TRANSFERRED | Graphify stat cache |
| `rosy-platform/middleware/core/graphify-out` | 407 | TRANSFERRED | Graphify stat/AST cache |
| `rosy-platform/src` | 1,499 | HOLD | 1,413 pyc 외 협업 state·lock·cache도 혼재 |
| `rosy-platform/apps` | 2 | HOLD | pyc; actor/실행 참조 미확정 |
| `rosy-platform/modules` | 20 | HOLD | pyc; actor/실행 참조 미확정 |
| `rosy-platform/firmware` | 3 | HOLD | pyc; actor/실행 참조 미확정 |
| `rosy-platform/signal` | 3 | HOLD | pyc; actor/실행 참조 미확정 |
| `rosy-platform/middleware/core/api_web` | 118 | HOLD | pyc와 협업 state 혼재 |
| `rosy-platform/middleware/apps/device` | 158 | HOLD | pyc; actor/실행 참조 미확정 |
| `rosy-platform/.pytest-tmp-control` | 56 | HOLD | 시험 자료·lock; 생산 세션 미확정 |
| `rosy-platform/.pytest_cache` | 6 | HOLD | 공유 시험 상태; 생산 세션 미확정 |
| `rosy-platform/.ruff_cache` | 15 | HOLD | 도구 cache; 생산 세션 미확정 |
| `pidA` | 1 | HOLD | 기록 PID는 현재 없음. 이것만으로 생산/종료 의도를 확정하지 않음 |
| `wsA.json` | 1 | HOLD | 자격 필드 포함. 값은 출력/문서/분류 manifest에 복사하지 않음 |
| `rosy-platform/build` | 1,606 | HOLD/별도 범위 | 생성 환경. reparse 91개 제외한 파일 수 |
| `rosy-platform/install` | 1,158 | HOLD/별도 범위 | 설치 overlay. reparse 342개 제외한 파일 수 |
| `rosy-platform/log` | 461 | HOLD/별도 범위 | 실행/빌드 로그. reparse 3개 제외한 파일 수 |

파일 수는 분류 시각의 관측값이다. reparse target을 따라가지 않았다. 기존 1,803개 legacy 파일을 삭제 목록으로 사용하지 않았다.

## 이관 전 조건과 검증

Graphify producer는 설치 CLI 구현, marker와 cache schema로 식별했다. tracked runtime/tool/deploy/config 입력에 Graphify 결과 경로를 소비하는 참조가 없었고, 확인한 사용자/작업 설정 파일에도 직접 경로 참조가 없었다. 날짜만으로 종료를 추정하지 않았다.

Windows process 목록에서 Graphify CLI/관련 Python producer와 후보 경로를 명시한 Python/Node 작업이 없었다. 네 source root/하위 항목에 reparse가 없고 제품 추적 파일이 없음을 확인했다. 전체 418파일의 inventory 이후 hash/크기/mtime 안정성, exclusive-read open 가능 여부를 확인한 뒤 복사했다. destination 전체 hash/크기 확인 이후 producer/file-set를 재검사하고 파일 단위로 원본을 제거했다. 비어 있는 디렉터리만 별도로 제거했으며 재귀 delete는 쓰지 않았다.

이 process 검사는 모든 Windows 프로세스의 내부 cwd/메모리 참조를 증명하는 검사가 아니다. Graphify 결과는 실행 소스가 아니고 원문을 보존한 이관이다. 다른 cache/state는 이 근거를 확대 적용하지 않고 HOLD로 남겼다.

## 위치·복구·남은 항목

자료 세션: `X:\DevTemp\projects\rosy-platform\2026-10-13--140927--folder-artifacts-p1--f5e4ef`.

- `evidence/artifact-inventory.json`: source/owner/purpose/active/references/decision/destination/rollback 및 초기 수량.
- `evidence/graphify-files-before.json`: 418파일별 source/destination, 크기/mtime/SHA-256.
- `evidence/process-observations.json`, `reference-check-scope.json`: producer·기록 PID 관측과 설정 검사 범위. credential 값은 포함하지 않음.
- `evidence/graphify-transfer-actions.jsonl`: 파일별 실제 이관/원본 제거 기록.
- `evidence/artifact-disposition.json`, `logs/transfer-readback.txt`: 최종 hash·source 부재·HOLD 보존·CLI 읽기 동등성.
- `export/graphify/{umbrella,repository,middleware,core}/graphify-out`: 이관 bytes. 당시 index scope를 유지한 보관 결과이며 새 main 분석 결과가 아님.

복구는 위 manifest의 source 경계와 현재 존재 여부를 다시 확인하고 destination hash를 검증한 뒤 원래 위치에 복사한다. 새 파일/생성물을 덮어쓰지 않는다. copy/readback 실패에는 나머지 원본을 보존하고 기록된 부분 이관만 복구한다.

**남은 작업:** 15 HOLD 경로의 actor/사용 참조 조사, D-738 S1~S10, proof P2, worktree P3. 이번 기록의 commit/원격 문서 gate/local main 착지 결과는 Git과 같은 X: 세션 landing 로그로 확인한다. pytest와 lint는 이관 bytes readback을 대신하지 않는다. push·배포·ROS graph·장치/현장 인수는 이번 결과에 포함하지 않는다.
