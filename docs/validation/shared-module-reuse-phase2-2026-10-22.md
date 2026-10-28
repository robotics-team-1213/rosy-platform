# 공유 모듈 2차 소프트웨어 검증 — 2026-10-22

공통 전송 reader를 먼저 검증·로컬 main에 반영한 뒤 기존 D-841 구현과 camera-peer 소비자를 통합했다. 이 기록은 아래 커밋의 시험 증거이며 원격 push·GitHub CI·배포·실물 수용 완료를 뜻하지 않는다.

- Shared reader Git commit: 46fb9075bd789c0fa4e63e0ff0d374e64f683a7b
- Consumer Git commit: 35a98bc84dc8d33b4c75d467a4e862d6a97ec5d5
- Port local main Git commit: 1beb748d1077ae7648999913ceb5170c4d15472a
- Vault local main Git commit: 18a93a9a3305cb44fa8bf8c03a13bcc20e891a6f

## 범위와 결과

D-845의 readResponse는 공통 전송의 취소·timeout·정리 수명 안에서 서비스별 해석을 수행한다. reader 미지정 호출의 기본 JSON/204/blob은 보존한다. camera-peer는 호출별 life와 헤더 스냅샷을 사용하며 401/403/404에서 본문을 읽기 전 정리, 엄격 JSON, 종료 후 응답 무시, 단일 POST를 유지한다.

- 공유 Node: request 31개·전체 transport 52개, skip0. 이전 소스에 새 회귀 7개가 RED였다.
- 공유 공식 원격 focused: 128 passed/skip0.
- 공유 명시적 lab FULL: 소유 affected_tests.lab_full_invocations의 CI20+root1+추가등록2를 공식 remote_pytest.py에 전달했다. 23 invocation 모두 exit0, 각 known_failures.py 비교 exit0. 실행별 중복 포함 30,661 passed/2,028 skipped/0 failed이며 고유 시험 수가 아니다. 독립 검토가 raw 해시·집계·등록 경로 누락0을 확인했다.
- 공유 공식 착지: 영향1201 passed/3 skipped. opt-in Chromium 네 묶음은 398 passed, 361 passed/2 failed, 235 passed, 269 passed였다. 두 실패는 액션 탭 초점과 모바일 지도 버튼 안정성 검사이며 각각 단독1 passed로 LOAD-FLAKY 분류됐다. native land exit0, 로컬 main 반영 완료. 이를 안정성 문제가 없다는 증거로 확대하지 않는다.
- 소비자 실제 파일·기존 Node loader: 전환 전 8 passed/1 expected failure. 전환 후 새9+기존2 통과, 전체 Fleet Node363 passed/skip0.
- 소비자 공식 focused: ROSY_RUN_BROWSER_TESTS=1, camera-peer 브라우저·disabled poller·shared transport·두 learning 경로 회귀·release/provenance/harness 가드 220 passed/skip0/exit0.
- 독립 최종 코드 검토: Critical/Important 없음. 기존 Learning 코드·시험, 동결1차 validation, 정확한 provenance tuple은 이전 보존 커밋과 blob 동일. D-841이 들어와 부재 gap 한 행만 제거했다.

pytest 본문에는 요청 SHA가 포함되지 않는다. 커밋 연결은 공식 runner 호출의 --sha·출력 및 세션 실행 기록에 근거하며, 아래 로그 해시만으로 실행 SHA를 독립 입증한다고 주장하지 않는다. 실제 브라우저 opt-in 결과와 기본 FULL의 건너뜀을 구분한다.

## 원본 로그

로그 root: 외부 <TEMP>/rosy-shared-reuse/phase2/. 첫 stale-index STOP과 중단한 부분 실행도 별도 attempt 디렉터리에 보존했다. 아래는 완료 실행의 요약이다.

| 상대 로그 | 종료 요약 | SHA-256 |
|---|---|---|
| consumers-focused/run-1.txt | 220 passed, 39 warnings in 34.44s | 13eb645be4cde346686dcce48fb184bafda3fa2600c046cefd0d6b467206835a |
| reader-full/run-1.txt | 111 passed in 2.61s | 490d27fd2feeddc0eaa63882533497f3bdaa4e56c6fe75a11cf56a33dd9e71f1 |
| reader-full/run-10.txt | 6 passed, 2 skipped, 12 warnings in 10.92s | dd47d1b1c3a351f4ca107f68e28766650c57edd32f1ce856a8584b0ca7fae055 |
| reader-full/run-11.txt | 3554 passed, 113 skipped, 62 subtests passed in 141.49s (0:02:21) | 18aad9498f71081ec127aaada8618f64de55f4e972f05c25086989f14dde9bd9 |
| reader-full/run-12.txt | 6131 passed, 326 skipped, 2 warnings in 710.15s (0:11:50) | 63521cafe4fa46280920e0fa1f61e9027365376b605eeeed02c6c26cc10d7122 |
| reader-full/run-13.txt | 47 passed, 32 skipped in 4.93s | 547c2a52a932f65f7b2d9c025f19c66f36d724ce4859a93fed54865a18f32c8f |
| reader-full/run-14.txt | 736 passed in 49.08s | 4ac4e63eefa10ac2fb8a96a73c7c52c10742651c2aec130ab334568c63e33c04 |
| reader-full/run-15.txt | 155 passed in 0.49s | 47d97d34c094536a10e8c57d5670376531c541efd354a7a023c5aaf3cbfae15f |
| reader-full/run-16.txt | 121 passed, 2 warnings in 4.63s | 97645e26e86481795e18572d2a10c485810a1b7ee3928c4865a3c746a62da957 |
| reader-full/run-17.txt | 9 passed in 1.51s | 258f65e9e14fdf4d7f6788a020fbe4297fabed9b47b9357617e5ea862496038e |
| reader-full/run-18.txt | 25 passed in 0.78s | ef44ddf3b3742b621b0e6fbd6c731c8b4869029cc5aba6d3d703166d4b87ce6a |
| reader-full/run-19.txt | 328 passed, 4 skipped in 9.20s | 3c0b9e71b28af421a681cc863abcfedcacb74a5156d1835c41fecd748d04c5bf |
| reader-full/run-2.txt | 133 passed, 16 skipped in 2.72s | 761b3bed79833849733ab0e23fda176c634bb47cdc82b8e3b8bd4d9061ed7b92 |
| reader-full/run-20.txt | 473 passed in 0.93s | d519d48dd559e22bbf2ca68e81540a665320a1d97084d5595ebebfd543ec8972 |
| reader-full/run-21.txt | 9345 passed, 1125 skipped, 56 warnings in 696.06s (0:11:36) | 72bb5352eac200a4a198989030cb7baabd03f6bbde726b7d0879f2d2606bcfe9 |
| reader-full/run-22.txt | 1783 passed, 296 skipped, 2 warnings in 56.77s | 50b55694a6c30515510eed28e7262048c39c85c23cbf3cc73a5ea96117538bd6 |
| reader-full/run-23.txt | 188 passed, 13 skipped, 2 warnings, 25 subtests passed in 6.61s | 0c9c16e128b2d362960feb0b0fda9427187bd2d05b722c966b97f14ca7d0c1bb |
| reader-full/run-3.txt | 6 passed, 6 skipped in 0.69s | c00e4ca4ad6e896266b934d3ad038a5465b9a84ea623aef1c2b223aa98f7e197 |
| reader-full/run-4.txt | 211 passed, 3 skipped in 2.00s | 6f7e20e2c2b8a27ac0d143098cc0e39dd9397a3cc05d96b28021079566efb248 |
| reader-full/run-5.txt | 21 passed, 28 skipped in 0.47s | a719f2ca8b44b98ca51f5e17ff4ab97d7ec9beaa2db0cc5e6da54541b67a4e98 |
| reader-full/run-6.txt | 3 passed in 0.53s | b5f1f6e54a22ad81e1d3dcd63943805f7bdb47c841f72460bab06b24cc515e52 |
| reader-full/run-7.txt | 4 passed in 0.69s | be1beeb602babf721d1a7cc7002e5f7626cf299d04ba8da384eb5ec09769a25e |
| reader-full/run-8.txt | 12 passed in 0.36s | b6ef7e621325b38610a185c95c7b41eecc19fbd6777487bed04b9d4b5aa88113 |
| reader-full/run-9.txt | 7259 passed, 64 skipped, 12 warnings, 5 subtests passed in 474.34s (0:07:54) | 12c861caffbf0a973878b83d48b56951ee1dfce3d14a39f0bb62dbf035cc4fc5 |
| reader-landing-attempt3/refactor-shared-response-reader/alone-1-4-1.txt | 1 passed in 0.98s | a33286c6a594617561f0e2dcac2a49e43285cbd1cba8a7c7c6e90fb2dbe961c8 |
| reader-landing-attempt3/refactor-shared-response-reader/alone-1-4-2.txt | 1 passed, 2 warnings in 3.76s | b0e1eca1fdec7d5d54377bda55ca9e07a21b82ae3f1cfe72bbaaa8de4d867f78 |
| reader-landing-attempt3/refactor-shared-response-reader/run-1-1.txt | 1201 passed, 3 skipped, 39 warnings in 100.97s (0:01:40) | 71e5aef105de2789fbb7f9b8a0f39315223117997bcbe7cccf38fced94c2ebed |
| reader-landing-attempt3/refactor-shared-response-reader/run-1-2.txt | 269 passed, 2 warnings in 588.13s (0:09:48) | e345573db73ab5e9b233e8a12e6de068f52034f0acb52ef0f55b1dbe5c2b2503 |
| reader-landing-attempt3/refactor-shared-response-reader/run-1-3.txt | 398 passed, 2 warnings in 840.26s (0:14:00) | 2a3a257c6b126b0f113dd904f124926ad7b0cdefb2e4c18be013a73e8ddcc627 |
| reader-landing-attempt3/refactor-shared-response-reader/run-1-4.txt | 2 failed, 361 passed, 2 warnings in 802.61s (0:13:22) | 053d9c972950a19b9371d3855dc420b276525b6b5b443db79b833ad11de3fd7c |
| reader-landing-attempt3/refactor-shared-response-reader/run-1-5.txt | 235 passed, 2 warnings in 618.96s (0:10:18) | 1ddc2821ab8e2fbe326cb17fbab811b9bc62ac357e172ecbf6cca7dd7421fef9 |

## 남은 수용 경계

소비자 통합의 공식 최종 착지는 후속 land 실행 기록으로 확인한다. 이 문서가 묶는 소비자 소스 검증은 위 Git commit이다. 기존 1차 동결 기록은 수정하지 않았다.

Port는 실제 producer에서 화물/목적지·팔 전체 퇴피·최종 하역 사실을 공급하는 운영 어댑터가 아직 없다. Port의 docs/observation-acceptance.md에 소유 경계·신뢰·원본 시각/identity·attempt/revision·거절 시험과 실물 수용 선행 조건을 명시했다. sim_model_pose나 그리퍼 OPEN을 이 사실로 합성하지 않는다. Port/Vault 기존 실제 HTTP 증거의 source pin과 분리 환경 조건은 1차 기록을 따른다. 새 HTTP·실물·배포 시험으로 부풀리지 않는다.
