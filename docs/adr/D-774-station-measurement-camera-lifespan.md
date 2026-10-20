# D-774: 스테이션 측정 카메라는 설치된 관측 프로세스가 실행 중일 때 송출을 요청한다

**Status:** Accepted (2026-10-16, D-772의 사용자 승인 자동 접안·복귀 경로 구현). 실기 활성화·광학 수용은 별도다.

## Context

D-691의 일반 카메라는 인증된 preview 읽기 후 30초 동안만 송출한다. D-772 자동 접안 관측까지 같은 조건에 두면 화면을 닫은 뒤 제어 관측이 사라진다. 내부 추적이 preview 요청을 가장하거나 영상을 임의로 재교정해서는 안 된다.

## Decision

`rosy-vision station-vision --config <JSON>`의 승인된 설치 source만 명시적인 measurement demand를 갖는다. 프로필 전체와 서로 다른 phone/source 자격증명을 검증한 뒤 기존 IngestServer를 시작한다. 각 source의 관측 worker가 실행 중인 동안 기존 `demand.wanted=true`를 보낸다. 소비 task가 종료하면 소유 프로세스는 실패로 끝내며, 종료 시 measurement demand를 해제하고 WebSocket과 HTTP client를 닫는다. 일반 vision·tracking의 기본 생성자는 measurement source가 없으며 D-691의 인증 preview 요청/30초 규칙을 유지한다. 카메라의 발열·전원 보호는 우선한다.

수신기는 설치 source별 기존 `config.width`만 선택한다. 새 height/rotation 필드를 와이어에 추가하지 않는다. worker는 실제 frame header의 크기·회전과 JPEG decoding 크기를 교정과 대조한다. 임의 rescale·viewer transform을 사용하지 않는다. 측정용 pinhole lens 교정과 marker-plane 교정은 같은 source/epoch/설치 revision에 결속한다. source epoch는 설치 프로필의 관측 세대이며 phone sequence 초기화나 링크 재연결로 새로 만들지 않는다. 유효한 최신 frame 이외의 관측은 갱신하지 않는다.

CLI는 관측만 조립한다. Fleet의 접근 검증·위치 버전 확정·세션 권한이나 CORE의 최종 주행/정지·충전 권한을 갖지 않는다. 프로필의 approved는 설치자가 제공한 승인 기록이며 실제 측정·현장 수용의 자동 증거가 아니다. 배포·실기 capability 활성화는 이 명령 실행 권한에서 추론하지 않는다.

## 관계와 검증

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 operations/overhead 안에서 조립하며 새 최상위 배포 소유자를 만들지 않는다 |
| D-429 | 카메라는 관측만 제공하고 Fleet·CORE의 실행 권위를 보존한다 |
| D-430 | lens/profile/measurement 수명 경로를 safety 검토·원격 시험 대상으로 등록한다 |
| D-691 | 일반 preview의 규칙을 보존하고 설치된 D-772 측정 source에만 예외를 둔다 |
| D-772 | 화면 열림과 독립된 정밀 접안·스테이션 재발견 관측을 구성한다 |

설치 검증·비밀 분리·실제 JPEG/HTTP·WebSocket demand 및 종료·일반 preview 회귀를 원격에서 확인한다. 실측 광학/장치 프로필과 DEVICE/FIELD는 별도 기준이다.
