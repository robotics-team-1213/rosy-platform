# ROSY 릴리스 서명 키 운용

- **Document ID:** ROSY-DEPLOY-SIGNKEY-001
- **Status:** v1
- **Related:** `docs/plans/2026-09-01-rosy-os-v1-image-release-design.md` §7.4/§9.1,
  `deploy/robot/pinky_pro/release/signing.py`

## 1. 이 키가 무엇을 결정하는가

장비는 릴리스를 받으면 `SHA256SUMS`에 대한 Ed25519 detached signature를 먼저
검증하고, 통과한 뒤에야 개별 파일 checksum을 확인한다. 즉 **이 키를 가진 사람이
그 장비에 무엇이든 설치할 수 있다.** 컨테이너 이미지, systemd unit, 업데이트
스크립트가 모두 이 서명 하나 뒤에 있다.

v1은 신뢰 키를 **하나만** 쓴다. 장비의 `/etc/rosy/trusted-release-keys/<key-id>.pem`
에 공개키가 있고 manifest의 `signing_key_id`가 그것을 가리킨다.

## 2. 두 가지 결과를 먼저 이해할 것

**키가 유출되면** 공격자가 서명한 번들을 장비가 정품으로 받아들인다. v1에는 온라인
키 폐기 경로가 없다. 대응은 새 신뢰 키를 담은 recovery 이미지를 만들어 **모든 장비를
물리적으로 다시 굽는 것**이다.

**키를 잃어버리면** 그 순간부터 어떤 릴리스도 서명할 수 없다. 현장의 모든 장비가
업데이트 불능이 되고, 복구는 역시 새 키를 담은 recovery 이미지를 물리적으로 굽는
것뿐이다.

두 실패의 복구 비용이 같고, 둘 다 현장 방문을 요구한다. 그래서 백업과 접근 통제를
둘 다 진지하게 다뤄야 한다. 어느 한쪽만 잘해도 소용이 없다.

## 3. 생성

서명 전용 환경에서만 생성한다. 빌드 호스트도, 개발 PC도, 저장소도 아니다.

```bash
umask 077
openssl genpkey -algorithm ed25519 -out rosy-release-2026-01.key
openssl pkey -in rosy-release-2026-01.key -pubout -out rosy-release-2026-01.pem
```

- `.key`가 개인키다. 이 파일은 서명 환경을 절대 떠나지 않는다.
- `.pem`이 공개키다. 장비의 `/etc/rosy/trusted-release-keys/<key-id>.pem`에 들어간다.
  승인된 공개키만 `deploy/robot/pinky_pro/release/public-keys/`에 커밋한다.
  `test_only_public_release_key_pems_are_tracked_in_the_repository`가 경로와
  공개키 표시와 개인키 표시 부재를 검사한다. 사용할 키는 Ed25519여야 하며,
  이 파일 경계 검사만으로 알고리즘 검증을 대신하지 않는다. 개인키는 저장소 밖에 둔다.
- key id(`rosy-release-2026-01`)는 manifest의 `signing_key_id`와 장비의
  `/etc/rosy/trusted-release-keys/` 파일명에 함께 쓰인다. 소문자·숫자·하이픈만
  허용된다(`deploy/robot/pinky_pro/release/manifest.py`의 `_KEY_ID`).

## 4. 보관

**서명 환경**은 네트워크에서 분리된 전용 머신 또는 하드웨어 토큰이어야 한다.
최소 요건:

- 개인키 파일은 `0600`, 소유자는 서명 작업 계정.
- 서명 환경에는 빌드 산출물을 반입만 하고, 개인키는 반출하지 않는다.
- 서명 작업 로그(언제, 어떤 release_id, 어떤 git revision에 서명했는지)를
  남기고 일반 artifact와 **분리 보관**한다.

**금지 사항.** 아래 넷 중 CI가 실제로 막을 수 있는 것은 저장소 안에서 일어나는
둘뿐이다. 나머지 둘은 운영 규율이며, CI가 지켜준다고 착각하면 안 된다.

| 금지 | 강제 수단 |
|---|---|
| 저장소에 개인키를 커밋하는 것 | `test_only_public_release_key_pems_are_tracked_in_the_repository` + `secret_scan` |
| 개인키 파일이나 승인된 공개키 경로 밖의 PEM을 추적하는 것 | 같은 테스트가 경로·확장자·공개키/개인키 표시를 확인. Ed25519 선택·서명 검증은 별도 |
| 컨테이너·SD 이미지에 개인키를 넣는 것 | **CI 밖.** WP-6의 이미지 검사가 마운트된 트리에 `secret_scan`을 돌려야 확인된다 |
| 빌드 호스트에 개인키를 두는 것 | **CI 밖.** 서명 환경 분리라는 운영 규율로만 보장된다 |

## 5. 백업

키 분실이 유출과 같은 비용을 갖기 때문에 백업은 선택이 아니다.

- 최소 2부를 서로 다른 물리적 장소의 오프라인 매체에 보관한다.
- 각 사본은 봉인하고 개봉 이력을 기록한다.
- 복구 절차를 **연 1회 실제로 리허설한다.** 읽히지 않는 백업은 백업이 아니다.
- 백업 매체에는 공개키와 key id도 함께 넣어, 어떤 키인지 나중에 식별할 수 있게 한다.

## 6. 교체와 폐기

v1의 온라인 키 rotation은 비범위다. 교체 경로는 하나뿐이다.

1. 새 키를 서명 환경에서 생성한다(§3).
2. 새 공개키를 담은 **recovery 이미지**를 빌드한다.
3. 각 장비를 그 이미지로 다시 굽는다.
4. 이후 릴리스는 새 key id로 서명한다.

즉 키 교체는 소프트웨어 업데이트가 아니라 현장 작업이다. 키를 만들 때 이 사실을
전제로 보관 수준을 정해야 한다.

## 7. 릴리스 서명 절차

> **2026-09-22 갱신:** 예고됐던 `sign_release.py` 대신
> `deploy/robot/pinky_pro/release/package_release.py`(오프라인 서명+번들)와
> `deploy/robot/pinky_pro/release/publication.py`(발행 검증)가 구현돼 있다. 아래는 실제로
> 존재하는 인터페이스다.

전제: D-145 네이티브 빌더의 unsigned payload를 D-146 importer가 검증해
`signed: false` handoff로 노출한 상태여야 한다. 첫 대상은
`manifest.json`에 `release_id: 2026.09.21-001`, full 40-hex `git_revision`,
`signing_key_id: rosy-release-2026-01`이 기입된 payload다.

### 7.0 파일럿 키와 게시 승인

현재 파일럿 공개키는 `public-keys/rosy-release-2026-01.pem`이다([키 상태](../../deploy/robot/pinky_pro/release/public-keys/README.md)). 개인키는 운영자의 보호된 오프라인 서명 환경에만 있으며 이 작업에서 조회하거나 생성하지 않았다. 프로덕션 키 소유권과 교체는 별도 릴리스 결정이다.

2026-10-17에 공개 저장소의 `release` 환경을 구성하고 API로 재확인했다.

| 항목 | 설정 |
|---|---|
| 승인 담당 | 기존 게시 담당 `livsbittt`. 단일 게시 담당이 자신의 실행도 승인할 수 있으며 두 사람 승인을 뜻하지 않음 |
| 실행 ref | `main` 브랜치만 허용. 입력한 릴리스 태그의 승인·서명 검증은 별도 |
| 관리자 우회 | 꺼짐 |
| 환경 변수 | `ROSY_RELEASE_KEY_ID=rosy-release-2026-01` |
| 환경 secret | 없음. 개인키를 GitHub로 전달하지 않음 |

실제 게이트 구성 근거는 [환경 검증 기록](../validation/release-environment-2026-10-17.md)을 본다. 이 설정 확인은 게시 시험이 아니다. 승인된 draft·태그·소스 SHA·외부 서명 산출물을 확보한 뒤 기존 검증 절차로 게시한다.

### 7.1 서명 환경(오프라인)에서 — package_release

```bash
# 0) 서명 환경 준비: python3, OpenSSL 3, zstd 번들 압축에 필요
# 1) payload 반입 + 반입 checksum 기록
sha256sum rosy-unsigned-payload.tar.zst > import-checksum.txt

# 2) 서명 + 번들 (개인키는 payload 디렉터리 밖 — 스크립트가 경계를 강제한다)
python3 deploy/robot/pinky_pro/release/package_release.py \
    2026.09.21-001/rosy-unsigned-payload \
    dist/rosy-release-2026.09.21-001.tar.zst \
    --public-key rosy-release-2026-01.pem \
    --private-key /secure/rosy-release-2026-01.key
```

`package_release`는 payload secret scan → `SHA256SUMS` 작성 → Ed25519 raw
서명 → `verify_tree`(공개키) → tar+zstd 번들 순서로 진행하고, 어떤 단계든
실패하면 번들을 남기지 않는다. 번들 파일명은
`rosy-release-<release_id>.tar.zst`로 고정된다(`PACKAGE_NAME`).

### 7.2 네트워크 측 발행 검증 — publication (공개키만 필요)

서명된 번들을 저장소 소유자에게 가져오면, 개인키 없이 검증한다:

```bash
python3 deploy/robot/pinky_pro/release/publication.py verify-publication \
    dist/rosy-release-2026.09.21-001.tar.zst \
    --release-id 2026.09.21-001 \
    --git-revision 397bb25de9d92e659ab68658a46f275203d52659 \
    --public-key deploy/robot/pinky_pro/release/public-keys/rosy-release-2026-01.pem \
    --json
# {"ok": true, "signed": true, "physical_acceptance": "HOLD", ...}
```

`signed: true`는 서명·번들 identity를 증명할 뿐이고 `physical_acceptance`는
별도 게이트로 HOLD로 남는다.

### 7.3 증거 귀환과 gate 연결

- 서명 작업 로그(언제, 어떤 release_id, 어떤 git revision)는 일반 artifact와
  **분리 보관**한다(§4).
- `publication.py` JSON 출력과 번들 SHA-256을 deploy 게이트 증거로 착지한다.
- ARTIFACT gate는 ① 승인된 키로 서명된 번들 ② publication 검증 JSON
  ③ 공개키 커밋 + `ROSY_RELEASE_KEY_ID` 승인 설정 ④ 기록이 모일 때 판정한다.
  이 넷은 장비 G0(stage/manifest)의 입력이 된다.


## 8. 검증 순서를 바꾸지 말 것

`verify_release_files`는 **서명 → checksum** 순서를 강제하고, 서명이 실패하면
파일 해시를 아예 계산하지 않는다. 순서를 뒤집으면 다음 공격이 통한다.

1. 공격자가 payload를 바꾼다.
2. 바뀐 payload에 맞게 `SHA256SUMS`를 다시 만든다.
3. checksum을 먼저 보는 구현은 "모든 파일 정상"을 보고한다.

서명만이 이것을 잡는다. 그래서 서명이 실패했을 때 checksum 결과를 함께 보고해서도
안 된다 — 신뢰할 수 없는 목록에 대한 "정상"은 오해를 만든다. 이 동작은
`test_payload_is_not_hashed_against_an_untrusted_checksum_list`가 고정한다.
