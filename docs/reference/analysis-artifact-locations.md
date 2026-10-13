# 분석 생성물의 작업 위치

소스·Git worktree는 F:, 분석 결과·캐시·로그는 X: 세션에 둔다. 작업 등록/재개는 `X:\DevTemp\_management\workspace.ps1`의 `New`/`Resume`를 사용한다. 원칙은 `F:\AGENTS.md`, 실제 처리 기록은 [P1 결과](../validation/folder-artifacts-p1-2026-10-13/result.md)다.

## Graphify와 Python 캐시

설치된 Graphify는 `GRAPHIFY_OUT`에 절대 경로를 지정할 수 있다. 값은 모듈 import 때 읽으므로 **프로세스를 시작하기 전에**, 해당 세션의 셸에서 설정한다. 사용자/시스템 전역 환경 변수는 바꾸지 않는다. Python 개발 도구의 새 bytecode 캐시도 같은 방식으로 세션 scratch에 둔다.

```powershell
# 먼저 같은 셸에서 workspace.ps1 New 또는 Resume를 실행한다.
if (-not $env:DEV_SESSION) { throw '작업 세션을 먼저 등록/재개하세요.' }
$sourceRoot = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { throw '실제 Git worktree에서 실행하세요.' }
$env:GRAPHIFY_OUT = Join-Path $env:DEV_SESSION 'scratch/graphify/core'
$env:PYTHONPYCACHEPREFIX = Join-Path $env:DEV_SESSION 'scratch/python-cache'

# 소스 범위를 명시한다. 출력 경로로 source root를 추정하지 않는다.
graphify extract (Join-Path $sourceRoot 'middleware/core') --code-only
graphify god-nodes --graph (Join-Path $env:GRAPHIFY_OUT 'graph.json') --top 5 --json
```

서로 다른 source scope는 `scratch/graphify/<scope>`로 구분한다. 보존 결과는 해당 세션 export/evidence에 위치와 hash를 기록한다. 다른 세션의 결과를 묵시적인 `graphify-out/graph.json`으로 선택하지 않는다. 기존 결과를 읽을 때는 `--graph <명시한 X: graph.json 경로>`를 쓴다.

위 설정은 현재 설치본의 `graphify.paths.out_path/default_graph_json`에서 X: 경로로 해석되는 것을 확인했다. P1에서는 새 전체 extract를 수행하지 않았으며, 기존 결과의 read command가 이관 전/후 같은 출력을 내는 것을 확인했다. 전체 재추출과 다른 버전/확장 기능의 검증을 대신하지 않는다.

## 옛 경로·시험 생성물

- pytest는 committed HEAD의 원격 runner로만 실행한다(D-584). 노트북에 새 pytest cache나 `.pytest-tmp-control`을 만들지 않는다. 반환 로그는 X: 세션에 둔다.
- `.omc` 협업 상태, lock, 자격 정보, build/install overlay는 이름이나 나이로 disposable cache를 판정하지 않는다. 생산자·사용 참조를 모르면 HOLD다.
- `build/install/log`의 경로·symlink는 활성 환경을 조사한 별도 작업에서 다룬다. Python cache 설정으로 기존 파일이 자동 이동되는 것은 아니다.
- 이관은 명시한 파일 목록의 source/destination 경계와 reparse 여부 확인 → 복사 → 전체 hash/크기 확인 → 같은 source bytes 확인 → 원본 파일 제거 → destination readback 순서다. 실패 시 남은 원본과 검증된 사본을 보존한다. 광범위 재귀 삭제나 서비스 종료로 상태를 맞추지 않는다.
