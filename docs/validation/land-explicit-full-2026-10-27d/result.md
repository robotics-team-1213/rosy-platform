# 2026-10-27 · actual main 737 통합과 CLI 회귀

[이전 고정 검증 기록](../land-explicit-full-2026-10-27/result.md)을 잇는 별도 후속 기록이다. 기존 기록은 수정하지 않는다.

기존 기록을 보존한 후속 단계다. local commit `eb58313466952dfefaeff5346eb81720b35db1aa`에 실제 main commit `737f296892108b4febe1a47ba18b4df3e779a7be`를 정상 병합했다. Root가 검토한 tree `636ef5b74b3d44e2c407ec660f7f3fa96c78addb`의 checkpoint commit은 `d2217085fe8c245af3af4b00325a5b78ef70eb6d`이다. incoming 병렬 guard/body 준비·크기 사전 검사·nonSafety main-delta 최적화·custom-as-EXTRA·명시적 none/skip-reason 정책을 보존했다. literal `full`을 EXTRA로 바꾸는 incoming 정규화는 이 RED checkpoint에 의도적으로 남겼다.

fixture 예외 환경변수를 해제한 실제 CLI 시험은 canonical FULL 대신 `[['pkg/test'], ['full']]`을 실행해 AssertionError로 실패했다. setup·import·수집 오류가 아니며, double-quiet 출력의 정확한 FAILED node와 NEW1을 근거로 삼는다. 출력되지 않은 pytest 실패 개수·시간 요약을 인용하지 않는다. Root가 승인한 한 줄 수정 tree `dc798da56170db7e03c3fb00e021d7ea7b6a2b64`를 local source commit `877cf55c013c8747322822973ba996aed83ff66a`로 보존했다. 두 준비 결과의 적격성·fresh guard clone·process witness·fresh-only report·FF 전 차단은 그대로 유지된다.

| 실행 | source commit | 실제 결과와 판정 |
|---|---|---|
| `red-integration737-cli` | `d2217085fe` | 선택한 CLI node FAILED, NEW1/known0/flaky0, official·outer·known exit1 |
| `green-integration737-cli` | `877cf55c01` | CLI 3 PASS/0 SKIP, official·outer·known exit0, NEW0/known0/flaky0 |
| `green-integration737-tools` | `877cf55c01` | 기존 owner 11파일 336 PASS/0 SKIP, official·outer·known exit0, NEW0/known0/flaky0 |
| `green-integration737-selectors` | `877cf55c01` | selector·실제 architecture owner 5파일 299 PASS/0 SKIP, official·outer·known exit0, NEW0/known0/flaky0 |

PASS 개수는 quiet 진행 행의 문자만 세었으며 CLI 3개는 336개와 겹친다. 고유 시험 수로 합산하지 않는다. 모든 raw·runner·known 판정은 `%LOCALAPPDATA%/Temp/rosy-land-explicit-full/` 아래 표의 별도 폴더에 보존했다. 각 새 실행은 qualified-labs wrapper의 fresh disk 기준(30 GiB 이상·사용률 90% 미만)을 통과했고 공식 runner의 자원 기준에 따른 직렬 실행을 허용했다. 실제 Chromium·전체 FULL·착지·게시·장치 수용 근거는 아니다.

원본 파일의 바이트는 다음 SHA-256으로 결속한다. 경로는 위 네 실행 폴더 아래의 `runner.txt`, `run-1.txt`, `run-1-known.txt`이다.

| 실행 폴더 | runner.txt | run-1.txt | run-1-known.txt |
|---|---|---|---|
| `red-integration737-cli` | `sha256:224dbd6ead0a05050848daa88777cff93a531a3004a9648e942b469f5771aac5` | `sha256:f14952e710dfc5f4b45899b3d7bee7b7230ae38c9355da3cccef6d1e995d45d5` | `sha256:b6108368b4c82b9b64bc5ec4dd5fa690fe5fa53486720ca0e12b9ff07dbab705` |
| `green-integration737-cli` | `sha256:6620001d307a1182694197c16ef74ac01cfe83d68f005c9a2a598d06812ef547` | `sha256:6c0814ba8c6cf2e8fb16fda6038d696bf095f2800fca995e46f526ceadf7f4c6` | `sha256:c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e` |
| `green-integration737-tools` | `sha256:ee0609dfb12dc23c273b54773c8036a5a8bdf442076238398f6dab53fd55d6f4` | `sha256:5372354aa954eda6518b1aa2640a5eac7a6a88257195b9f9f2a1bb3c98aa74e2` | `sha256:c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e` |
| `green-integration737-selectors` | `sha256:71109d1a46c6165cebf7cf73160376cae01a3d01857a738a692d0d0b9d3af7f7` | `sha256:118a27b7e4d5b2060a42ec968cfb89d8178b357cbc35e25e826e2d78e6f4f73a` | `sha256:c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e` |

충돌하지 않은 incoming 13경로는 main737과 동일하며 기존 Tool1 선택 시험 및 incoming 선택 시험 2개, 양쪽 journal 내용을 보존했다. charging 시험의 shared body AST는 동일하다. `lifespan`·`shutdown_UNDOCKING`은 `test_station_camera_pipeline_lifespan.py`, `continuous`는 `_continuous.py`의 wrapper가 호출하며 timeout·assertion은 바뀌지 않았다. 이 사실은 과거 charging 실패가 해결됐다는 뜻이 아니다.

source fix까지 D766 20커밋 범위가 통과했다. 최종 문서 커밋 뒤 범위·generate/lint/diff·정본 scan·공식 dry-run·clean 상태는 외부 후속 handoff에 별도로 결속한다. 더 최신 main과의 통합·공식 FULL·게시 SHA 기능 포함은 Root의 후속 관문이다. CE: 이 통합에서 새 교훈은 추가하지 않았다. 기존 두 교훈을 적용했고 새 정규화 반례와 최소 수정은 코드·회귀 시험·위 RED/GREEN으로 설명된다.
