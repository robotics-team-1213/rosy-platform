# Learning·Isaac 공개 반영과 실제 서명 배포

2026-10-25 관측. [이전 소비 화면·설치기 검증](../learning-conveyor-release-2026-10-25/result.md)과 [기존 접촉 실행](../isaac-pinky-conveyor-roundtrip-2026-10-25/result.md)을 잇는 후속 기록이다. 이 기록의 배포는 모델 PC의 코드·Learning 서비스 활성화다. 로봇 명령이나 learned policy 승격을 수행하지 않았다.

## 공개 소스와 검증

| PR | 공개 merge commit | 새로 실행한 검사와 실제 결과 |
|---|---|---|
| [201](https://github.com/robotics-team-1213/rosy-platform/pull/201) · Learning 산출물·private SIM 설정 보존 | commit `bcad6a076ed1d0d42ee2b211b232a11e85653264` | API·명시 Chromium 26 PASS, 설치기 48 PASS. 최종 pre-push 519 + 9,300 PASS / 1,148 SKIP / 0 NEW. PR CI 40178085593 및 merge CI 40178966788 성공 |
| [202](https://github.com/robotics-team-1213/rosy-platform/pull/202) · import 보고서 | commit `02c80a7c20cc10819fc25f0effe51c52192cc334` | 원격 289 PASS / xacro 1 SKIP. 최종 pre-push 519 + 334 PASS / 1 SKIP / 0 NEW. PR CI 40179621531 성공 |
| [203](https://github.com/robotics-team-1213/rosy-platform/pull/203) · bounded run manager | commit `e231f97b06766661a96cd0e3530a7864fe928fd9` | 원격 359 PASS / 1 SKIP. 최종 pre-push 519 + 421 PASS / 1 SKIP / 0 NEW. PR CI 40180166004 및 merge 전체 CI 40183287809의 20개 잡 모두 성공 |
| [204](https://github.com/robotics-team-1213/rosy-platform/pull/204) · Fleet 비동기 화면 관측 | commit `e7870d279ba918d3c6f7ac211d46a72b65cd0cac` | 최종 head 명시 Chromium 23 PASS / 0 SKIP / 0 NEW. pre-push 519 + 4,320 + 6,202 PASS / 516 SKIP / 5 subtest PASS / 0 NEW. PR CI 40182103687 성공 |
| [205](https://github.com/robotics-team-1213/rosy-platform/pull/205) · contact producer·판정기·기존 증거 | commit `f2868aab3281dc0f071595f0e7257959a740a25a` | 원격 365 PASS / 1 SKIP. 최종 pre-push 519 + 613 PASS / 1 SKIP / 0 NEW. PR CI 40183526370 및 merge 전체 CI 40184154647의 20개 잡 모두 성공 |
| [206](https://github.com/robotics-team-1213/rosy-platform/pull/206) · remote receipt·snapshot CLI | commit `9cbc1f0598496b72807d92ec9c7f8d81b9b4ed09` | 원격 CLI·Isaac·HTTP 399 PASS / 1 SKIP. 최종 pre-push 519 + 630 PASS / 1 SKIP / 0 NEW. PR CI 40184423341 및 merge 전체 CI 40184908139의 20개 잡 모두 성공 |

각 PR은 작성자와 다른 읽기 전용 에이전트가 최종 base/head를 검토했고, 게시 head 변경 때 재검토했다. 원격 시험은 커밋된 SHA에서 실행하고 각 로그를 `test/known_failures.py`와 비교했다. SKIP은 실행 성공으로 계산하지 않았다. 기존 a46 소스·시험·동결 기록은 좁은 변경으로 공개 main에 반영했으며, 로컬 main 전체를 공개 main이나 운영 payload에 합치지 않았다. 사용자 승인과 서버 설정에 따라 merge commit으로 병합했다.

CI 실패 이력도 보존한다. PR202 merge CI 40179928359의 Fleet 화면 실패는 fake-clock 뒤 API 응답이 DOM에 반영되기 전에 즉시 숨김 상태를 검사한 경쟁이었다. `operations/fleet/test/test_console_card_trips_browser.py`의 같은 세 숨김 조건을 Playwright `expect(...).to_be_hidden()`으로 기다리도록 고쳤다. 제품 동작·타임아웃·임계값·skip·quarantine은 바꾸지 않았다.

PR204 merge CI 40183280676에는 별개 G1 지연 실패가 있다. `test/test_platform_g1_timing.py:212`의 0.25초 bound에서 ReleaseBarrier 24회 p50=0.003060초, p90=0.006275초, p99/max=0.422716초였다(잡 121138812835, 1 FAILED / 3,001 PASS / 349 SKIP). 동일 G1 소스·시험의 후속 e231 전체 CI에서는 해당 잡이 3,002 PASS / 349 SKIP으로 통과했다. 이 시간은 직접 dispatch와 SQLite transaction·스케줄링을 포함하므로 네트워크 RTT로 해석하지 않는다. 원인 분리는 미해결이며 통과한 후속 결과로 원래 bound 초과를 지우지 않는다.

## 실제 운영 배포: 새로 실행한 검사

공식 `deploy/site/rosy_model_code.py`로 **sequence 41**, source **`e231f97b06766661a96cd0e3530a7864fe928fd9`**를 기존 등록 키로 서명했다. 신규 키 생성·교체 없이 private key에서 도출한 공개 키와 운영 trust key의 SPKI-DER SHA-256 일치를 확인했다. 환경 지문은 `24eb783be68765fa71e753d940f1b93c2845ad721d3d96a19c9e47e838034933`이다.

뒤의 PR205·206은 SDK/CLI/문서 경로다. e231, f286, 최종 remote CLI head112f7e3의 `model_code_layout.CODE_PREFIXES` payload inventory는 경로·mode·blob 732개가 같았다(SHA-256 `c18f101d4a16011eab4be59957898e1522a1bd46216af98c2dd5e7960d0d849b`). 전체 CI가 끝난 e231을 배포 소스로 명시했으며 9cbc가 배포됐다고 주장하지 않는다. SDK producer는 별도 고정 source7d0으로 유지했다.

| 전달 산출물 | 크기 | SHA-256 |
|---|---:|---|
| archive | 7,147,520 B | `25112281fed85310233eb262ec5641da6856419a87e0f5a6d83442e93f14b0b5` |
| release.json | 285 B | `d9f25d0a3759c88d5045a32bd4513005033e2524bbf45ae77390286473d4918f` |
| signature | 166 B | `1dfaa6b43e7a191c3ce9321dae2f1a9bcf9aec9e531d58abdbeb33e04e487417` |

등록 키 signature·archive를 검증하고 새 전용 inbox에 동일 바이트를 전달한 뒤 READY를 마지막에 발행했다. 기존 GPU 시험 중에는 정상 hold를 존중했고 중지·lock 강제 해제를 하지 않았다. idle 확인 후 기존 `rosy-model-code-update.service`가 sequence41/sourcee231을 `applied`로 수용했다. 환경 설치·업그레이드 없이 기존 signed 경로를 사용했다.

공식 `auto_review_release.py`와 `install_review_release.py`의 정확한 e231 blob을 버전이 붙은 운영 도구 폴더에서 사용해 `model-code-41-e231f97b0676`을 활성화했다. 기존 unit에서 달라진 실행 인자는 `--sim-config` 추가뿐이다. 새 unit SHA-256은 `ec904599772dca242566d3a470c62b3800ae4ed5b5fa90bd2bd095f1c30e50e9`이다. private SIM 설정은 owned regular file·0600·고정 digest를 확인했다. 기존 unit/current backup과 공식 rollback 경로를 보존했다.

별도 읽기 전용 검토자가 **19:39:18 KST** 운영 상태를 독립 재확인했다.

- 서비스 active/running(19:38:26 이후), 실제 process argv와 unit 일치, DropIn 없음, `--sim-config` 존재.
- accepted model source·sequence·review current가 모두 e231/41에 일치. pending·failed 없음.
- `/api/workspace` 401, `/api/accounts/options` 200 및 account 활성화, `/accounts`와 `/learning/sim` 200. 인증 경계를 유지했다.
- 활성화 이후 journal 오류 패턴 0. 실제 배포된 `sim_web.LocalRuns`로 기존 run 조회와 6개 산출물 크기·SHA-256·MIME를 다시 검증했다.
- OMX center를 query-only로 조회해 배포 전후 모두 **0 datasets / 0 runs**를 확인했다. 학습이나 데이터 수집이 발생했다고 해석하지 않는다.

## 기존 SDK 관측을 재사용한 검사

새 Isaac SDK 실행은 하지 않았다. 별도 깨끗한 producer source `7d0cfcd6e94fd0181e324319e12c274f3e2f3890`, run `36041b241ee25366986bb3a6262ba0be`의 기존 실행을 다시 검증했다. 실제 배포된 조회 경로에서 FINAL/SUCCEEDED, stage=contact_roundtrip, task_success=true를 확인했다.

접촉 보고서 662,173 B의 SHA-256은 `b91a359bc461a110d86d30e44f1bbd10a69bfb072cb388d10672c7336bdc0568`이다. 단계 PNG 다섯 개는 각각 142,932 / 93,560 / 80,600 / 81,217 / 93,219 B이며 manifest와 실제 파일의 크기·hash·MIME가 모두 일치했다. 초기 검토에서 원본 이미지 다섯 개를 직접 보고, 보고서에서 판정기를 재계산했다. 3,624 step·30.200001575초의 결정론적 CAD IK 실행은 정지 합성 Pinky 적재면 proxy↔정지 컨베이어와 단일 18 mm/0.05 kg 물체의 접촉 왕복을 지지한다. 초기화 후 attachment·pose write·외부 도움 없이, lift 중 지지 접촉 소실과 양쪽 finger 접촉, 최종 정착 오차를 관측했다. 상세 수치와 조건은 원래 동결 기록을 따른다.

## 확인하지 못한 항목과 남은 완료 기준

운영 로그인 세션을 이용한 Learning 화면 전체 흐름은 확인하지 않았다. 일관된 SQLite backup과 private SIM 설정 복사본으로 별도 loopback GET-only 화면 검사를 시도했지만, `review_app.make_server`가 `collaboration-bound workspace requires its account configuration`으로 시작을 거절했다. 보호 검사를 우회하거나 복사본의 인증 바인딩을 지우지 않았다. 이 시도는 브라우저 성공·스크린샷 증거가 아니다. 공개 head의 명시 Chromium 회귀와 운영 HTTP/산출물 검증을 운영 로그인 화면 관측으로 바꾸어 쓰지 않는다.

| 우선순위 | 남은 작업 | 완료 기준 |
|---|---|---|
| P1 | 로그인한 실제 Learning 화면 수용 | 정상 계정 경로에서 같은 run·보고서·PNG 5개 표시와 링크, 계정 권한·읽기 전용 동작을 관측. 기존 사람 정답·운영 세션을 시험 데이터로 사용하지 않음 |
| P1 | G1 지연 초과 원인 분리 | 고정 revision에서 scheduler·SQLite 비용을 구분한 측정으로 원인을 설명하고 원래 bound를 보존한 검증. 한 번의 후속 통과를 해결로 취급하지 않음 |
| P2 | 동기화 시연 수집 | 기존 Episode 계약의 상태·행동·카메라 시계열, 원본 provenance·해시와 검토를 갖춘 실제 데이터. train/eval을 에피소드 단위로 독립 분리 |
| P2 | 학습과 독립 정책 평가 | 검토 데이터에서 ACT 학습, 별도 프로세스 재적재, 정확한 policy revision으로 독립 SIM 과제 실행·실패 포함 평가. 데이터·정책 revision·환경·seed·receipt 결속 |
| P3 | 물리 수용 | 카메라 보정, 팔·Pinky 적재면·컨베이어 실측, 장치 보정과 승인된 실물 수용. 이동 컨베이어·완전한 Pinky 모델·현장 성공은 별도 증거 필요 |

접촉 JSON과 PNG는 동기화 Episode가 아니며 learned policy revision이 없다. 데이터나 사람 정답·정책 성공을 합성해 남은 항목을 완료 처리하지 않았다. CE: 해당 없음 — 기존 drive-mode 교훈을 공개 보존·재사용했고, 새 구현·시험·로그 외에 추가할 검증된 해결 교훈은 없다. G1 지연 원인은 미해결이다.
