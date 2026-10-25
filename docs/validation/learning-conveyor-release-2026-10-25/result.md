# Learning 접촉 왕복 결과의 공개 소스 연결 — 2026-10-25

공개 accepted source의 Learning 화면과 기존 실행 상세·평가 연결을 보존하며 접촉 보고서와 다섯 단계 PNG 조회, 선택한 시나리오의 재실행 복원을 추가했다. 별도 pinned Isaac checkout을 기존 LocalRuns로 연결하며 SDK나 학습 정책을 검수 앱에 복제하지 않는다.

## 새로 실행한 검사

- `28cbe5dc48`의 원격 API 회귀에서 새 접촉 경로 아홉 건의 404를 재현했다. 기존 import 보고서는 유지됐다.
- `ebc1a89c52`의 명시적 원격 Chromium/API 26개가 통과했다. 공개 소스에만 있던 평가 화면·실행 상세 링크 회귀도 유지했다.
- `b1f990bbd8`의 원격 설치기 회귀에서 신규 private SIM binding 및 구버전 복귀 후 재활성화 네 건의 실패를 재현했다.
- `e24bb3ea58`의 원격 설치기·자동 갱신기 48개가 통과했다. 일반 파일·소유자 전용 권한, 대상 CLI 지원, 이전 release 복귀와 연결 복원을 검사한다.
- 최종 게시 head의 영향 범위·pre-push·CI와 운영 배포 수용은 후속 결과로 구분해 기록한다. 위 중간 SHA의 통과를 최종 게시·운영 수용으로 간주하지 않는다.

## 기존 증거 재사용과 한계

물리 성공 증거는 실행 source `7d0cfcd6e94fd0181e324319e12c274f3e2f3890`, run `36041b241ee25366986bb3a6262ba0be`의 불변 결과다. 개발 이력의 `docs/validation/isaac-pinky-conveyor-roundtrip-2026-10-25/result.md`와 이번 공개 포트의 이력은 구분한다. 해당 문서는 아직 공개 이력에 없으므로 별도 보존된 원본 기록을 따른다.

이번 연결은 저장 결과 조회 기능이다. 새 SDK 실행·학습 Episode 생성·정책 평가·실물 명령은 수행하지 않았다. 희소 접촉 관측과 다섯 PNG를 동기화된 시연 Episode로 취급하거나 policy SIM pass로 승격하지 않는다.

## 운영 적용 조건

현재 운영 unit의 state·Python·listener·collaboration·OMX center·workspace links를 보존한다. 기존 signed model-code 승인과 review release 설치기를 사용하고 새 private `sim-config.json`만 결속한다. source/binding/workspace/hash 검사와 활성 학습 작업 거절을 우회하지 않는다. 운영 성공 판정에는 서비스 상태 외에 인증된 기존 run과 여섯 artifact 원본 조회가 필요하다. 실패 시 이전 current와 unit 원본을 복구한다.

CE: 해당 없음. 기존 [동일 unit 보존 교훈](../../solutions/deployment/learning-center-upgrade-needs-the-identical-unit-first-2026-10-23.md)을 적용하며, 이번 일반적인 consumer/installer 누락은 코드·회귀 시험으로 설명된다.
