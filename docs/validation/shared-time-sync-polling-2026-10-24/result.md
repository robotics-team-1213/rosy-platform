# ROSY 공통 NTP 갱신 주기 보완

기준 소스는 `fe0519eea1`, 브랜치는 `fix/ntp-upstream-polling`이다. [D-861](../../adr/D-861-one-identical-ntp-endpoint-for-all-devices.md)의 동일한 단일 관제 source와 기존 50ms 정밀도 검사를 유지한다. 앞선 시간원 선택 수정은 main `497a792af2b7`에 반영됐고 해당 착지 검증은 474 passed였다.

## 보완 내용

공식 [chrony 설정 문서](https://chrony-project.org/doc/4.5/chrony.conf.html)는 외부 공용 서버를 64초보다 자주 조회하지 않도록 권고한다. 생성 설정을 역할별로 나눴다. 관제의 외부 source는 minpoll 6 / maxpoll 6, 내부 관제만 따르는 Linux client는 기존 minpoll 4 / maxpoll 6을 유지한다. 주소·인증·source 개수·step 정책은 바꾸지 않았다.

Windows는 실제 polling이 1024초인 것을 확인했다. 기존 registry 전체 백업 및 domain/policy 거부 뒤 W32Time Config의 MinPollInterval/MaxPollInterval을 각각 DWORD 6으로 설정하고 기존 `/config /update`를 적용한다. 이는 내부 관제 peer의 64초 갱신이며 `0x8` client mode와 단일 peer를 유지한다. 의미·단위는 [Microsoft 설명](https://learn.microsoft.com/windows-server/networking/windows-time-service/windows-time-service-tools-and-settings?tabs=config)을 따른다.

## 검증

- `cf4fc39941`의 새 site 조건이 외부 minpoll 4를 거부했다. `d1cfcf4c7e`에서는 site 및 Windows 조건 두 개가 실패했다.
- 수정 후 시간 동기·harness 원격 검증 exit 0, 영향 선택은 **354 passed / 37 warnings / exit 0**, NEW 0 / known 0 / flaky 0이었다. 공식 runner를 사용했고 노트북 pytest는 실행하지 않았다.
- 원본 로그: `%LOCALAPPDATA%/Temp/rosy-time-poll-fix/{red,platform-red,green,affected}/run-1.txt`.
- PowerShell 구문과 WhatIf 검증은 통과했다. 독립 검토에서 주요 지적은 없었다.
- 관제 실제 설정에서 외부 source 다섯 개 모두 `nts`와 minpoll/maxpoll 6을 확인했다. 같은 범위를 실행 중 daemon에 적용하고 제한된 burst로 갱신했다. NTP·관제 서비스 재시작과 강제 clock step은 없었다.
- Windows 관리자 실행은 exit 0이었다. 이후 registry 두 값이 6, 실제 상태가 `Poll Interval: 6 (64s)`, 동일한 관제 Source 하나, Last Sync Error 0, 마지막 성공 표본 약 6초를 확인했다. W32Time의 정상 보정 방식을 사용하며 강제 step을 추가하지 않았다.
- 모델·AI 설치 준비 파일도 수정 소스로 다시 배포했다. 이 파일 복사는 실행 중 clock 설정을 바꾸지 않는다.

## 남은 조건

사용자는 Pinky 두 대가 실제로는 아직 꺼져 있다고 정정했다. 앞선 No route/timeout은 현재 장치 설정이 틀렸다는 증거가 아니다. 전원 전에는 추가 접속을 반복하지 않고, 부팅 후 신원·공통 이름의 resolver·UDP 경로·실제 선택 source·clock domain·재부팅/단절 복구를 확인한다.

Pinky 가입 구현의 `--accept-dns=false`와 현재 VPN DNS 기반 endpoint 조합은 실물에서 아직 검증하지 않았다. PC의 성공을 로봇으로 일반화하지 않는다. 현재 CLI 설치 절차는 명시적 등록 단계이며, 이 변경으로 새 이미지의 자동 사이트 등록이나 자동 admission gate가 생기지는 않는다.

현재 UTC 정밀도 수용도 HOLD다. 관제의 마지막 후속 관측은 stratum 3/Normal, 남은 correction 약 5.48ms, 보고 UTC 상한 약 198ms였다. 이 상한은 WAN 지연·불확실성을 포함하며 실제 시계 편차를 그 값으로 측정했다는 뜻은 아니다. 50ms 기준과 실제 로봇 간 시각 정렬은 별도로 검증한다.

CE: 미해결 — 로봇 실물·정밀도·복구 수용이 남아 있다. polling 보완의 근거와 재발 방지는 코드·회귀·운영 안내에 함께 보존했다.
