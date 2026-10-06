## D-470 main CI 통과부터 로봇 서명 배포까지 고정된 로컬 서명기가 자동 연결한다

**Status:** Accepted (2026-10-05, 사용자 GitHub CI/CD 자동 로봇 업데이트 지시; DEVICE/FIELD 별도).

### Context

D-412는 게시된 서명 릴리스를 로봇이 받지만 빌드·서명·발행은 운영자의 명령이었다. 사용자는 main에 올리면 GitHub CI/CD가 로봇 업데이트까지 이어지도록 변경하라고 지시했다. D-437의 로컬 개인키 경계는 유지한다.

### Decision

1. 승인된 로컬 고정 설치본의 예약 작업이 main push CI를 확인한다. repository ID, CI workflow ID, event=push, head_branch=main, 성공 상태와 정확한 SHA가 맞아야 native unsigned build를 workflow_dispatch로 요청한다. PR·fork·실패·실행 중 CI는 대상이 아니다.
2. native workflow는 수동 API 진입점, 읽기 권한, unsigned 결과를 유지한다. run-name에 release ID를 담아 재개 시 빌드를 식별한다. CI·빌드 run·artifact source-revision이 같아야 서명하며 요청 사이 main이 바뀌면 거부한다. 대기 중 source도 main의 조상이어야 한다.
3. 서명·패킹·발행 helper까지 승인된 고정 설치본에 복사하고 해시를 확인한다. 자동으로 새 main을 checkout하거나 서명 PC에서 후보 코드를 실행하지 않는다. 새 도구 버전은 별도 검토된 커밋으로 설치한다. 현재 사용자 로그인 중 5분마다 확인하며 PC가 꺼지면 게시 전 단계가 대기한다.
4. YYYY.MM.DD-NNN 전역 순서를 유지한다. 기존 tags·예약 tags·장치 설치 버전을 보고 GitHub ref의 원자적 생성으로 payload-reserved ID를 선점한다. 예약 번호는 재사용하지 않는다. 단일 잠금과 SHA·ID·빌드 run·tarball digest·phase를 보존한다. 불완전 준비는 이전 증거를 남긴 별도 attempt로 최대 세 번 복구한다. 등록되지 않은 dispatch는 20분 뒤 실패로 기록한다.
5. 모든 대상의 ROS ABI를 확인한 뒤 기존 D-412 publisher로 게시한다. 재개는 공개키 검증된 원격 rollout의 source SHA·tarball digest·release ID·canary가 트랜잭션과 같을 때만 허용한다. 전송 실패는 pending으로 보존하고 철회는 terminal이다. 죽은 자기 publisher PID의 잠금만 회수한다. 새 트랜잭션은 이전 상태를 audit에 남기고 독립된 상태로 시작한다.
6. 자동화는 MANUAL·hold·보정·다른 claim·낮은 배터리를 해제하지 않는다. 로봇의 IDLE 조건·서명/해시·카나리·정상 상태 검사·롤백은 유지한다. 업데이트 성공은 Nav2 기동·지도·map 위치 확정·실물 주행 수용과 별도다.
7. D-412 결정 1의 수동 발행과 D-437 결정 1의 수동 후보 생성 제한을 이 자동 로봇 payload 경로에 한해 개정한다. D-145의 unsigned ARM64/offline signing, D-437의 키/runner 경계, 사이트 후보·SD 이미지 경로는 유지한다. 새 외부 API·모드·프로토콜 필드는 만들지 않는다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | developer-side release tooling 위치 유지 |
| D-429 | source 경로·소비 경계 유지 |
| D-430 | safety runtime·최종 명령 writer와 장치 적격성 검사 유지 |
| D-412 | 발행 전 자동 연결을 추가하고 카나리·철회·롤백 유지 |
| D-437 | 고정 로컬 실행 코드/키와 GitHub hosted unsigned build 유지 |

### Verification

실패한 CI·PR·fork·workflow 불일치, source race, main ancestry, artifact symlink/SHA 불일치, 설치본 변조, 예약 ID, 준비 재개, 다른 원격 rollout 거부를 호스트 시험으로 확인한다. 실제 예약 작업·GitHub 빌드·서명 게시·장치 installed SHA/updater committed는 별도 증거다. 호스트 PASS나 이전 배포 철회를 DEVICE/FIELD GO로 기록하지 않는다.
