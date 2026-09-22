## D-172 첫 Pinky Pro 카드는 머지된 커밋의 서명 이미지를 검토된 plan에 고정해 굽는다

**Status:** Accepted (2026-09-22). D-164(서명 `.img.xz`), D-33(로봇 신원), ROSY-DEPLOY-SIGNKEY-001을
첫 실기 카드에 적용하는 결정.

**Context:** 첫 Pinky Pro 실기 이식을 위해 SD 카드 한 장을 굽는다. 결정이 필요한 사실은 다섯 가지다.

- main HEAD는 PR #19 머지(`9aee918`) 뒤 직접 푸시된 커밋들 때문에 CI가 빨갛다(하네스 로그 순서,
  stale index, 테스트 fixture의 가짜 secret). 로봇 패키지 payload는 `9aee918`과 같다.
- 이전 unsigned 이미지(`2026.09.22-001`)는 `58c9e8a`(#16) 기준이라 #17-#19의 서명기·Imager 수정 이전이다.
- 오프라인 서명 개인키는 별도 서명 머신이 아니라 운영 PC의 `%LOCALAPPDATA%\Rosy\signing\`에 있다.
  그 공개키는 저장소의 신뢰 앵커 `rosy-release-2026-01.pem`과 SHA-256이 같다.
- 중앙 Fleet 서버는 아직 없다. 첫 부팅은 Fleet 값을 `/etc/rosy/fleet-bootstrap.json`에 저장만 하고
  읽는 코드는 없다.
- `prepare-rosy-sd.ps1`은 로봇 번호와 Fleet 값을 필수로 요구했고, PlanOnly와 WRITE가 장치 이름을
  각자 새로 뽑아 검토한 계획과 기록된 카드가 달라질 수 있었다.

**Decision:**

1. **이미지 기준은 마지막 머지 커밋이다.** `9aee918`에 `release/2026.09.22-002` 태그를 달고
   `build-pinky-image.yml`을 native ARM64 러너에서 실행한다. 직접 푸시된 main HEAD로는 발행하지 않는다.
2. **서명은 운영 PC의 기존 키로 한다(파일럿 한정).** 새 키를 만들지 않는다 — 새 키는 이미지에 들어간
   신뢰 앵커와 달라 카드를 다시 구워야 한다. 서명 직후 커밋된 공개키로 재검증한다. 별도 오프라인 서명
   환경(SIGNKEY-001 §4)으로의 이전은 FIELD 전 조건으로 남긴다.
3. **로봇 번호는 registry의 빈 번호(1-61) 중 무작위로 배정한다.** 고정 기본값이 아니므로 D-33을
   지킨다. 무작위는 registry가 분리된 운영 PC 사이의 DDS domain 충돌 확률을 낮춘다.
4. **Fleet 값은 콘솔 호스트 기본값(`https://<host>.local`, `rosy-pilot-lan`)으로 채운다.** plan에
   출처(`fleet_source: default`)를 남기고, 중앙 Fleet 서버가 생기면 재프로비저닝으로 바꾼다.
5. **기록은 검토된 plan에 고정한다.** `-PlanOnly -PlanPath`로 plan을 한 번 저장하고, WRITE는 같은
   plan의 신원·preset·model·country·Fleet 값을 그대로 쓴다. 디스크·이미지·SSID·DDS 신원·registry가
   바뀌었거나 인자가 plan과 (대소문자까지) 다르면 writer 호출 전에 멈춘다. 자동 번호는 WRITE 안에서
   뽑지 않는다.

**구현·처리 항목:**

| # | 항목 | 상태 |
|---|---|---|
| 1 | `9aee918` 태그 + ARM64 이미지 빌드 (run 35717277503) | 완료 — unsigned handoff 12 files |
| 2 | 다운로드 + `SHA256SUMS` 검증 | 완료 — 12/12 OK |
| 3 | 기존 키로 서명 + 공개키 재검증 (`sign_image_release.py`, `verify-image-release.py`) | 완료 — image sha256 `eaf843c4…` |
| 4 | `prepare-rosy-sd.ps1` 자동 번호·Fleet 기본값·plan 고정 (PR #20, 계약 46 passed) | 완료, 리뷰 반영 |
| 5 | `-PlanOnly -PlanPath` 실행, plan 보관 | 완료 — `rosy-pinky-e4us`, 18번, domain 58, disk 1 serial `000000000207` 32 GB |
| 6 | 관리자 권한 WRITE: Imager `--cli --sha256` → 전체 readback → 일회성 bundle → registry·receipt | 이 ADR로 실행 |
| 7 | 카드 부팅, first-boot `PROVISIONED`, readback JSON (runbook G0-G2) | 실기 필요 |
| 8 | main CI 복구(emotion 로그 순서, fixture 가짜 secret) | 미해결 — main 소유자 작업 |
| 9 | 서명 키를 별도 오프라인 환경으로 이전 | FIELD 전 조건 |

**Alternatives:**

- main HEAD로 빌드 — CI가 빨간 상태의 검토 안 된 커밋을 제품 provenance로 남긴다.
- 기존 `2026.09.22-001` 재사용 — 더 빠르지만 manifest revision이 머지 커밋과 다르다.
- 새 서명 키 생성 — 이미지 신뢰 앵커를 바꾸는 커밋과 재빌드가 필요하고, 키 의식을 개발 PC에서
  다시 하는 것이므로 위험이 줄지 않는다.
- 가장 작은 빈 번호 배정 — 결정적이지만 운영 PC가 둘이면 같은 domain을 내준다.
- plan 없이 매 실행마다 신원 생성 — 확인한 plan과 구운 카드가 달라질 수 있다.

**Consequences:** 첫 카드는 머지 커밋과 정확히 묶인 서명 이미지를 쓰며, 장치 신원은 plan 파일과
receipt로 추적된다. 개인키가 운영 PC에 있는 동안 이 PC가 유출되면 모든 파일럿 카드의 신뢰가 무너진다
(SIGNKEY-001 §2). 이는 파일럿 위험으로 수용하고 FIELD 전에 닫는다. Fleet 값은 실제 서버가 생기면
다시 정해야 한다. 카드 기록은 MEDIA 증거일 뿐 BOOT·DEVICE·FIELD를 승격하지 않는다.

**Validation / Transition:** 쓰기 성공 기준은 Imager exit 0, 전체 readback `verified: true`,
boot 파티션의 `rosy-provision/provision.json`, registry에 18번·`rosy-pinky-e4us` 등록, receipt 생성이다.
그 뒤 [첫 장치 런북](../deployment/pinky-pro-first-device-runbook.md) G0-G5를 따른다. 증거 파일은
`F:\tmp\rosy-release\cards\`의 plan·receipt와 서명된 릴리스 폴더다.
