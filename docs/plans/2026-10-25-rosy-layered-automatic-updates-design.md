# ROSY 이미지의 전 계층 자동 업데이트 완료 기준

상태: 사용자 요구와 후속 구현 목표, 2026-10-25. 현재 전체 OS 자동 갱신 구현·실물 수용을 뜻하지 않는다.

사용자는 다기종 배포 구조화 뒤 이미지를 배포하고, **배포된 ROSY 자체가 이후에도 OS를 포함한
전체 구성의 자동 업데이트를 지속 처리**하도록 요구했다. 앱 코드만 자동으로 바뀌는 상태를
전체 목표 완료로 보지 않는다.

## 유지할 기존 결정

[D-412](../adr/D-412-robots-self-update-from-signed-github-releases-when-idle.md)의 서명된 릴리스
자동 확인·유휴 적용·카나리·장치 hold와 [D-387](../adr/D-387-robot-updates-operator-approved-rollout.md)의
계층별 복구·전원·재부팅 경계를 재사용한다. D-412는 D-387의 3·4계층 구현을 완료하지 않았다.
새 목표 때문에 서명·정비 gate·장치 identity·보정값 보호를 생략하지 않는다.

## 배포 이미지의 필수 수용 조건

| 구성 | 자동 업데이트가 증명해야 하는 결과 | 현재 확인한 범위 |
| --- | --- | --- |
| ROSY 앱·런타임 | 적합한 서명 릴리스 탐색, staging/apply, 실제 새 코드 실행, 실패 rollback | 기존 updater/timer 소스 존재. 현재 연결 기체의 활성 상태는 미확인 |
| host 도구·서비스 | 서명된 파일/유닛 변경, health, 재시작과 실패 복구 | image-layer sync와 boot-support catalog/inverse 소스 존재 |
| OS userspace·시스템 패키지 | 고정된 패키지 closure, 멱등 적용, 설치 버전 확인, rollback/복구 | 계층별 구현 inventory와 수용 근거 추가 필요 |
| 커널·모듈·DTB·부팅 구성 | 호환 조합 staging, 재부팅 전후 연속성, boot 성공 확인, 실패 fallback | D-387 boot/tryboot 경계. boot-support script 갱신과 동일하지 않음 |
| 전체 OS/rootfs·메이저 변경 | 비활성 슬롯/복구 가능한 이미지 적용, 서명·대상 검증, 정전/부팅 실패 복구, 개인 데이터 보존 | D-387 P4 별도 단계. 현재 지원 완료로 광고하지 않음 |
| 제조사 firmware | 해당 기종의 공식 갱신·복구 경로와 실제 결과 | EEPROM/HAT/SDK 기체별 별도 판정. 지원 불명 firmware를 자동 flash하지 않음 |

모든 계층은 산출물 버전과 실제 실행/설치 readback을 구분해 표시해야 한다.
업데이터가 실행됐거나 다운로드가 끝났다는 이유로 적용 완료를 표시하지 않는다.
정전·네트워크 단절·공간 부족·서명 오류·기종 불일치·유휴 아님·hold·재부팅 중 재개를 반례로 둔다.

## 구현·배포 순서

1. 진행 중인 다기종 도구 재구조화와 기종 설정 결속의 정상 source 병합을 마친다.
2. 기존 자동 업데이트의 producer→서명→배포→설치→health→rollback 경로를 계층별로 감사한다.
   병행 `feat/auto-update-everywhere`의 다른 호스트 작업을 확인하고 중복 수정하지 않는다.
3. 누락 계층의 계약/산출물/복구 구현을 별도 시험 단위로 진행한다. 공개 manifest/API 변경은
   생산자·소비자·예약 절차를 함께 적용한다. 특정 A/B backend는 공식 근거와 실제 파티션/부팅 증거 뒤 선정한다.
4. native ARM64 이미지의 서명·패키지 inventory·boot 설정·자동 update timer/서비스 enable을 검증한다.
5. 실제 배포할 이미지와 연결된 Pinky의 identity·현재 OS/커널/릴리스·키·업데이트 상태·전원/정비 상태를 확인한다.
6. SD write/readback·실기 부팅 뒤 자동 업데이트와 실패 복구를 실제 기체에서 수용한다.
   이후 새 릴리스도 같은 경로로 계속 적용되는 연속성을 확인한다.

제품 배포 대상이 제조사 SDK 호스트인 경우 ROSY 어댑터/앱 업데이트와 제조사 OS/firmware 관리를
구분한다. 공식 API가 없는 Neo 2를 이 계획만으로 제어·업데이트 가능한 대상으로 바꾸지 않는다.

이 문서 작성과 source 시험은 실제 기체 접근·배포·재부팅·firmware flash·public push를 수행한 증거가 아니다.
