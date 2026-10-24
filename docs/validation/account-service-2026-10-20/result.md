# D-807 Account 배포·수용 후속 기록

2026-10-20 KST 기록. [승인된 실행 계획](../../plans/2026-10-19-account-service-rollout.md), [전일 소스·원격 검증](../account-service-2026-10-19/results.md), [D-807](../../adr/D-807-account-service-credential-ownership-and-acceptance.md)을 잇는다. 전일 기록은 당시 관측으로 보존한다. 이 기록도 배포·익명 진입 검증을 실제 사람·단말의 수용으로 확대하지 않는다.

다음 수용에는 실제 Android 연결과 로봇 전원·등록, Games의 운영 호스트·HTTPS callback, 여섯 번째 사람 계정의 원본 확인이 필요하다. 본인 영구 비밀번호·provider 동의·업무 결과는 사용자가 확인해야 한다. 이 입력 없이 전 앱 완료로 판정하지 않는다.

## 소스와 시험

최종 검토 commit `6b94197966835332701cbc7f83371643c51f0787`과 [PR119](https://github.com/robotics-team-1213/rosy-platform/pull/119)의 squash commit `a42ae9062ee4d7b29d3d3fd66a3087f155148194`는 tree `7193b9fa854efce362e6f43e67123d011058b7a4`가 같다. 실제 squash 메시지의 Safety-Review와 메타데이터 검사도 확인했다.

| 관문 | 실제 범위와 결과 |
|---|---|
| 최종 commit 원격 focused | 정책·보안 92 passed, NEW 0 / known 0 / flaky 0 |
| 정상 push 관문 | 네 보고서 21701 passed / 962 skipped / 92 subtests, 모든 보고서 NEW 0 / known 0 / flaky 0 |
| [PR CI39339745196](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39339745196) | 19개 작업 성공. 실제 checkout commit `f37e2d2cdcb24769b585bf2a5f963fd54e2a061d`의 tree가 위 검토 tree와 같다 |
| [main CI39342200884](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39342200884) | 실제 commit a42, 19개 작업 모두 성공. pytest 작업 16개·요약 31개에서 29451 passed / 0 failed / 1578 skipped, 모든 공식 분류 NEW 0 / known 0 / flaky 0 |
| [candidate39342200990](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39342200990) | unsigned 이미지·출처 증명·게시 4개 작업 성공. pytest·서명·설치 증거와는 별도 |

시험은 서로 겹치므로 위 수치를 합산하지 않는다. 1578 skipped를 실행 성공으로 세지 않는다. main CI의 카메라 10개 매개변수와 departure False/True는 명시적 PASSED였다. 역사적 station 네 항목은 [같은 소스 실패·통과 분류](../station-test-classification-2026-10-20/result.md)를 유지하며 원인 해결을 주장하지 않는다. 미게시 scheduling 실험은 최종 소스에 없다.

PR126의 이전 squash commit `815e5027483cb49ceacc4c562d83cb1439692cbe`는 검토 footer가 빠져 main CI39337638405가 pytest 전에 실패했다. 기존 reviewed-history 절차로 해당 squash의 byte-identical 검토 출처를 결속했고, 새 main의 전체 CI를 별도로 통과했다. 이전 실패를 성공으로 다시 분류하지 않았다.

## 서명과 현장 설치

기존 signer가 정확한 main CI, 태그·commit 일치와 GitHub build-site-candidate 출처를 검사한 뒤 기존 신뢰 키로 서명했다. [서명된 릴리스](https://github.com/robotics-team-1213/rosy-platform/releases/tag/site-a42ae9062ee4)는 정상 활성화된 현장 updater가 2026-10-20 00:08:35 UTC에 설치했다. 수동 관리자 인증 우회나 신뢰 키 교체는 없었다.

Fleet·Vision·Proxy는 모두 commit a42 참조로 실행 중이며 healthy다. 영속 updater 상태는 같은 설치 commit, hold 없음·진행 중 switch 없음이다. 실제 Fleet에서 가져온 AccountClient SHA-256은 `0fcb7f06a4048c9a64040baa9271743690c0a622fff69a9cb8e2164046fec31d`, 복구 guard SHA-256은 `88ebbd6f5bb01110a733ccb30c85d8deeceff07dc33308d81a3efa1c0940105b`로 해당 commit의 파일과 일치했다.

설치 캐시의 manifest·signature가 게시된 바이트와 같음을 확인했다. 이미지 archive를 read-only로만 연결한 격리 진단에서 archive SHA-256과 OCI descriptor 해시를 검증하고 실제 실행 이미지 3개의 OCI 식별자를 서명 manifest의 config ID에 연결했다. OCI 식별자와 config ID를 같은 값으로 취급하지 않았다. 진단에는 운영 DB·키·설정·socket·장치를 연결하지 않았다.

TLS 검증을 유지한 실제 HTTPS 요청에서 중앙 login200·JWKS200(공개키 1개)·익명 session401을 확인했다. 별도 Vault 배포도 root200·익명 session authenticated=false·보호 devices401·중앙 login303과 정확한 callback 및 Secure/HttpOnly cookie를 확인했다. 이 관측은 실제 사용자의 허용 업무나 영속 결과를 입증하지 않는다.

## Learning 앱 5개 전환과 데이터 보존

edge·v12·v13·v13-eval과 legacy937 Account front를 최종 commit 6b로 활성화했다. 원래 legacy 서버는 loopback backend로 유지하고 별도 인증 front를 통과하게 했다. 여섯 서비스는 active/enabled이며, 외부 HTTPS 다섯 경로에서 익명 접근 차단·계정 화면·정확한 중앙 client/resource/callback·Secure/HttpOnly cookie를 검증했다. 현장 peer에서도 정상 TLS로 재확인했다. 공개 요청의 Host를 조작하지 않았다.

재시작 후 설치된 다섯 release 각각의 manifest 파일 1476개가 고정 소스 해시와 일치했다. HTTP listener 여섯 개는 loopback 전용이고 과거 비인증 decisions listener는 없다. 현장 업데이트 뒤에도 다섯 receiver의 공개키 pin이 현재 Authority JWKS와 일치했다.

전환 직전 review writer만 멈춘 일관된 보호 백업은 1347파일과 해시 manifest다. 네 SQLite의 integrity check를 통과했고, 모든 원래 열을 투영해 42개 기존 테이블의 원래 행과 값이 보존됨을 확인했다. 기존 비 SQLite 파일 1297개와 legacy 원본·정적 보호 설정의 바이트도 보존됐다. metadata에는 보호 설정과 정확히 같은 collaboration_project 한 행만 추가됐다.

edge의 빈 pixel_drafts와 v12의 7개 초안에는 기존 migration이 origin=NULL, withdrawn=0 열을 추가했다. 원래 열·값·기본키를 보존하고 철회되지 않은 초안으로 유지함을 확인했다. 최초 SELECT* fingerprint는 열 추가를 값 변경으로 판정해 서비스를 멈췄다. 중간 검사 실패 뒤 무조건 재시작 명령을 보낸 실수는 즉시 다시 정지해 바로잡았고, 최종 재개는 전체 보존 검사의 성공 뒤에 수행했다. 옛 DB 복원·사람 라벨 재작성·자동 membership 부여는 하지 않았다.

기존 UI-follow updater만 비활성화해 이전 UI로 덮어쓰지 못하게 했다. training·model-code updater·bridge/pipeline은 재시작하거나 재설정하지 않았다. UI-follow 재개는 호환되는 승인 소스와 Account 인자 검증 뒤 별도로 수행한다. 실패 시 기본 복구는 해당 앱·경로를 닫고 현재 사람 데이터를 보존하는 것이다.

## 계획 항목별 판정과 남은 수용

| 계획 항목 | 이 기록으로 입증한 범위 | 아직 입증하지 않은 범위 |
|---|---|---|
| Task 1–2 공통·CORE | 기존 영속 회수·장애·브라우저 회귀와 최종 소스 CI | 실제 장치의 열린 REST/WS/native/media 회수 계측 |
| Task 3 앱별 | 최종 소스 통합 검증. Cam JVM 441 passed, 별도 Pilot release JVM 106 passed / 선택 probe 1개 제외. 두 운영 설정 포함 APK의 서명·스테이징 | 실제 Android 설치·app-link·Keystore·사용자 callback. 최신 field ADB 조회는 연결 기기 0대 |
| Task 4 설치·전환 | 중앙·Vault·Learning 설정/백업/서명·설치·runtime 경계. 기존 사람 5명과 최초 변경 정책 유지 | 실제 Games 호스트/client/callback 및 여섯 번째 사람 원본, offline 로봇 receiver 설치·재등록 |
| Task 5 격리 복구 | 배포 Authority의 격리 RAM DB와 read-only 키 복사본에서 fresh-process password/disable/family/refresh-replay·키 overlap·stale restore 거부. 기존 실제 DB 복사본 guard 검사. 변경 없는 Authority/guard 소스 결속 | 운영 키 실제 교체·JWKS 공개·receiver lifecycle, 옛 key/trust rollback 방어 전체의 수용 |
| Task 5 사람·장치 | 익명 진입·거부와 배포 생존 상태 | 실제 관리자/사용자 로그인·앱 복귀·허용/거부·영속 결과·logout/disable, 일반 30초/5분과 D-789 미디어 종료 계측 |

Games의 preview CLI는 실제 match와 robot client를 시작하므로 로그인 probe로 실행하지 않았다. 다섯 Learning 프로젝트의 grant도 실제 관리자 흐름에서 확인해야 한다. Vault의 실제 허용 작업·기계 자격 매핑도 미수용이다. native·복구·main pytest는 서로 다른 산출물과 범위이므로 하나의 수치로 합치지 않는다.

## 원본 증거와 한계

실제 호스트·사용자·보호 설정·백업 경로와 raw capture는 보호 운영 기록에만 남겼다. 공개 식별자는 다음 SHA-256으로 원본에 결속한다.

| 원본 | SHA-256 | 입증 범위 |
|---|---|---|
| main CI evidence-summary.json | `a54e88008bd4350fce7ac568041f80d4c7cf158c9bba074eaed4a0b6ef593dd9` | 실제 checkout·작업·수치·분류. 전체 job log와 별도 해시 목록 보관 |
| release.json | `290824ac50877b2cc253fee9d6c46bfafe8c47b0ded08f27046b723838780c9c` | 4494바이트 manifest, GitHub attestation subject와 설치 캐시 일치 |
| release.json.sig | `958a3781a2da8a9aa6b4e64d13e238b1af971583907099a865ad3aa956e6dd02` | 기존 신뢰 키의 배포 서명 바이트 |
| images.tar | `57edcb656dff9d8ed6facfbc3af2e0530413bb231f5ffc3b95b4460dc2da8926` | 설치된 이미지 archive와 OCI/config 연결. 외부 tar.part00와 다른 객체 |
| 현장 runtime receipt | `6b70e2fa3205be2fdd30d514cfb0aef50560984104b1629245f94f092bb16630` | 4258바이트 UTF16LE+BOM. 실행 상태·파일 해시·HTTPS. native SSH 명령 exit0의 호스트/시각 귀속은 별도 기록 |
| Learning data receipt | `ce6c32967f20cef58bab3f5b785fbf26e5eeeb0acf5f8a96bf5df2f5bdb4c011` | 2389바이트. 원래 행·파일 보존과 명시한 추가. service/TLS 증거는 별도 native 관측 |

독립 읽기 전용 검토가 두 runtime/data 영수증의 해시·필드, commit/tree·원본 소스 해시 및 기록의 범위를 대조해 뒷받침되는 문제를 찾지 않았다. 검토자가 실제 운영 DB·물리 장치를 다시 검사했다는 뜻은 아니다. 운영자 관측을 결속하는 이 기록만으로 전 앱 실사용 수용이 완료되지는 않는다.
