# D-649 온라인 배포 수용

확인 시각: 2026-10-11 09:44 UTC. 배포 source `2891e10061233b1067fd315cdcbad78bdb1b5d46`. 이 문서를 추가하는 후속 문서 커밋과 실제 설치 소스를 구분한다.

## 소스·릴리스 관문

- 80개 원본 이동은 source `5da31e05cb89`로 main 통합·발행했다. 최종 영향 시험 11,370 passed, zero NEW. 설치 identity와 Safety 책임의 독립 검토 기록은 [result.md](result.md), [safety-review.md](safety-review.md)에 있다.
- 공용 tooltip의 정상 클릭과 hover 보완은 [독립 UI 검토](ui-review.md)를 거쳤다. 실제 Chromium·구조 56 passed, 통합 608 passed / 435 skipped, 문서·계약 283 passed, 최종 pre-push 289 passed. 건너뛴 시험은 실제 브라우저 증거와 구분한다.
- 최종 source의 [CI 38128614393](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38128614393): 14개 시험 그룹과 `ci-result` 모두 성공. ROS 빌드·노드 기동, CORE, 센서, Safety, Fleet 브라우저와 Gazebo를 포함한다.
- [Site 후보 빌드 38128614377](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38128614377), [Android 38128614388](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38128614388)도 성공. 기존 등록된 자동 서명 작업이 `site-2891e1006123`에 서명을 첨부한 뒤 기존 updater로 적용했다.
- 실패한 source `53c557136957`와 `5da31e05cb89` 후보는 적용하지 않았다. 모델 sequence 20·21은 READY 없이 남았으며, 다른 소스로 번호를 재사용하지 않았다.

## 설치·실행 readback

| 대상 | 실제 수용 증거 |
| --- | --- |
| Site PC | candidate와 updater의 installed commit이 위 source와 일치. 09:43:54 UTC installed. Fleet·Vision·Proxy의 실제 실행 이미지가 해당 commit tag이며 셋 모두 healthy. 등록된 검증기가 서명·이미지·기능 관문을 통과했다. |
| 모델 PC | 등록된 키로 서명한 sequence 22를 환경 fingerprint 일치 확인 후 적용. state result `applied`, current release와 source 일치. 신뢰된 controller 설치 후 등록 config bytes·키를 유지했다. Review current가 `model-code-22-2891e1006123`, 실제 process와 CWD가 `learning/curation/perception/review_app.py`를 실행한다. |
| AI PC | 기존 배포 스크립트의 `ROSY_REPO`로 실제 전용 Git 저장소를 선택했다. 새 detached source의 `operations/situation`에서 서비스 active와 실제 PID/CWD를 확인. Fleet API heartbeat의 build commit이 `2891e1006123`, state present, age 4.85s였다. |

모델 source archive sha256 `45ee1239e374c10b83ca31b355c99800b8770babd4a08ebb98980b343cbc825e`. 환경 fingerprint와 등록된 서명은 대상에서 검증했으며, READY는 전체 CI 통과와 controller 설치 후 마지막에 올렸다. 환경·데이터·venv를 재구성하거나 실행 중 학습을 중단하지 않았다.

Site의 `/console`, Console JS·styles·site-map-model, `/common/ui.js`는 strict TLS로 읽은 실제 HTTP 200 bytes의 sha256이 해당 source Git blob과 일치했다. Console CSP의 self script 정책과 frame-ancestors none도 확인했다.

## 보존과 수용 범위

- 등록된 `rosy_40`, `rosy_41` 두 대는 그대로 offline. 카메라 등록 `ceiling_north`도 유지했다.
- 활성 Site 지도 v5의 activated_at과 전체 JSON sha256 `a77b564cbfa2e3d276f4f3fcaccfe66db1345bea4980ed3afc2fc9987101cf86`이 배포 전후 일치했다. `map_v2_fleet` 출처를 다른 지도로 대체하지 않았다.
- AI 모델 프로필 `qwen3-vl:8b-instruct@0533d74300e4:d619-v5:7cd1d825`, owner available을 유지했다. 새 모델 활성화나 실행 권한 변경은 하지 않았다.
- Review 네 화면의 63·43·53·8개 frame identity와 class set·map reference fingerprint가 배포 전후 일치했다. 별도 고정 평가 unit의 sha256도 같았다. 독립적으로 고정된 화면은 해당 승인 버전을 유지한다.
- Site의 기존 기능 inventory 관문과 등록·지도 API는 통과했다. 별도로 시도한 SQLite 직접 읽기는 DB를 열지 못해 ledger fingerprint 증거로 사용하지 않는다. observer token의 카메라 frame 직접 조회는 배포 전부터 401이어서 권한을 추가하지 않았다.
- 사용자 결정으로 Pinky 두 대는 오프라인에 두고 기존 자동 업데이트 경로를 유지한다. 로봇 적용·ARM64 장치 수용·실주행·카메라 frame 전체 흐름은 이 온라인 배포 수용에 포함하지 않는다. 이동 명령이나 E-stop reset은 보내지 않았다.
