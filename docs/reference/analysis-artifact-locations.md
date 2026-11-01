# 분석 생성물의 작업 위치

실험실 PC의 소스·Git worktree는 F:, 분석 결과·캐시·로그는 X: 세션에 둔다. 작업 등록/재개는 `X:\DevTemp\_management\workspace.ps1`의 `New`/`Resume`를 사용한다. 원칙은 `F:\AGENTS.md`, 실제 처리 기록은 [P1 결과](../validation/folder-artifacts-p1-2026-10-13/result.md)다. 다른 개발 PC의 Graphify 출력은 아래 공용 도구가 사용자 캐시 경로에 둔다. 드라이브 문자를 복제하거나 전역 환경 변수를 바꾸지 않는다.

## Graphify와 Python 캐시

### 팀 공용 파이프라인

Python 3.10+와 Git이 있는 개발 PC에서 실행한다. 로봇 런타임 의존성이나 배포 항목은 아니다. Graphify 0.9.91로 확인했으며 다른 버전은 다시 검증한다.

```powershell
python -m pip install --user uv
python -m uv tool install graphifyy==0.9.91
python -m uv tool update-shell
# 새 셸에서 Codex용 스킬을 등록한다.
graphify install --platform codex

# 저장소 루트 또는 작업 worktree에서 실행한다.
python tools/graphify_pipeline.py build
# 작은 범위의 실행 확인:
python tools/graphify_pipeline.py build --scope middleware/core/events
# 플랫폼 전체 코드와 명시적 Markdown 링크:
python tools/graphify_pipeline.py build --scope . --documents
# 별도 Harbor 체크아웃(실제 Git 루트 경로를 넣는다):
python tools/graphify_pipeline.py build --repository "<harbor-checkout>" --scope . --documents
# 출력된 Run 경로를 명시한다. 경로에 공백이 있으면 따옴표로 감싼다.
python tools/graphify_pipeline.py query --run "<run-path>" "CommandManager"
```

`build`의 기본 범위는 기존과 같이 `middleware/core`다. `--scope .`은 전체 저장소, `--repository`는 별도 Git 체크아웃을 선택한다. scope는 선택한 저장소 안의 디렉터리여야 하며 Git 메타데이터·작업 워크트리 폴더를 직접 선택할 수 없다. 코드와 테스트를 함께 색인하며 `package.xml` 등 미지원 파일은 extract 로그에 남는다. Harbor 앱 코드를 플랫폼에 복사하거나 런타임 의존성을 추가하지 않는다.

선택 범위에 초기화된 submodule·중첩 Git 저장소·디렉터리 링크가 Git 목록의 디렉터리 항목으로 나타나면 중단한다. 바깥 저장소의 revision·파일 해시만으로 그 안의 변경을 검증할 수 없기 때문이다. 해당 체크아웃을 `--repository`로 별도 분석한다.

`--documents`는 Graphify 0.9.91이 이번 실행에서 생성한 `cache/stat-index.json`을 사용한다. ignore·민감 파일 필터를 통과한 파일만 목록 노드로 추가하고 Markdown의 명시적인 로컬 링크를 연결한다. 인라인·참조형 링크와 URL 인코딩된 파일명을 지원하며, 코드 블록·인라인 코드·외부 URL·범위 밖 경로는 제외한다. 없는 대상과 미지원·필터 제외 대상은 `coverage.json`의 `unresolved_links`에 남긴다. 중첩 괄호 같은 복잡한 Markdown 구문, 문서·ADR의 의미 관계, 이미지·영상 내용은 분석하지 않는다. corpus index가 없거나 깨졌거나 범위를 벗어나면 문서 분석 성공으로 처리하지 않는다.

출력 부모는 `--output` → `DEV_SESSION/scratch/graphify` → Windows의 `%LOCALAPPDATA%/ROSY/analysis/graphify`, 그 외 운영체제의 `$XDG_CACHE_HOME/ROSY/analysis/graphify` 또는 `~/.cache/ROSY/analysis/graphify` 순서로 고른다. 실제 결과는 그 아래 고유한 실행 폴더에 둔다. 분석 대상과 도구 저장소 양쪽의 저장소·worktree 내부 출력은 거절한다.

1. 범위의 Git revision과 추적·미추적 비무시 파일의 SHA-256을 기록한다. 상위 `.gitignore`·`.graphifyignore`, Git의 저장소·사용자 제외 규칙도 기록해 분석 대상 변경을 감지한다.
2. `--code-only --no-cluster`로 코드 관계를 추출한다. 요청한 경우 문서 링크를 합친 뒤 한 번만 클러스터링한다. 출력·Python 캐시 설정은 자식 프로세스에만 적용한다.
3. 보고서 생성에 `--no-label`을 명시해 API·자동 LLM 백엔드 탐색 없이 커뮤니티와 보고서를 생성한다. `Community N` 표기는 이 선택의 결과다. 1,500개가 넘는 노드는 HTML에서 커뮤니티로 요약하고 JSON에는 전체를 보존한다.
4. 빈 그래프·끊어진 참조는 실패 처리하고 자기참조 개수는 `health.json`에 남긴다. 주요 노드 조회도 실행한다.
5. 소스 revision과 파일 해시가 그대로인지 확인한 뒤에만 `provenance.json`을 `verified`로 기록한다. 실패 로그와 `failed` 상태는 보존한다.
6. 조회할 때도 소스·그래프 해시를 확인한다. 변경됐으면 새로 생성한다. `--run` 없이 다른 세션의 그래프를 추정하지 않는다.

생성물은 `graphify-out/{graph.json,graph.html,GRAPH_REPORT.md}`, 실행 근거는 `provenance.json`, `health.json`, `coverage.json`, 단계별 `*.log`다. Git에 넣지 않는다. `coverage.json`은 문서 링크 범위와 추출기의 `warning:` 행을 보존한다. 선택 파서가 없거나 일부 구문을 해석하지 못했다는 경고를 `verified`로 덮지 않는다. 명령 성공은 종료 코드로 판단하므로 PowerShell에서 stderr 경고가 작업을 잘못 중단하지 않는다.

`verified`는 생성물 무결성과 CLI 실행 확인을 뜻한다. 검색 정확도·완전성이나 로봇 동작 검증을 뜻하지 않는다. 그래프의 추출 관계와 추론 관계를 구분하고 답의 원본 위치를 확인한다. 현재 그래프는 무방향일 수 있어 `affected` 결과로 실제 의존 방향이나 테스트 생략을 결정하지 않는다. 테스트 선택은 기존 harness를 따른다.

조회는 코드 심볼 이름으로 시작한다. 한국어 질문을 입력한다고 동의어나 번역이 자동 처리되지 않는다. 출력이 토큰 예산으로 잘리면 질문을 좁히거나 `--budget`을 늘린다.

### 채택 판단과 후속 검증

상태는 **Trial**이다. 전체 저장소·Harbor의 구조 분석을 실행할 수 있어도 검색 품질의 채택 판단을 뜻하지 않는다. [최초 실행 기록](../validation/graphify-core-trial-2026-10-16/result.md)의 CLI 확인과 검색 품질 비교를 구분한다. 다음 비교에서는 같은 소스 snapshot에 대해 실제 질문 5~10개의 정답 파일·심볼을 먼저 고정한다. 기존 `rg`+원문 확인과 그래프 조회 각각의 누락·오탐, 원문 확인까지 걸린 시간, 생성·갱신 시간을 기록한다. 품질 저하 없이 반복 탐색 비용이 줄어든다는 증거를 얻은 뒤 탐색 기본 도구로 채택할지 판단한다. 결과가 부족하면 기존 검색을 유지한다.

### 기존 수동 실행과 이관 기록

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
