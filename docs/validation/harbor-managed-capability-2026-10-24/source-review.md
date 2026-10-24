# D-856 managed capability의 독립 소스 검토

기준 commit `f6c3a7195e`, 검토자 `neutral_arm_contract_review` (`rosy_contract_reviewer`). 등록 factory→shared admission/store/final owner→canonical journal/session→grant→phase→receipt→Fleet SDK의 실제 경로를 검토했다.

설계 검토에서 receipt의 정적 journal 덮어쓰기와 SDK의 404→None을 지적했다. 구현은 실제 attempt snapshot의 canonical journal을 ARM receipt로 내보내고 static identity가 덮지 못하게 한다. Fleet는 ARM grant의 journal을 대조하며 ARM 404는 fenced reconciliation이 필요한 unavailable로 남긴다. 과거 Action GET은 같은 journal에서 세션이 달라져도 허용하고 과거 세션으로 새로 실행하지 않는다.

구현 재검토에서 material finding은 없었다. capability는 실제 등록된 불변 callable factory·같은 admission/store/final owner·session/managed scope를 대조한다. canonical journal과 scope는 같은 SQLite read snapshot에서 읽고 identity를 만들지 않는다. ARM journal/session의 완전 digest와 pre-journal/phase/command 결속도 확인했다.

고정 feature commit `46f56d6b481af9d7af50c29a546d8a5ceb15547a`도 같은 독립 검토자가 재검토했고 material finding은 없었다. 원격 결과와 진행 중인 FULL은 [검증 기록](result.md)에서 구분한다. 이는 Fleet physical producer/claim 해제·실제 ROS·장치·현장 수용을 승인한 결과가 아니다.
