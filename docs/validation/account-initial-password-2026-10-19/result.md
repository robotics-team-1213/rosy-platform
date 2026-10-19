# ID! 초기 비밀번호와 프로필 변경 검증

2026-10-19 사용자 후속 지시로 기존 ID 목록의 초기 비밀번호를 `ID + !`로 준비하고 본인이 변경하도록 한다. 이 지시는 확인된 대상의 명시적 초기화이며 모든 기존 사용자를 자동 초기화하는 정책이 아니다. 실제 명단·자격은 private 영역에서만 다룬다.

## 구현

`fix/account-initial-password-policy`를 main `6bf5d191e6`에서 분리했다. legacy 초기 상태와 Account bootstrap은 기존 ID와 같은 초기값 및 ID!를 첫 변경 대상으로 인식한다. 기존 관리자 create/reset은 정확한 ID!만 짧은 임시값으로 허용하고 `change_required=1`을 유지한다. 관리자 HTML 임시 입력만 minlength2로 맞췄다. 다른 짧은 값은 서버가 거절한다.

본인 첫 변경·프로필의 영구 비밀번호는8~1024자, ID/ID!와 다른 값이어야 한다. 현재 비밀번호 확인·same-origin·세션 교체/회수·Account revision·재시작 후 유지 계약을 보존했다. 새 API/자격 종류/권한/의존성은 없다. [Account protocol](../../reference/rosy-account-protocol.md)에 계약을 기록했다.

## 커밋 기반 실행

모델 PC에서 최종 제품/시험 소스 **`103df862b1`**를 실제 Chromium opt-in으로 실행했다.

```powershell
python tools/remote/remote_pytest.py --sha 103df862b1 --log-dir <external-log-dir> -- ROSY_RUN_BROWSER_TESTS=1 operations/fleet/test/test_password_session.py operations/fleet/test/test_account_ledger.py operations/fleet/test/test_self_profile.py operations/fleet/test/test_password_login_browser.py operations/fleet/test/test_fleet_account_browser.py operations/fleet/test/test_account_admin_browser.py -q
python test/known_failures.py <external-log-dir>/run-1.txt
```

실제 결과 **160 passed, 0 skipped, exit0, NEW/known/flaky0**. 로그 `%TEMP%/rosy-account-rollout-20261019/password-policy-final-readback/run-1.txt`, SHA-256 `ecb30bc7d14200129596b56f244ad87886990872536e180bec1408d33abeb28c`.

새 회귀는 ID!의 최초 쿠키 업무 제한, bootstrap 후 본인 변경·재시작, 긴 ID!를 영구 비밀번호로 되돌리는 시도 거부, 짧은 ID! create/reset, 그 밖의 짧은 값 거부, 실제 관리자 HTML→제한 로그인→본인 변경→프로필 복귀를 확인한다. 기존 profile·세션·CSRF·권한·회수 회귀도 위 명시한 범위에서 실행했다. 운영 당사자의 로그인은 아니다.

## 실패와 독립 리뷰

- 최초 f794aebc4의 RED는 정책 누락4개와 test helper의 source hash 재생성 실수1개였다. helper는 기존 default hash를 재사용하도록 고쳤다.8675d2453의5파일153 passed·skip0·NEW0은 중간 결과다.
- 독립 리뷰가 짧은 ID!의 관리자 생성/reset·HTML 길이 불일치를 발견했다. ce07b9531에서 실제3개 RED로 재현하고07f04030f에서 보완했다. 재검토는 기존 Important가 해소됐고 추가 finding이 없다고 판단했다. 리뷰어는 시험을 실행하지 않았다.
- 07f04030f의 첫6파일 실행은 본인 변경 후 관리자의 오래된 revision으로 revoke를 시도한 브라우저 검사1개가 실패했다. 서버의409 보호가 정상 작동한 경우다.103df862b는 관리자 목록을 재조회한 뒤 다음 작업을 수행하도록 fixture 흐름을 수정했다. 위 최종160개 통과와 구분한다.

## 실제 반영의 남은 관문

사용자는 main 병합·서비스 활성화를 지시했다. foundation 회귀, 앱 변경, ADR/절차, 이번 정책을 분리해 기존 FIFO 착지 관문을 사용한다. 이 기록 시점 main 착지·push·CI·서명 배포·운영 비밀번호 초기화는 미완료다.

현장 기존 설정은 사람 로그인5개·기계 자격4개이며 사용자 요청의6명 명단과 다르다. 사용자는 명단이 Confluence 또는 Notion에 있을 것이라고 안내했다. 연결된 Notion 검색은 `Authentication required`로 거부됐고 Confluence 도구는 제공되지 않았다. 재인증/정확한 페이지 또는 ID 목록을 요청한 상태다. tailnet 프로필도 의도한 명단과 일치하지 않으므로 사용자로 추측해 추가하지 않았다.

현장 보호 폴더에는 확인된 기존5개 ID의 ID! 해시 후보를 기존 parser로 검증해 보관했다. 기계 자격은 동일하게 유지했고 운영 파일·DB에는 적용하지 않았다. 전체6명 명단과 관리자 ID를 확인한 뒤 백업·서명 배포·명시적 초기화·실제 본인 로그인/비밀번호 변경 readback이 필요하다. 실제 사용자 수용·계정 이관·열린 업무/미디어 회수와 복구를 이 소스 시험으로 대신하지 않는다.
