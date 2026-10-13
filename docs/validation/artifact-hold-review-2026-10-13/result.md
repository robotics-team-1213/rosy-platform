# P1의 15개 HOLD 항목 재확인·처리

**날짜:** 2026-10-13 · **시작 기준:** commit `33d76482f` · **브랜치:** `docs/artifact-hold-review`.

사용자가 지정한 범위는 [P1에서 보류한 15곳](../folder-artifacts-p1-2026-10-13/result.md)이다. 전체를 다시 조사하고 확인된 비활성 cache/temp 파일을 X:로 이관했다. 보호된 협업 상태·자격 자료·참조되는 overlay는 유지했다. S1 구조 이동은 실행하지 않았다.

## 처리 결과

**1,847파일/42,508,179바이트(40.54 MiB)**를 X:에 보존한 뒤 같은 source bytes를 확인하여 원본 파일을 제거했다. 모든 destination hash·크기, source 부재를 읽어 확인했다. 구성은 orphan Python bytecode 1,715개, pytest/Ruff cache 76개, 시험 임시 자료 56개다. Git에는 원문이 아니라 이 기록과 계획 상태만 넣는다.

| 기존 HOLD 경로 | 처리 | 남은 파일 | 판정 |
|---|---|---:|---|
| `src` | pyc 1,413개와 nested pytest cache 55개 이관 | 31 | 협업 state·lock·미확정 기록 보존 |
| `apps` | orphan pyc 2개 이관 | 0 | 캐시만 있던 경로 정리 |
| `modules` | orphan pyc 20개 이관 | 0 | 캐시만 있던 경로 정리 |
| `firmware` | orphan pyc 3개 이관 | 0 | 캐시만 있던 경로 정리 |
| `signal` | orphan pyc 3개 이관 | 0 | 캐시만 있던 경로 정리 |
| `middleware/core/api_web` | orphan pyc 116개 이관 | 2 | 협업 state 보존 |
| `middleware/apps/device` | orphan pyc 158개 이관 | 0 | 캐시만 있던 경로 정리 |
| `.pytest-tmp-control` | 시험 생성물·inactive lock 56개 이관 | 0 | 임시 자료 보존 후 원본 정리 |
| `.pytest_cache` | pytest cache 6개 이관 | 0 | cache 보존 후 원본 정리 |
| `.ruff_cache` | tool cache 15개 이관 | 0 | cache 보존 후 원본 정리 |
| 우산 `pidA` | producer 이력/PID 확인 | 1 | PROTECTED_UNRESOLVED |
| 우산 `wsA.json` | schema·field type 및 이력 확인 | 1 | PROTECTED_UNRESOLVED |
| `build` | 생성/설치 소비 경로·reparse 조사 | 1,606 | PRESERVE_REFERENCED_OVERLAY |
| `install` | `env.sh`·CI의 setup 소비 확인 | 1,158 | PRESERVE_REFERENCED_OVERLAY |
| `log` | build/overlay 증거·reparse 조사 | 461 | PRESERVE_REFERENCED_OVERLAY |

source 경로는 제품 저장소 기준이며 `pidA/wsA.json`만 우산 기준이다. **8곳 정리, 2곳 부분 정리, 5곳 유지**다. 유지한 7개 경로를 전부 제거했다거나 전체 workspace가 깨끗하다고 집계하지 않는다. 파일 수는 reparse target을 제외한 확인 시점의 값이다.

## 추가 확인 근거

### 실행 소스가 없는 bytecode

1,715개는 `__pycache__/*.cpython-*.pyc`에만 있고 대응 `.py`가 없었다. header 형식, Git 비추적 상태와 전체 hash/size/mtime 안정성을 확인했다. 자신의 X: 임시 파일에서 `.py`를 compile한 뒤 원본을 제거하고, 표준 `PathFinder.find_spec`가 orphan `__pycache__`를 일반 import 대상으로 찾지 못하는 것을 assert로 확인했다. 대상 bytecode를 실행하거나 역직렬화하지 않았다. 명시적인 sourceless loader까지 불가능하다는 주장도 아니다.

### cache/temp의 비활성 확인

Windows process에서 native pytest/Ruff producer가 없음을 이관 전과 원본 제거 전에 확인했다. source 경로의 tracked 파일·reparse ancestry를 제외하고 전체 파일의 exclusive-read open 가능 여부를 확인했다. pytest cache의 CACHEDIR marker와 자료 위치를 확인했으며 lock 파일은 PID로 추정하지 않고 실제 open 가능한 상태와 생산 프로세스 부재로 검사했다.

실행 중인 Docker 컨테이너 30개의 mount를 읽었고 검토 대상 F: 경로의 bind는 없었다. 실행 중인 WSL 배포판은 docker-desktop뿐이었다. 컨테이너·서비스 종료와 Docker/WSL 내부 데이터 조작은 하지 않았다. 이 검사는 모든 프로세스의 내부 cwd·메모리 참조나 미래 실행을 증명하는 검사가 아니다.

모든 파일을 먼저 복사하고 destination 전체 hash/크기를 확인한 뒤, 원본 hash를 다시 확인하며 정확한 파일 경로만 제거했다. 비어 있는 디렉터리만 정리했고 재귀 delete는 쓰지 않았다. 실패 시 검증된 사본과 나머지 원본을 보존하도록 했다.

### 유지가 필요한 항목

- **협업 상태:** `src/.omc/state/sessions`의 세 producer ID에 해당하는 Claude transcript를 찾았다. 마지막 record가 queue/cost 상태이며 session 폐기 계약은 확인되지 않았다. transcript 본문과 tool 입력은 공개 기록에 복사하지 않고 metadata만 X:에 남겼다. 다른 세션의 cooldown/throttle/error 상태와 남은 lock/기록은 건드리지 않았다.
- **`pidA/wsA.json`:** 기록 PID는 현재 없지만 생성을 설명하는 실행 명령을 찾지 못했다. 과거 Codex 이력에서는 파일 목록만 확인된다. `wsA.json`은 자격으로 보이는 non-null 문자열을 포함해 token 값을 출력·문서화·사용·임시 export하지 않았다. 두 파일의 producer/보존 계약을 확인하기 전에는 제거하지 않는다.
- **`build/install/log`:** 단순한 중복 소스가 아니다. `env.sh`가 `install/setup.bash`를 읽고 CI가 build/install/log를 생성·소비한다. Linux reparse와 상대 경로/생성물의 일관성이 필요한 영역이므로 Windows에서 비운 뒤 소스 정리 완료로 선언하지 않는다. overlay 퇴역 또는 X: 이전은 소비 경로·link 보존·재빌드/환경 검증을 포함한 별도 작업이다.

## 증거·복구·검증 경계

자료 세션: `X:\DevTemp\projects\rosy-platform\2026-10-13--154416--artifact-hold-review--8df57c`.

- `evidence/hold-current-inventory.json`, `hold-state-metadata.json`: 15곳의 재관측과 보호한 metadata 구조. credential 원문은 없음.
- `evidence/collaboration-owner-trace.json`, `cache-producer-processes.json`: 확인한 actor 이력과 process 관측.
- `evidence/orphan-bytecode-candidates.json`, `cache-transfer-manifest.json`: source/role/누락 원본/destination/size/mtime/hash 목록.
- `evidence/cache-transfer-actions.jsonl`, `hold-review-readback.json`: 실제 파일별 처리와 최종 8/2/5 판정.
- `export/orphan-bytecode`, `export/inactive-caches`: 이관 원문. 현재 소스나 시험의 성공 증거가 아님.

복구는 manifest의 source 경계와 새 파일 존재 여부를 확인하고 destination hash를 검증한 뒤 정확한 원래 위치에 복사한다. 새로 생성된 자료를 덮어쓰지 않는다. 향후 Python cache 출력은 [X: 세션 안내](../../reference/analysis-artifact-locations.md)를 따른다. 노트북 pytest는 실행하지 않는다.

처리 기록의 committed HEAD는 원격 문서/구조 gate와 known-failure 비교 후 local main에 착지하며 최종 결과는 이 세션의 landing 로그와 Git readback으로 확인한다. host pytest는 파일 이관 readback·실물 수용을 대신하지 않는다. push·배포·장치 명령·S1~S10/P2/P3 실행은 이번 범위 밖이다.
