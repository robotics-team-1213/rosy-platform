# 책임 분리 통합·검증·착지 증거

브랜치 `refactor/responsibility-execution`, 착수 소스 `51ad9b355f`.
이 기록은 로컬 소스·원격 시험과 실제 운영 수용을 구별한다.

## 통합과 회귀

동료 D-657의 원장 dispatcher/goal helper 이동을 유지하며 `358214688`에서 통합했다.
순수 전체 진척 projection, 설치 경로·native no-clobber 검사는 함께 유지한다.
중복된 이전 import shim은 없다. 이후 `757226957d`는 당시 main `342a72f479`를 포함한다.

`9fc0a88c9`는 구조/호출자/설치 검토에서 DTO 계약 모듈 분리, API 1.207 설명·시험,
source-first perception fixture, board 없는 기존 테스트의 복원 guard를 보완했다.
독립 검토자 `responsibility_review`가 의미·설치·권한의 중요 문제 해소를 확인했다.

원격 모델 PC의 `d942b265bf` 회귀는 세 invocation에서 9210/3870/3596 passed,
442/116/183 skipped였다. 합계 16676 passed/741 skipped이며 첫 invocation에는
크기 검사 1 NEW가 있었다. 나머지 두 invocation은 NEW0다.
이 수치를 전체 무실패 또는 최신 HEAD의 재실행으로 표시하지 않는다.
Console Node 시험은 289 passed/0 skipped다. opt-in 실제 Chromium은 실행하지 않았다.

`757226957d` 최종 영향 검사의 남은 NEW는 Fleet 52292 > 기존 52083+150였다.
D-661 두 책임을 `fleet/incidents`로 그대로 묶고 전체 직접 호출자를 바꿨다.
독립 검토자는 팀 알림·사람 인수가 하나의 사건 조정 영역이고,
판단·resolver·장치 admission이 기존 소유자에 남는 경계를 확인했다.
동일 physical-line 필터 실측은 Fleet 51933, incidents 360이다.
별도 하위 단위와 부모 재측정을 함께 기록했고 예산·허용 증가량은 유지했다.

## 최종 원격 검증과 로컬 FF

최종 검증 HEAD `7afb0e2c4f`는 main `1e163e70f3`의 전체 project_progress와
호출 시점 wire-schema import 개선을 통합했다. 설치 probe의 import 격리·실제 투영,
native no-clobber와 incidents 설치 검사를 함께 보존했다. 독립 검토자도 통합을 확인했다.

2026-10-11 AI PC 원격 terminal exit 0, 493 passed/0 skipped, 비교기 NEW0/known0.
범위는 구조·전체 harness·release boundary·wheel/sdist/source/native 설치·책임 추출,
판단 receipt·이름 있는 인수·알림·차선 정지 API/근거·resolver/loop·무조치·Mission progress다.
`land-incidents-2/refactor-responsibility-execution/run-1-1.txt`에 증거가 있다.
모델 PC가 자원 하한에 미달해 기존 runner가 AI PC를 선택했다. 노트북 pytest는 실행하지 않았다.

`tools/land.py` terminal exit 0, lint ok, 1 round에서 로컬 main으로 37 commits FF,
착지 SHA `7afb0e2c4f`. push하지 않았다. 이 기록의 후속 커밋은 결과 문서화이며,
소스 검증 대상과 실제 운영/CI 수용을 변경하지 않는다.
로그는 `X:/DevTemp/projects/rosy-platform/2026-10-11--201913--responsibility-execution--256063/logs/`다.
실패를 known failures에 추가하지 않았고 모든 성공 판정에는 비교기 NEW0를 요구한다.

## 팀 수용과 남은 관문

팀이 새 Discord 서버·채널·비공개 설정과 Pinky 정답 검수를 맡는다.
[팀 인수 절차](../../reference/team-discord-incidents.md)와
[독립 평가 검수](../pinky-judgment-acceptance-2026-10-11/review.md)를 사용한다.
실제 채널 발송/수신/이름 있는 로그인/담당 인수 readback/현장 결과/종료 통지와
정답·허용 한계 receipt는 없다. 단계 3~5 운영 수용과 단계 6 제한 모델 토론은 HOLD다.

원격 x86 wheel/sdist/native fake와 source closure는 실제 ARM64 이미지·배포·장치 증거가 아니다.
push·CI·배포·provider 활성화·실물 motion은 수행하지 않았다.
