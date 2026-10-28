# D-841 공유 모듈 소비와 독립 앱 HTTP 검증 — 2026-10-22

[D-841](../adr/D-841-shared-module-reuse-and-integration.md)의 구현·시험 증거다. 플랫폼 기준은 `238af6c8990fd282995a32996f504af2239c9b95`, 최종 제품 코드 커밋은 `f17e5dd873`, 후속 시험 수정은 `f048fe9471e4f571eb8bc1e0cd33212c72d85968`이다. 후자의 diff는 시험 두 파일뿐이다. 모든 플랫폼 pytest는 커밋된 소스를 공식 `tools/remote/remote_pytest.py`로 승인된 시험 PC에서 실행했다. 노트북 pytest·운영 서버·장치 명령은 실행하지 않았다.

## 구현과 검토

- Fleet enrollment·camera-pairing이 기존 `shared/web/request.js:createRequest`를 소비한다. 현재 bearer와 추가 헤더, 상세 오류, 취소·화면 수명 검사를 유지한다. 공통 request API와 POST 재전송 정책은 바꾸지 않았다. camera-peer는 D-841의 파싱·헤더 처리 차이로 제외했다.
- 학습 여덟 파일의 경로 검사 정의를 curation·registry 소유 범위의 두 표준 라이브러리 helper로 합쳤다. `.git` 디렉터리·worktree 파일·미생성 출력·symlink resolve 정책을 보존한다. 기존 다른 배포 단위의 guard와 CORE/Fleet proof helper는 유지한다.
- 독립 코드 검토에서 파일 로더의 sibling import 순서 회귀가 발견됐다. `78749e5021`에 격리 subprocess 회귀를 추가하고 `f17e5dd873`에서 자기 경로 초기화 뒤로 helper import를 옮겼다. 리뷰어가 수정 범위를 재검토했다.
- 전체 영향 시험은 이전 변수명을 요구하는 `error.status = resp.status;` 문자열 검사를 발견했다. `f048fe9471`에서 이 한 줄을 제거하고 두 실제 panel의 plain 404 폴링 차단, 120초 후 차단 유지, `resetPolling()` 후 재요청 시험으로 대체했다. 독립 재검토에서 추가 finding은 없었다. 실제 로그인 이벤트 배선은 이 새 시험의 범위 밖이다.

## 플랫폼 실행 결과

아래 명령의 공통 진입점은 `python tools/remote/remote_pytest.py --log-dir <외부 로그 디렉터리> -- <인수>`다. 최종 후속 명령에는 `python -X utf8`을 사용한다. 로그 경로는 실행 PC의 `%TEMP%/rosy-shared-reuse/` 기준이며 raw 로그는 Git에 넣지 않았다. 각 완료 로그를 `python test/known_failures.py <로그>`로 비교했다.

| 소스 | pytest 인수·범위 | 관측 | 로그 |
|---|---|---|---|
| `cada481c56` | `test/test_network_topology_contracts.py test/test_harness_contracts.py -q` | 124 passed, skip 0, NEW 0 | `docs-fixed/run-1.txt` |
| `5351187b44` | `ROSY_RUN_BROWSER_TESTS=1 shared/web/test/test_transport.py operations/fleet/test/test_site_map_api.py operations/fleet/test/test_console_camera_pairing.py operations/fleet/test/test_camera_peer_browser.py -q` | 43 passed, skip 0, NEW 0 | `fleet/run-1.txt` |
| `fab496a567` | `learning/curation/omx/test learning/registry/policy/test -q` | 330 passed, 3 skipped, NEW 0 | `learning-green/run-1.txt` |
| `f17e5dd873` | `learning/curation/omx/test/test_output_paths.py learning/curation/omx/test/test_collection_intake.py learning/curation/omx/test/test_native_review.py -q` | 57 passed, 1 skipped, NEW 0 | `loader-green/run-1.txt` |
| `f048fe9471` | `operations/fleet/test/test_console_disabled_features.py operations/fleet/test/test_site_map_api.py::test_console_web_node_unit_tests_pass -q` | 3 tests 통과, exit 0, skip 0, NEW 0 | `disabled-pollers-green/run-1.txt` |

Fleet Node는 최초 전송 옵션 RED 2개를 확인한 뒤 전체 352개가 통과했다. 마지막 폴링 행동시험을 포함한 대상 panel Node 11개도 로컬에서 통과했고, 최종 전체 Node는 위 원격 wrapper로 재확인했다. 학습 helper 부재 RED 8개는 `2a372c6c2d`에서 공식 원격으로 확인했다. 노트북의 순수 import 진단은 helper 탐색 오류를 재현했으나 수정 뒤 numpy 부재로 전체 import를 완료하지 못했다. 그 진단을 GREEN으로 계산하지 않았다.

`f17e5dd873`의 원격 환경에서 변경 대상 CLI 여덟 개의 `--help`가 모두 exit 0이었다. 실제 출력 생성 CLI smoke를 별도로 반복하지 않았으며, 출력 거절·기존 데이터 보존은 소비자 pytest 범위로 확인했다. 위 skip은 통과로 합산하지 않았고 개별 원인을 이 기록에서 분류하지 않았다.

전체 영향 범위는 `python tools/harness/rosy_harness.py affected --base 238af6c8990f --json`의 `mode=affected`, escalation 없음, 두 invocation이다. 각 invocation에 `ROSY_RUN_BROWSER_TESTS=1`과 `-ra`를 추가하여 공식 runner의 `--affected-json -`으로 실행했다. serial 설정을 유지했다. CI FULL 또는 저장소 모든 시험을 실행했다는 주장은 하지 않는다. 첫 invocation은 `f17e5dd873`에서 **4626 passed, 31 skipped, 5 subtests passed, NEW 0**이었다(`affected-final/run-1.txt`).

## 독립 앱의 실제 HTTP

앱은 승인된 remote helper의 SSH·자원 제한을 사용해 실행별 임시 디렉터리에 Git bundle로 전달하고 수신 측에서 bundle과 전체 SHA를 확인했다. 새 배포 도구나 운영 설정은 만들지 않았다. 플랫폼 의존성 환경의 loopback 서버와 별도 앱 시험 프로세스를 사용했다. Port 전용 무의존 venv 및 신규 설치 버전 목록은 만들지 않았으므로 새 앱 배포 환경 수용 증거로 사용하지 않는다.

- **Port:** `5d6c4ba39c297e30bed3fef82d32a3b94b544a8d`, 플랫폼 `238af6c8990fd282995a32996f504af2239c9b95`, 기존 Vault 시험 하네스 `ad7030b319d5796ba45e7287f7dfe170470283b8`. 새 opt-in launcher가 SHA·dirty 상태를 검증하고 기존 서버 조립을 재사용한다. 기본 unittest는 47 tests/exit 0/통합 미설정 skip 1, 명시 실제 HTTP 통합은 **2 tests/exit 0/skip 0**. compile/proposal/job 조회, candidate 동일 키 재접수·본문 충돌·viewer 거절·busy 응답을 확인했다. 명시 모드의 설정 누락은 실패했다. runtime `harbor`에 플랫폼 import나 새 의존성은 없다. 소유 기록: rosy-port `docs/validation/2026-10-22-shared-module-reuse.md` (`2f365ea`).
- **Vault:** 제품 소스 `ad7030b319d5796ba45e7287f7dfe170470283b8`, 기존 플랫폼 pin `8be38f1b94c937c9864fb26488cd2b8549fc06b2`. 공유 platform venv 첫 시도는 ReadTimeout/input과 후속 admit 409로 2개가 실패했다. 같은 S1/S2 분리 실행은 통과했다. 원인을 단정하거나 제품 코드를 바꾸지 않고 문서의 별도 환경으로 재검증했다. Vault requirements 환경의 **290 passed/4 integration skipped**, 고정 플랫폼 Fleet requirements+pytest 8.3.5 통합 환경의 **4 passed/skip 0/exit 0**를 확인했다. 소유 기록: rosy-vault `docs/validation/2026-10-22-shared-module-reuse.md` (`18a93a9`).

이 서버는 실제 Fleet HTTP·compiler·장부를 사용하지만 robot/arm과 관측은 시험용이다. Port의 물리 관측 producer 어댑터와 장치 수용은 후속 과제다. Vault DEFERRED를 픽업 완료로 취급하지 않는다. main 착지·push·배포·실물·현장 검증은 수행하지 않았다.

## 전체 영향 실행의 종료와 후속 확인

두 번째 invocation도 같은 `f17e5dd873`에서 완료됐다. **7318 passed, 8 skipped, 1 failed**, 2047.43초였으며 유일한 실패는 `operations/fleet/test/test_console_disabled_features.py::test_console_gates_disabled_feature_pollers`다. known-failure 비교는 NEW 1/known 0/flaky 0이었다. 이 실패를 known-failure 목록에 추가하지 않았다.

해당 실패는 위에서 설명한 이전 변수명 문자열 검사이며 `f048fe9471`의 실제 panel 행동시험과 기존 disabled 검사·전체 Node wrapper의 원격 exit 0으로 수정 범위를 확인했다. 제품 코드 변경은 없었다. 두 broad invocation 합계는 11944 passed/39 skipped/1 failed이며, 이를 최종 커밋에서 전체 재실행한 GREEN으로 표현하지 않는다. test-only 수정 후 34분의 두 번째 invocation을 반복하지 않았다. 수정된 범위의 실제 원격 통과와 나머지 동일 제품 코드의 broad 결과를 함께 남긴다.

증거 문서 작성 시 harness lint는 0 errors/기존 33 warnings였다. main 착지 또는 게시 시에는 그 시점의 저장소 절차와 최신 SHA 검증을 다시 적용해야 한다.

## 원본 로그 SHA-256

| `%TEMP%/rosy-shared-reuse/` 아래 경로 | SHA-256 |
|---|---|
| `docs-fixed/run-1.txt` | `4d1d0471a3d5f9b61ef0d6897ec8aebab37ce416a6eb508243f322696537cd1f` |
| `fleet/run-1.txt` | `742ebdb2227c0ca7b4e5879fb19453572bcf8194fa25e826af04e5e15b393366` |
| `learning-green/run-1.txt` | `94288f76d7842b222e4c9964fba9b4e1e23b707a5ad7ba83dd39d8af28711781` |
| `loader-green/run-1.txt` | `be568706f888eaf0c39815542004a5821750463c27e943f350bae74f6c510187` |
| `disabled-pollers-green/run-1.txt` | `6e7062a29471f6791eec15c046eca52676f997ca1170a4341905d110235424a2` |
| `affected-final/run-1.txt` | `3f85e1fcfbea96e6fa5835a367d5976558a2a4cbd25a548d6c699e84094160d4` |
| `affected-final/run-2.txt` | `cb8a64315274729266eece5d68b5712ecc504b23a3e30e44caf3f7b9b38f5975` |
| `apps/run-1.txt` (Port 성공과 Vault 첫 실패 모두 보존) | `272b4fbe0574d6d5e80f5d10f6d7173943aa144f05dded26b5c221374362d76b` |
| `apps/vault-repeat.txt` | `e0663f1e598b7a788282d9cadb824b4a5fcfc00930be268fa420626f2157ea92` |
| `apps/vault-environments.txt` | `d239c8f14772c209ef15778db9a460b63c4b905f176da7d16793553e8de43869` |
