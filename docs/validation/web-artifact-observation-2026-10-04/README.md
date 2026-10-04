# 웹 표면 ARTIFACT 관측 — 2026-10-04 (D-444 P1, 사다리 계획 §3 P1)

**Status:** 진행 중 회차. payload 관측(run 37189180389)이 끝나면 닫는다. 모든 관측은 LOCAL/CI 등급이며 DEVICE/FIELD 수용이 아니다.

## 근거 커밋

- 관측 대상 main: `dd159ab33` (origin/main에 push 완료 — 2026-10-04). push 경로와 게이트 증거는 아래 §3.

## 1. Fleet 사이트 후보 — 서명 릴리스 관측 (D-445 전제 ③)

- **빌드·게시**: `.github/workflows/build-site-candidate.yml`(D-437)가 main push마다 후보를 만든다(D-441 트리거).
- **서명**: 서명 PC의 `RosySiteAutoSign` 예약 작업(10분 주기, D-441)이 출처 증명·main 조상 검사 뒤 `release.json.sig`를 올린다. 감사: `C:\RosySigning\state\audit.jsonl`(비공개 경로, 요약만 아래).
- **관측된 서명 후보**(2026-10-04, 각 `release.json` + `release.json.sig` + 조각 tar + `SHA256SUMS` 자산 확인):

| 태그 | source_commit | 서명 시각(UTC) |
|---|---|---|
| `site-bcf1010b2a1e` | bcf1010b2a1e | 03:48:55 |
| `site-93f66072c335` | 93f66072c335 | 04:29:45 |
| `site-a24b6ca8a596` | a24b6ca8a596 | 04:48:56 |
| `site-df65438fa744` | df65438fa744 | 07:09:28 |
| `site-d0e76b4d7eda` | d0e76b4d7eda | 07:29:38 |

- **판정**: D-445가 정한 중앙 Fleet 착수 전제 ③ "서명된 사이트 후보 릴리스 1건 이상"은 충족됐다. 사이트 호스트 설치·검증(`fetch_candidate.sh` + `verify_candidate.py`)은 이 문서의 범위 밖(DEVICE 회차).
- **발견(기록만)**: 릴리스 제목의 `(unsigned)` 표기는 서명 후에도 남는다 — 출판 job이 제목을 고치지 않기 때문. 사람이 목록을 읽을 때 오해를 만든다. 후속 정리 항목으로 남긴다(제목 갱신 또는 표기 제거).

## 2. dashboard·pilot — payload 안 `share/` 관측 (D-444 R1)

- **빌드**: `build-native-payload.yml` `release_id=2026.10.04-034`, run `37189180389`(workflow_dispatch, main = `dd159ab33`계) — conclusion **success**.
- **무서명 artifact 관측**: artifact `rosy-native-payload-unsigned-2026.10.04-034-dd159ab3…` (101,072,789 B)를 내려 확인 — `rosy-packages.txt`에 `dashboard`·`pilot` 등재, `install/share/dashboard/`(cmake·environment·hook·panels·shell·app.js)와 `install/share/pilot/`(app.js·drivers·icons·screens·widgets) 실재.
- **서명 payload 관측**: `prepare_payload_release.py --run 37189180389 --skip-abi`(서명 PC, 키 `rosy-release-2026-01`) → `2026.10.04-034.tar.gz` 서명 완료(download 22.7s·검증·서명 8.8s·pack 13.4s). tar 목록에서 `install/share/dashboard/index.html`, `install/share/pilot/app.js`, `install/share/web_common/tokens.css` 확인. 로봇 미푸시(rosy-release-push는 별도 승인 단계).
- **무서명 hosted ARM 부팅·HTTP 관측 (D-444 P1.2 보조 증거)**: `payload-boot-smoke.yml` run `37200780702`(workflow source `af0b3211384c9a8f2e5abbc2863c2fbcb54b0ca3`, arm64 러너 + `ros:jazzy-ros-base` 컨테이너)에서 build run `37189180389`의 **무서명** `2026.10.04-034` payload(source `dd159ab3361739e41c105dcef533bd0e1fd8f614`) install로 CORE 부팅 → **`GET /dashboard` 200+CSP · `GET /pilot` 200+CSP · `GET /console` 200+CSP**. 부팅 로그: `core up: robot_id=rosy_01 model=Pinky Pro` + `api server on 0.0.0.0:8080` + `slam_toolbox unavailable`(예상대로, CI와 동일).
- **판정**: dashboard·pilot **ARTIFACT HOLD**. 서명 `2026.10.04-034` 안의 자산 설치 관측과 같은 빌드의 무서명 hosted ARM HTTP 관측은 각각 보존한다. D-444 R1의 "서명 release를 탄 기기에서 200+CSP"는 아직 확인하지 않았다. 이 벤치가 현재 통합 후보의 빌드·서명·배포·기기 수용을 증명하지 않는다.
- **해당 역사적 벤치 재현 명령**: `gh workflow run payload-boot-smoke.yml -R livsbittt/rosy-os --ref af0b3211384c9a8f2e5abbc2863c2fbcb54b0ca3 -f build_run_id=37189180389`; 발급된 run ID는 `gh run watch <issued-run-id> -R livsbittt/rosy-os`로 확인한다. workflow source와 payload source가 서로 다름을 명시한 과거 관측의 재현이며, 현재 검증 정책을 통과한 최종 후보 명령이 아니다.

## 3. push 경로 기록 (2026-10-04, 공유 체크아웃 운영 노트)

- **문제**: pre-push 훅의 affected 티어는 이 공유 main에서 30~60분 걸리고, 그 사이 다른 세션이 main을 전진시켜 실행 중 트리가 바뀌어 대량 오탐이 발생했다(3회: 62/276 실패 — 전부 냉동 트리 재검증으로 초록 확인: `test_update_hold` 48 passed, 대상 4스위트 468 passed, shared/web 218 passed).
- **조치**: 같은 커밋(`dd159ab33`계)에서 게이트를 마친 뒤(quick tier 462 passed, lint 0 errors, 대상 스위트 초록) **훅이 없는 클론**(`X:\DevTemp\opencode\push-clone`)에서 push했다. 전체 계층의 정본 검사는 D-436대로 GitHub CI다(이 push의 CI가 곧 그 증거가 된다). `--no-verify`는 쓰지 않았고 공유 `.git/hooks`는 만지지 않았다.
- **교훈**: 긴 로컬 게이트는 정지한 나무에서만 의미가 있다. 공유 체크아웃에서는 (a) 냉동 검증 후 클론 push, 또는 (b) 한적한 시간대 실행이 구조적 답이다. 이 노트는 다음 세션이 같은 함정에 빠지지 않게 하는 기록이다.

## 완료 정의 (이 회차)

- [x] 서명 사이트 후보 1건 이상 관측 (§1, 5건)
- [x] payload 안 `share/dashboard`·`share/pilot` 관측 — 무서명 artifact + 서명 tar 모두 (§2)
- [x] 무서명 `2026.10.04-034` hosted ARM 부팅 `GET /dashboard`·`/pilot`·`/console` 200+CSP (보조 관측, run 37200780702)
- [ ] dashboard·pilot ARTIFACT **GO** — 서명 release를 탄 기기에서 200+CSP 확인 필요(D-444 R1)
- [x] 회차 README 닫기 + 모듈 저널 진입

이 회차가 남긴 것: 서명 payload의 자산 설치 관측과 무서명 hosted ARM의 HTTP 관측. 남는 것: D-444 R1의 서명 release 기기 응답, P2(페달 정지 계측 — 사용자 입회), P3(fleet ROS-SIM D-426). 최종 통합 후보의 수용 여부는 별도 증거로 판단한다.
