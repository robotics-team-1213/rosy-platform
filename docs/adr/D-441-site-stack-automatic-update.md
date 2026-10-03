## D-441 사이트 스택 자동 업데이트: main push 빌드 → 서명 PC 자동 서명 → 사이트 호스트 자동 설치·롤백

**Status:** Accepted (2026-10-04, 사용자 결정; D-437 수동 실행·손 서명과 D-301 운영자 승인 개정, workflow push 실행·서명 PC 예약 작업·호스트 설치와 첫 자동 갱신은 미검증, 사이트 키 미준비). 저장소의 workflow·서명기·호스트 갱신기·문서까지가 이 결정의 구현이다. workflow의 push 실행, 서명 PC의 예약 작업 등록, 사이트 호스트 설치와 첫 자동 갱신은 아직 실제로 돌려 보지 않았다. 사이트 서명 키는 D-301대로 아직 준비되지 않았다.

**Connects:** D-301, D-412, D-434, D-437. **Amends:** D-437 결정 1(수동 실행만)·4(운영자 손 서명), D-301 결정 2(서명 전 운영자 승인).

### Context

- D-437은 사이트 후보를 GitHub hosted runner에서 빌드하고, 서명 스테이션에서 운영자가 `release.json`만 손으로 서명하게 했다. 빌드는 수동 실행(`workflow_dispatch`)뿐이었다.
- 실제로는 main에 합친 코드를 사이트 호스트에 올리는 데 사람이 네 번 손을 대야 한다(실행, 해시 옮기기·출처 확인·서명·업로드, fetch, 검증·load·전환). 지금 사이트는 시험대이고, 자주 바뀐다.
- 로봇은 이미 서명된 GitHub Release에서 스스로 갱신한다(D-412). 관제 PC는 사이트 스택만 맡는다(D-434).
- 2026-10-04 사용자 결정: 사이트 스택도 스스로 갱신한다. main에 합친 코드가 곧 사이트 배포가 되는 것(시험대 운용)을 받아들인다.

### Decision

1. **main push가 빌드한다.**
   - `build-site-candidate.yml`에 `push: branches: [main]`을 더한다. `paths:`는 후보 이미지와 묶음에 들어가는 것 전부다. `build_candidate.py`가 Dockerfile에서 읽는 원본 경로(`deploy/site`와 Fleet·Vision의 COPY 원본), `DOC_FILES`, workflow 파일 자신이다. 시험이 두 목록을 맞춘다.
   - push에서 빌드하는 커밋은 `github.sha`다. 사전 job이 같은 태그의 릴리스를 찾으면 push는 notice만 남기고 성공으로 끝낸다(빌드 생략). dispatch는 지금처럼 바로 실패한다.
   - 새 push가 옛 push의 **빌드 job만** 취소한다(job 단위 concurrency, push끼리 한 그룹). dispatch는 실행마다 자기 그룹이라 취소되지 않는다. 출처 증명 job은 취소 그룹에 없다. 릴리스 job은 취소하지 않는 한 그룹에서 줄을 선다. 그래서 만들다 만 릴리스나 동시 정리가 생기지 않는다. 기다리던 릴리스 job은 더 새 것으로 바뀔 수 있다(최신이 이긴다).
   - 옛 `site-*` 정리(최신 3개)는 그대로다.
2. **서명 PC가 자동으로 서명한다. 키는 그 PC에만 있다.**
   - `deploy/site/auto_sign_candidates.py`를 예약 작업(Windows, 10분마다, 로그인한 현재 사용자; `register_auto_sign_task.ps1`)이나 Linux 타이머로 돌린다. 설정 파일(JSON)은 저장소 밖에 둔다.
   - 서명 전에 아래를 **모두** 확인한다. D-437의 "운영자가 해시를 옮기고 출처를 확인한 뒤 서명한다" 절차를 기계가 그대로 한다.
     1. 태그가 `^site-[0-9a-f]{12}$`이고, `release.json`이 있고, `release.json.sig`가 없다.
     2. `release.json`만 새 임시 폴더에 받는다.
     3. `gh attestation verify release.json --repo <R> --signer-workflow <R>/.github/workflows/build-site-candidate.yml --source-ref refs/heads/main --format json`이 통과한다. 결과의 `release.json` subject digest가 받은 바이트의 SHA-256과 같다. 이 값이 `--expected-manifest-sha256`이 된다(D-437의 "실행 기록에서 옮긴 해시"를 대신한다. 출처 증명도 자산 쓰기 권한으로 고칠 수 없다).
     4. manifest의 `source_commit`이 main의 조상이거나 같다(`gh api repos/<R>/compare/<sha>...main`의 status가 `ahead` 또는 `identical`).
     5. 태그가 `site-<source_commit[:12]>`이다.
     6. 기존 `sign_candidate.sign_manifest_only`가 기대 커밋·기대 해시로 받아들인다(manifest 형식·이미지 태그·플랫폼, 공개 키 자가 검증). 서명기를 다시 구현하지 않고 그 함수를 부른다.
     7. 올리기 직전 다시 봐서 서명이 이미 붙었으면 올리지 않는다. `--clobber`를 쓰지 않는다.
   - 결정마다(서명, 거부와 이유) JSON 한 줄을 상태 폴더의 `audit.jsonl`에 남긴다. 같은 바이트의 거부는 다시 검사하지 않는다(`release.json`이 바뀌면 다시 본다). 종료 코드는 0(할 일 없음), 10(서명함), 20(거부·오류), 2(설정·잠금)이다.
   - `gh` 토큰은 이 저장소의 Contents 읽기·쓰기만 갖는 fine-grained 토큰으로 둔다.
3. **사이트 호스트가 서명된 후보를 스스로 설치한다.**
   - `deploy/site/rosy_site_autoupdate.py`와 `rosy-site-autoupdate.service`(oneshot, root)·`.timer`(15분, `RandomizedDelaySec`, `Persistent`)를 운영자가 `/usr/local/lib/rosy-site`의 검증기 옆에 설치한다. 갱신기와 검증기는 검증할 후보에서 오지 않는다(D-301 결정 3 그대로).
   - 한 번 실행: 잠금 → `site.env`의 현재 태그 → 공개 릴리스 목록(HTTPS, 토큰 없음, 쪽 넘김) → 설치된 것보다 나중에 만들어졌고 `release.json.sig`가 있으며 여기서 실패한 적 없는 가장 새 `site-*` → 설치. 옛 후보로 내려가지 않는다.
   - **덮어쓰기 거부.** Compose override가 사이트 서비스의 `image:`를 고정하면 옛 코드가 "건강하게" 계속 돌 수 있다. 그래서 `ROSY_SITE_PAIRING_COMPOSE`가 후보의 `compose.pairing.yaml` 말고 다른 파일을 가리키거나, `site.env`가 `COMPOSE_FILE`을 정하거나, 스택 unit(drop-in 포함)이 다른 `-f`를 더하거나, 새 태그로 돌린 `docker compose config`가 세 서비스를 `rosy-site-<service>:<commit>`으로 풀지 않으면 아무것도 바꾸지 않고 거부한다.
   - 내려받기 → `SHA256SUMS` → 조각 잇기 → D-437 tar 구성원 규칙과 `data` 필터로 `/opt/rosy/candidates/<commit>`에 풀기 → 설치된 검증기와 `/etc/rosy/site/autoupdate.conf`의 신뢰 키로 `--signature-only`에 해당하는 검증 → `docker image load` → 전체 검증.
   - 전환: `site.env` 태그를 원자적으로 쓰고(백업 유지) `/opt/rosy/candidate` symlink를 원자적으로 바꾼다. 그 자리가 실제 폴더면 처음 한 번 `/opt/rosy/candidates/<그 커밋>`으로 옮긴다. 그리고 `rosy-site-stack.service`를 재시작한다.
   - 건강 확인: 설정한 `healthz`가 200이고 세 컨테이너가 모두 running·healthy이며 새 이미지로 돌아야 한다(시간 제한 안에). 아니면 이전 symlink·`site.env` 백업으로 되돌리고 재시작하며, 그 태그를 실패로 기록한다. 실패한 태그는 자동으로 다시 시도하지 않는다(`forget-failed`로 운영자가 푼다).
   - 최신 K개 후보 폴더(지금 것과 직전 것은 항상)를 남기고, 어떤 컨테이너도 쓰지 않는 옛 `rosy-site-*` 이미지를 지운다.
   - 단계마다 JSON 한 줄을 journal에 쓰고 상태를 `/var/lib/rosy/site-autoupdate.json`에 둔다. `--dry-run`은 선택과 덮어쓰기 검사만 하고 아무것도 받거나 바꾸지 않는다.
   - 첫 설치는 지금처럼 손으로 한다. 갱신기는 돌고 있는 후보만 바꾼다.
4. **멈추는 법.** 호스트는 `systemctl disable --now rosy-site-autoupdate.timer`, 서명 PC는 예약 작업 비활성화. 둘 중 하나만 멈춰도 새 배포가 멈춘다.

### D-437·D-301 개정

- D-437 결정 1의 "main push만으로는 후보나 릴리스가 생기지 않는다"를 바꾼다. 위 경로를 건드린 main push가 후보를 만든다. dispatch는 남는다.
- D-437 결정 4와 D-301 결정 2의 "운영자가 승인한 manifest"는 이제 "위 2의 검사를 모두 통과한 main 빌드의 manifest"다. 서명은 "main의 이 커밋에서 이 workflow가 만든 이 manifest"를 증명한다. 사람이 커밋 내용을 본다는 뜻은 더 이상 없다. main에 합치는 리뷰가 그 자리를 맡는다.
- D-301 결정 2의 나머지(키는 서명 PC에만, 덮어쓰기 거부, 공개 키 자가 검증, 키 비포함)와 결정 3·4(따로 설치한 검증기와 키, 서명 → 해시 → load → 이미지 ID)는 그대로다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 지금처럼 손으로 실행·서명·설치 | 안전하지만 바뀔 때마다 사람 네 단계. 시험대 운용에 맞지 않는다. 기각 |
| runner에서 서명(키를 GitHub secret으로) | D-437에서 기각한 그대로. 저장소 쓰기 권한이 곧 발행 권한이 된다. 기각 |
| 사이트 호스트에서 서명 없이 출처 증명만 확인 | 호스트에 `gh`와 Sigstore 신뢰가 필요하고, D-301의 오프라인 키 신뢰 고리가 사라진다. 기각 |
| 서명 PC 자동 서명 + 호스트 자동 설치(채택) | 키는 PC에 남고, 호스트 신뢰 고리(D-301)는 그대로다. 서명 전 검사는 기계가 매번 같은 순서로 한다. 채택 |

### Consequences

- main에 합친 사이트 코드는 약 30분 안에 사이트에서 돈다. 깨진 코드가 들어오면 건강 확인이 되돌리고 그 태그를 다시 시도하지 않는다. 건강 확인을 통과하지만 기능이 틀린 코드는 그대로 배포된다. 이것이 사용자가 받아들인 시험대 운용이다.
- 서명 PC의 키는 사람 없이 쓰인다. 그 PC나 그 사용자 계정을 장악하면 main 빌드가 아니어도 서명할 수 있다. 자동 서명기가 지키는 것은 "GitHub 쓰기 권한만 가진 사람이 바꾼 자산"과 "main이 아닌 빌드"다. PC 보호는 운영 책임이다.
- GitHub 저장소 쓰기 권한으로 main에 직접 push할 수 있다면 그 코드도 서명된다. main 보호 규칙이 사이트 배포의 문이 된다.
- 로봇 갱신(D-412)은 첫 쪽 20개 릴리스에서 `payload-*`를 찾는다. push마다 빌드가 생기지만 `site-*`는 최신 3개만 남으므로 그 쪽을 밀어내지 않는다. 다른 릴리스가 20개를 넘는 문제는 D-437 후속 작업 그대로다.
- 호스트가 오래 꺼져 있으면 정리된 중간 후보는 건너뛰고 최신을 설치한다.
- 검증기·서명 모듈이 main에서 바뀌면 호스트에는 관리자가 같은 검토 경로로 다시 설치해야 한다. 갱신기는 그것들을 후보에서 복사하지 않는다.

### Validation

- 호스트 시험(네트워크·Docker 없음): workflow 계약(push 트리거와 경로가 이미지 원본·문서를 모두 덮음, push는 기존 릴리스에서 성공·dispatch는 실패, 빌드만 취소, 릴리스 job 비취소 그룹), 자동 서명기(정상 서명·업로드, 출처 digest 불일치 거부, main 아닌 ref 거부, main에 없는 커밋 거부, 이미 서명된 릴리스 건너뜀, 태그·커밋 불일치 거부, 경합 시 덮어쓰기 안 함, dry-run, 설정·잠금), 호스트 갱신기(선택 규칙, override 거부 네 가지, 건강 실패 롤백, healthz 실패 롤백, 정상 전환과 정리, 실제 폴더 symlink 이주, 첫 설치 없음 거부, 조각 변조·링크 구성원 거부, dry-run, 잠금, unit·timer·runbook 계약). symlink가 필요한 시험은 Linux에서 돈다(Windows 개발 PC는 건너뜀, 컨테이너 Linux에서 확인).
- 아직 안 된 것: workflow의 첫 push 실행, `gh attestation verify --format json`의 실제 출력 형식 확인(서명기는 `verificationResult.statement.subject`를 읽는다), 서명 PC 예약 작업 등록, 사이트 호스트 설치와 첫 자동 갱신·롤백, systemd 하드닝과 Docker·systemctl 호출의 실제 호환. 사이트 키 준비는 D-301대로 별도 gate다.
- 이 ADR은 로봇 이동이나 정책 실행을 허락하지 않는다.

**Related:** [D-301](D-301-site-candidate-signatures.md), [D-412](D-412-robots-self-update-from-signed-github-releases-when-idle.md), [D-434](D-434-model-pc-and-site-pc-roles.md), [D-437](D-437-github-hosted-builds-and-offline-local-signing.md).
