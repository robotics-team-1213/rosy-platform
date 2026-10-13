## D-437 공개 저장소의 빌드는 GitHub Actions hosted runner에서 하고, 서명만 로컬 오프라인 키로 한다

**Status:** Accepted (2026-10-03, 사용자 결정). 빌드 위치·서명 경계·배포 경로의 결정이다. 사이트 후보 workflow(`build-site-candidate.yml`)의 첫 실제 실행은 사용자가 승인하는 push 뒤에만 가능하므로 아직 검증되지 않았다. 사이트 서명 키는 D-301대로 아직 준비되지 않았다.

**Connects:** D-145, D-225, D-301, D-412, D-434.

### Context

- 사이트 후보(`deploy/site/build_candidate.py`)를 Windows Docker Desktop 호스트에서 빌드하는 일이 너무 느렸다.
  - WSL2의 `docker save`가 수 GB짜리 `images.tar`를 Windows 디스크에 쓰는 데 오래 걸렸다.
  - Docker Scout의 SBOM 색인이 이미지마다 10분을 넘었다.
  - 결과물 수 GB를 Wi-Fi로 사이트 호스트에 옮겨야 했다.
- 저장소는 공개다. GitHub Actions hosted runner는 공개 저장소에서 무료이고, 디스크·네트워크가 빠르며, 매번 깨끗한 환경에서 시작한다.
- 로봇 payload·이미지 빌드는 이미 GitHub arm64 runner에서 unsigned 결과만 만든다(`build-arm64-payload.yml`, `build-native-payload.yml`, `build-pinky-image.yml`; D-145, D-225). 서명은 PC의 오프라인 키로 하고, 배포는 GitHub Release로 한다(D-412).
- D-301은 사이트 후보 `release.json`을 오프라인 Ed25519 키로 서명하고, 사이트 호스트가 따로 설치한 검증기와 공개 키로 확인하게 한다. 지금 서명기는 서명 전에 manifest가 적은 모든 파일을 로컬에서 검사한다. 그래서 서명하려면 수 GB `images.tar`를 서명 스테이션까지 내려받아야 한다.
- 학습·NCNN 변환·intake·store는 GPU와 비공개 데이터·모델이 필요해 모델 PC에 있다(D-434).

### Decision

1. **저장소 산출물의 빌드는 GitHub hosted runner에서 한다.**
   - 사이트 후보(amd64)는 `ubuntu-24.04`에서, 로봇 payload·이미지(arm64)는 기존처럼 `ubuntu-24.04-arm`에서, CI는 기존 `ci.yml`에서 한다.
   - workflow는 수동 실행(`workflow_dispatch`)이다. main push만으로는 후보나 릴리스가 생기지 않는다.
2. **runner 결과물은 서명되지 않는다.**
   - 사이트 키(D-301)와 Pinky 릴리스 키는 운영자의 서명 스테이션에만 둔다. GitHub secret으로 올리지 않는다.
   - workflow는 `GITHUB_TOKEN` 말고 어떤 secret도 쓰지 않는다. 빌드 job은 저장소 읽기 권한만 갖는다. 출처 증명은 빌드 도구를 돌리지 않는 별도의 작은 job이 하고, 그 job만 `id-token: write`·`attestations: write`를 갖는다. Release를 만드는 job만 `contents: write`를 갖는다.
   - 사이트 후보 workflow의 action은 모두 전체 커밋 SHA로 고정하고 태그를 주석으로 단다. 이동하는 태그가 바뀌어도 실행 코드가 바뀌지 않는다.
3. **사이트 후보의 배포 경로는 공개 저장소의 GitHub Release(prerelease)다.**
   - 태그는 `site-<짧은 커밋>`이다. 긴 빌드 전에 짧은 사전 job이 같은 태그의 릴리스가 이미 있는지 보고, 있으면 바로 실패한다. 후보 묶음은 tar로 묶어 2 GiB 아래 조각(`.partNN`)으로 나누고 `SHA256SUMS`를 붙인다. GitHub Release 자산은 파일당 2 GiB 한도가 있다.
   - `release.json`은 따로 자산으로도 올린다. 서명 스테이션은 이 파일만 내려받는다.
   - 릴리스 설명은 "`release.json.sig`가 붙기 전에는 UNSIGNED"라고 적는다.
   - 사이트 호스트는 자산을 받아 조각을 잇고, `SHA256SUMS`를 확인하고, 풀고, `release.json.sig`를 넣은 뒤 `docker load` 전에 서명과 파일 해시를 검증한다.
   - 풀기 전에 tar 구성원을 모두 검사한다. 일반 파일과 디렉터리만, `<커밋>/` 아래만 허용한다(심볼릭 링크·하드 링크·장치·FIFO·절대 경로·`..` 거부). 그 뒤 Python tarfile의 `data` 필터로 푼다(호스트 python3 3.12 이상).
   - D-301의 나머지 규칙은 그대로다. 검증기와 공개 키는 후보와 다른 경로로 호스트에 먼저 설치하고, 후보 안의 검증기로 그 후보를 인증하지 않는다.
4. **manifest만 서명한다.**
   - 서명 스테이션은 `sign_candidate.py --manifest-only`로 `release.json` 바이트만 서명한다. 파일 존재 검사는 하지 않는다.
   - 서명이 증명하는 내용은 "커밋 `<sha>`에서 CI 실행이 만든 이 manifest를 운영자가 승인했다"이다.
   - Release 자산은 저장소 쓰기 권한이 있으면 바꿀 수 있다. 그래서 서명 전에 `release.json`을 CI 실행에 묶는다. 두 가지 모두 필수다.
     - **기대 해시.** 빌드 job은 `release.json`의 SHA-256을 로그(notice)와 job summary에 쓴다. 실행 기록은 자산 쓰기 권한으로 고칠 수 없다. 운영자는 실행 페이지의 job summary 표(또는 `gh attestation verify --format json`이 보고하는 `release.json` subject digest)에서 이 값을 옮겨 `--expected-manifest-sha256`으로 넘긴다. 아무 로그 줄에서 옮기지 않는다. 빌드 도구(Docker·syft·빌더)를 돌리는 step은 `::stop-commands::<임의 토큰>`으로 workflow 명령 해석을 멈춘 채 돌고, 해시 표는 명령 해석을 다시 켠 뒤에만 쓴다. 그래서 도구 출력이 가짜 notice나 summary를 만들 수 없다. 서명기는 정확한 바이트의 SHA-256이 이 값과 다르면 거부한다.
     - **빌드 출처(provenance).** 빌드가 끝나면 별도의 `attest-provenance` job이 `release.json`과 `SHA256SUMS`만 받아 `actions/attest-build-provenance`로 출처 증명을 남긴다. 이 job의 권한은 `contents: read`, `id-token: write`, `attestations: write`뿐이다. 빌드 job에는 OIDC·증명 권한이 없다. Release는 증명이 끝난 뒤에만 만들어진다. 운영자는 서명 전에 `gh attestation verify release.json --repo <owner>/<repo> --signer-workflow <owner>/<repo>/.github/workflows/build-site-candidate.yml --source-ref refs/heads/main`을 통과시킨다. 이 단계는 서명기 플래그가 아니라 문서화된 운영자 절차다.
   - 출처 증명은 dispatch한 ref(main)를 적는다. 그래서 workflow는 빌드할 커밋이 dispatch한 커밋의 조상일 때만 빌드한다. main에서 dispatch하면 main 이력에 있는 커밋만 빌드된다.
   - 기대 커밋도 그대로 받는다. 서명기는 manifest의 `source_commit`이 40자리 16진수이고 기대 커밋과 같을 때만 서명한다.
   - 무결성은 그대로 지켜진다. 사이트 호스트의 `verify_candidate.py`가 서명된 manifest를 기준으로 배포 파일·SBOM·`images.tar` 해시를 모두 다시 확인한 뒤에 `docker load`를 허락한다.
5. **로컬에 남는 것.**
   - 학습·NCNN 변환·intake·store(모델 PC, D-434).
   - 서명 키 전부(사이트 키, Pinky 릴리스 키).
   - 사이트 설정·비밀(사이트 호스트의 `/etc/rosy`).
6. **이미지에는 공개 저장소 코드만 들어간다.** 설정·비밀은 이미지에 굽지 않는다.
   - Fleet·Vision 이미지는 `.dockerignore` 허용 목록에 있는 추적 파일만 복사한다. 프록시 이미지는 파일을 복사하지 않는다.
   - 빌더는 git이 무시하는 파일(예: `secrets/` 아래 실제 토큰, `.env`, `*.local.yaml`)이 아래 경로에 있으면 빌드를 거부한다.
     - `deploy/site/`. 프록시 이미지의 빌드 컨텍스트라서 그런 파일이 Docker 데몬으로 보내진다.
     - Fleet·Vision Dockerfile이 COPY·ADD로 복사하는 모든 원본 경로(예: `src/site/fleet`, `src/site/vision/rosy_vision`, `src/hmi/web_common`, 지도 파일). 빌더가 Dockerfile에서 직접 읽으므로 COPY가 늘면 검사도 따라간다. 빌더가 해석하지 못하는 COPY·ADD 형식(JSON 배열, heredoc, `--chown`·`--chmod` 외의 플래그)은 건너뛰지 않고 빌드를 거부한다. 디렉터리째 복사하므로 무시된 파일이 이미지에 들어갈 수 있다.
     - 파이썬 캐시(`__pycache__`, `.pytest_cache`)와 `.egg-info`는 예외다.
   - 시험이 이 규칙을 강제한다. Dockerfile의 COPY·ADD 원본에는 `secrets`나 `.env`가 없어야 하고, 위 경로에 무시된 파일이 있으면 빌더가 거부해야 한다.
7. **SBOM은 runner에서 syft(anchore)로 만든다.**
   - Docker Scout는 runner에서 Docker Hub 로그인이 필요하다. 그러면 secret이 하나 늘어난다.
   - `build_candidate.py --sbom-tool syft`는 SPDX JSON을 같은 파일 이름(`sbom/<service>.spdx`)으로 쓴다. 그래서 manifest 형식과 검증기는 바뀌지 않는다.
   - syft는 버전을 고정하고, 내려받은 파일의 SHA-256을 확인한 뒤에 쓴다.
   - 로컬 빌드의 기본값은 지금처럼 `scout`이다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 로컬 Windows(Docker Desktop)에서 빌드 | WSL2 `docker save`와 Scout 색인이 느리고, 결과를 Wi-Fi로 옮겨야 한다. 기각(로컬 수동 경로로는 남긴다) |
| 사이트 호스트에서 빌드 | 관제 PC는 8스레드·14 GB RAM이고 사이트 스택만 맡는다(D-434). 빌드 도구와 소스 체크아웃이 운영 호스트에 생기고, 빌드 부하가 관제를 흔든다. 기각 |
| GitHub hosted runner에서 빌드, 서명은 로컬 | 공개 저장소라 무료이고 빠르며, 매번 깨끗하다. 키가 GitHub에 가지 않는다. 채택 |
| runner에서 서명(키를 GitHub secret으로) | 저장소 쓰기 권한이나 workflow 변경 한 번이 발행 권한이 된다. D-145·D-301·D-412와 충돌. 기각 |

### Consequences

- 서명 스테이션은 수 GB 대신 몇 KB짜리 `release.json`만 받는다. 서명기는 묶음 내용을 보지 않으므로, 내용 확인은 사이트 호스트의 검증으로 넘어간다. 운영자는 서명하기 전에 커밋과 CI 실행이 맞는지 확인해야 한다.
- 공개 Release 자산은 누구나 받을 수 있다. 이미지에는 공개 코드만 있으므로 새로 드러나는 것은 없다. 설정·비밀은 호스트에만 있다.
- 사이트 호스트는 GitHub에 닿아야 한다. 닿지 않으면 같은 자산을 다른 기계에서 받아 옮긴다. 검증 절차는 같다.
- GitHub 쓰기 권한만 가진 사람도 Release 자산(`release.json`, 조각, `SHA256SUMS`, 이미 붙은 `release.json.sig`)을 바꾸거나 지울 수 있다. 바뀐 `release.json`을 운영자가 서명하지 않도록 기대 해시와 출처 증명 확인을 서명 전에 요구한다. 서명 뒤에 자산을 바꾸면 호스트 검증기가 서명이나 파일 해시 단계에서 거부한다. 쓰기 권한으로는 서명을 지우거나 후보를 지워 배포를 막을 수는 있지만, 호스트가 받아들이는 후보를 만들 수는 없다.
- 로봇 자동 갱신(D-412, `rosy_auto_update.py`)은 `releases?per_page=20` 한 쪽에서 prerelease까지 포함해 `payload-*`를 찾는다. `site-*` prerelease가 쌓이면 최신 payload가 그 쪽 밖으로 밀릴 수 있다. 그래서 release job은 새 prerelease를 만든 뒤 옛 `site-*` 릴리스와 태그를 지우고 최신 3개만 남긴다. 이름이 `^site-[0-9a-f]{12}$`와 정확히 맞는 것만 지우고, 다른 릴리스는 건드리지 않는다.
- 출처 증명의 source digest는 빌드한 커밋이 아니라 dispatch한 ref의 끝 커밋이다. 빌드한 커밋은 manifest의 `source_commit`과 서명기의 `--expected-commit`으로 묶이고, workflow는 그 커밋이 dispatch 끝 커밋의 조상일 때만 빌드한다.
- 이미지 ID는 두 형태다(2026-10-04 현장 실패로 확인). `release.json`의 `image_id`는 runner(classic image store)가 기록한 config digest다. containerd image store를 쓰는 호스트는 `docker image load` 뒤 `{{.Id}}`로 OCI image manifest digest를 돌려준다. 전체 검증기는 서명된 해시와 맞은 `images.tar` 안에서 각 이미지의 config blob과 manifest blob을 읽어 바이트 해시를 다시 계산하고, manifest의 `config.digest`가 서명된 `image_id`와 같을 때만 그 manifest digest도 받아들인다. 결과 summary의 `id_form`이 `config`인지 `oci-manifest`인지 남긴다. `index.json`이 없는 옛 archive는 config 형태만 받는다. manifest 형식과 이미 서명된 후보는 바뀌지 않는다.
- 후속 작업: 로봇 쪽 조회가 `payload-*`를 찾을 때까지 쪽을 넘기거나 prerelease를 거르도록 고친다. 이 브랜치에서는 로봇 코드를 바꾸지 않았다. 그 전까지는 위 정리가 유일한 방어다. 사이트 후보 외의 다른 릴리스가 20개를 넘게 쌓여도 같은 문제가 생긴다.

### Validation

- 호스트 시험: `--sbom-tool syft` 호출과 결과 파일, 이미지 원본 경로의 무시된 비밀 파일 거부, manifest-only 서명(기대 해시 불일치·커밋 형식·기대 커밋 불일치 거부, 덮어쓰기 거부, 서명 뒤 호스트 검증기 통과), fetch 스크립트(서명 없음·예상 밖 자산·변조 조각·심볼릭/하드 링크·FIFO·절대 경로·`..` 거부), workflow 계약(수동 실행, secret 없음, 릴리스 존재 사전 검사, 빌드 job 저장소 읽기 전용, 해시 summary와 출처 증명, release job만 쓰기, 옛 `site-*` 정리, action SHA 고정, syft 버전·해시 고정, prerelease, 조각 나누기).
- 아직 안 된 것: workflow의 첫 실제 실행. 사용자가 승인한 push 뒤 `gh workflow run build-site-candidate.yml`로 확인한다. 사이트 키 준비와 호스트 수용은 D-301대로 별도 gate다.
- 이 ADR은 로봇 이동이나 정책 실행을 허락하지 않는다.

**Related:** [D-301](D-301-site-candidate-signatures.md), [D-412](D-412-robots-self-update-from-signed-github-releases-when-idle.md), [D-225](D-225-update-without-reflash-and-faster-card-writes.md), [D-434](D-434-model-pc-and-site-pc-roles.md).

### 2026-10-04 — 자동 빌드·자동 서명·자동 설치 (D-441)

- 결정 1의 "main push만으로는 후보나 릴리스가 생기지 않는다"를 D-441이 바꾼다. 후보 이미지·묶음에 들어가는 경로나 workflow를 건드린 main push가 후보를 만든다. push에서 같은 태그의 릴리스가 이미 있으면 사전 job이 빌드 없이 성공한다. dispatch는 그대로 바로 실패한다. 새 push는 옛 push의 빌드 job만 취소하고, 릴리스 job은 취소하지 않는 한 그룹에서 줄을 선다.
- 결정 4의 운영자 절차(기대 해시 옮기기, `gh attestation verify`, 서명, 업로드)는 서명 PC의 `auto_sign_candidates.py`가 같은 순서로 한다. 기대 해시는 출처 증명이 보고하는 `release.json` subject digest이고, 받은 바이트와 같아야 한다. 커밋이 main에 있고 태그가 `site-<커밋 12자리>`일 때만 기존 `sign_manifest_only`로 서명한다. 키는 그 PC에만 있다.
- 사이트 호스트는 `rosy_site_autoupdate.py`(검증기 옆에 설치)로 서명된 최신 후보를 받아 같은 검증(서명 → 해시 → load → 이미지 ID)을 거친 뒤 전환하고, 건강 확인에 실패하면 되돌린다.

### Addendum (2026-10-10, D-553 addendum 3)

페이로드 빌드는 digest로 고정한 ARM64 빌더 이미지(`build-payload-builder.yml`, 같은 D-482 스냅샷 입력의 캐시) 안에서 돌고, 어느 브랜치에서든 dispatch할 수 있다. 서명은 여전히 운영 PC에서만 한다. 빌더 job만 `packages: write`를 job 토큰으로 갖는다. 근거와 조건은 [D-553](D-553-cd-speed-parallel-build-and-test-pcs.md) Addendum 3에 있다.
