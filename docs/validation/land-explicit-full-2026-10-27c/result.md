# Tool1 전체 추적 파일 가드 실패와 exact provenance 회복

2026-10-27 KST. 이전 [충전 실패·대조 기록](../land-explicit-full-2026-10-27b/result.md)은 보존했다. 아래 결과는 로컬 소스와 공식 원격 시험의 근거이며 전체 FULL·착지·게시·장치 수용을 뜻하지 않는다.

## 중단된 전체 검증

- 후보: 로컬 commit `30168bec9d02bfec738b62370fda5b2f9ab14d71`. 공식 `land.py --tests auto --no-cache`의 FULL 준비 회차는 exit1로 중단됐다.
- 사전 검사 234초: architecture 287 PASS, collect 2,138 PASS/1 SKIP, alone 21 PASS/1 SKIP·21개 완료·overflow 없음. 각 known 분류는 NEW0/known0/flaky0이다. 단일 skip은 source와 실행 인자상 반대 모드의 빈 parameter이며 raw에는 이유 문장이 없다.
- 완료 body는 25호출 중 두 개다. Fleet13은 7,031 PASS/391 SKIP/0 FAIL·721.84초, root23은 11,503 PASS/1,214 SKIP/1 FAIL·1,154.07초다. 합계 18,534 PASS/1,605 SKIP/1 FAIL은 중복 범위를 포함한다. 나머지 23호출은 취소·미실행이다.
- Core10은 다른 호출의 실패 뒤 취소된 partial이다. 완료 summary와 charging FAILED 줄이 없으며 충전 통과·비재발 근거가 아니다.
- 실패 id: `test/test_release_boundary_guards.py::test_no_secrets_in_tracked_files`. 후보 단독은 1 FAIL·27.40초, 당시 로컬 main 기준 commit `2f2494cf324f3db703469a32a73d4afe3d9e86e5`의 단독 대조는 1 PASS·24.73초였다. owning NEW로 착지하지 않았다.
- 외부 보존: `%LOCALAPPDATA%/Temp/rosy-land-explicit-full/failed-full-30168/`. 현재 실행에 연결한 raw 8개를 동일 해시로 복사했고 독립 `critic-audit.md`에서 argv/source를 대조했다. 과거 namespace의 다른 파일은 집계하지 않았다.
- 실패 console SHA-256: `FFECA4D0C21E23B8A9F75F0B718E4C19C9C52B39BE464175C7FC0086AF22B9EE`.

## 원인과 제한된 수정

게시의 commit/path/rule 검토 대장과 전체 추적 파일 검사의 exact-line provenance 목록은 독립이다. 이전 수정은 게시 대장만 보완했다. 전체 파일 가드는 고정 기록 27b의 7행에 있는 두 Git 참조를 계속 보고했다.

두 참조가 실제 commit 객체이며 기록이 원본 commit `296fdfc384`의 blob과 같음을 독립 검토했다. 기존 `public_provenance.json`에 정확한 경로·UTF-8 행 해시·두 참조 한 건만 추가했다. 기존 231개 record와 순서, 고정 기록, 게시 대장, scanner·규칙·임계값은 유지했다. 행 SHA-256: `9a7cf965bb5edb53522f1e1366a83c7cfc0178437f59a32c189198b476abc241`.

최초 보완 commit `9c8dbc22d0`에는 로그의 필수 증거 라벨 누락이 있었다. lint 실패의 종료 코드를 확인하기 전에 커밋한 실수를 보존한다. 후속 commit `f44520f70e`는 문장·결과를 바꾸지 않고 라벨만 교정했으며 기존 `log_repairs.yaml`의 정확한 old/new block 해시 한 쌍으로 제한했다. 기존 13쌍은 유지했다. 일반 라벨 허용·시험 완화·이력 재작성은 없다. 수정 후 lint는 0 errors/37 warnings였다.

## 커밋된 수정의 집중 원격 확인

소스는 로컬 commit `f44520f70ee626644a86232b85e655203b3de740`이다. 디스크 기준을 통과한 model·AI만 허용한 외부 wrapper에서 공식 runner를 호출했고 실제 실행은 model 역할이었다. Site와 노트북에서 pytest를 실행하지 않았다.

```text
python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- test/test_harness_contracts.py test/test_release_boundary_guards.py
python test/known_failures.py <external-log-dir>/run-1.txt
```

- 실제 결과: 183 PASS/0 SKIP/0 FAIL, 40 warnings, 49.39초. runner·외부 명령·known 분류 exit0, NEW0/known0/flaky0. listed but not failing 한 건은 skip이 아니다.
- 환경: env `499c18d0ee491bcf`, freeze `279c2df20eca6924`.
- 외부 근거: `%LOCALAPPDATA%/Temp/rosy-land-explicit-full/` 아래 `provenance-guards-f445/`, `provenance-guards-f445-runner.txt`, `provenance-guards-f445-known.txt`.
- raw `run-1.txt` SHA-256: `ced2958090776a930438c89388b8335fcef28554aadd60e3793930217178e5d1`.
- runner SHA-256: `49d55ddf1f4ffea8ab476135172f74b0b0f1eec7a37f083ae8bdafa72be17d94`.
- known SHA-256: `c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e`.

이 결과는 secret·journal 가드의 회복만 검증한다. 취소된 충전 시험의 원인 해결이나 NTP 정확도, 전체 FULL, 공개 CI, 실물 배포를 입증하지 않는다. 기존 [Git ID 교훈](../../solutions/workflow-issues/git-ids-in-validation-records-need-the-commit-prefix-2026-10-07.md)에 두 검사와 고정 기록 처리의 차이를 보완했다.
