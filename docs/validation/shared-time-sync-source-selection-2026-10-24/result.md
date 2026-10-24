# ROSY 공통 NTP 실제 동기 복구와 시간원 선택 수정

기준 결정은 [D-861](../../adr/D-861-one-identical-ntp-endpoint-for-all-devices.md), 앞선 기록은 [최초 설치·Windows 적용](../shared-time-sync-2026-10-24/result.md)이다. 모든 Linux 클라이언트와 Windows는 비공개 설치 기록의 동일한 관제 NTP endpoint 하나를 사용한다. 이 수정은 다른 시간원·fallback을 추가하지 않는다.

## 실제 장애와 원인

사용자가 모델·AI PC의 전용 SSH 창에서 sudo 인증을 완료한 뒤 chrony와 공통 source 설정은 설치됐다. 그러나 실제 상태는 stratum 0 / `Not synchronised`, source reach 377 / `^?`였다. 서버 응답이 도착한다는 사실과 같은 이름의 source 설정만으로는 동기 완료를 입증하지 못했다.

생성 설정의 `maxdistance 0.1`이 정상 패킷의 root distance를 거부했다. 관제의 인증된 상위 시간원은 root delay 약 242ms, dispersion 약 14ms였다. 남은 correction을 더한 보고 오차 상한 약 136ms가 선택 한도 100ms를 넘었다. 정상 시각을 천천히 따라가기 전에 시간원 자체가 선택에서 제외된 것이다.

`maxdistance`는 chrony 기본값인 3초로 복구했다. 이 값은 시간원 선택 한도이며 UTC 정밀도 수용 기준이 아니다. 기존 `assess()`의 50ms UTC 오차 상한·180초 표본 나이·leap/stratum/유효 수치 검사는 **그대로 유지했다**. 높은 WAN 불확실성을 정밀 수용 통과로 숨기지 않는다. 근거는 [chrony 설정 설명](https://chrony-project.org/doc/4.5/chrony.conf.html)이다.

## 검증된 수정

- 소스 `c50c268c1410`, 브랜치 `fix/ntp-source-selection`, 기준 `8a80472a23`.
- 새 회귀는 `0f03ec849b`에서 `0.136 < 0.1` 실패를 재현했다. 수정 후 시간 동기 집중 34개와 영향 선택 전체 **354 passed / 37 warnings / exit 0**이었다. known-failures 비교는 NEW 0 / known 0 / flaky 0이다.
- 공식 remote runner로 모델 PC에서 실행했다. 노트북 pytest는 실행하지 않았다. 로그는 `%LOCALAPPDATA%/Temp/rosy-time-source-fix/{red,green,affected}/run-1.txt`다.
- 독립 검토에서 주요 지적은 없었다. 새 회귀는 보고 오차가 시간원 선택 범위에 들어오면서도 정밀도 수용은 실패함을 함께 확인한다.

모델·AI 현장 복구는 원본 설정을 백업하고 구문을 검사한 뒤, **재시작 시의 makestep을 먼저 0회로 제한**해 적용했다. 정상 재시작과 rollback 모두 시계 jump를 요청하지 않는다. 실행 중 daemon에 step 비활성을 확인한 뒤 다음 boot용 기존 `makestep 0.1 3`만 디스크에 복구했다. 운영 중 시간 보정은 slew로 수행했다. 소스 이름·단일 source·서비스 자동 시작은 유지했다. `~/rosy-test/maintenance/time-sync/`의 설치기와 미리보기도 수정 소스로 다시 배포해 재설치가 옛 100ms 제한을 되살리지 않게 했다.

## 기기 관측

같은 관제 source가 실제 `*`로 선택된 것을 확인했다. 다음은 복구 후 한 회차의 관측이며 센서 노출 시각·전송 지연·재부팅 수용 증거를 대신하지 않는다.

| 호스트 | 실제 상태 | 남은 시각 보정량 | 표본 나이 | 보고 UTC 오차 상한 |
|---|---|---:|---:|---:|
| 모델 PC | stratum 4, Normal, 같은 source 하나 선택, enabled | 약 -0.355ms | 약 5초 | 약 144ms |
| AI PC | stratum 4, Normal, 같은 source 하나 선택, enabled | 약 -0.0025ms | 약 23초 | 약 142ms |
| 관제 PC | stratum 3, Normal, 기존 NTS source 선택, enabled | 약 -2.18ms | 약 25초 | 약 138ms |

Windows는 앞선 관리자 설치에서 같은 source·최근 동기 성공을 확인했고 이번 후속 조회에서도 같은 source와 Last Sync Error 0을 유지했다. 다만 Windows의 별도 정밀 오차 수용과 재부팅 검증은 아직 남는다.

관제의 기존 NTS upstream 다섯 개는 그대로 유지했다. 한 source 파일의 polling만 minpoll 4 / maxpoll 6으로 바꾸고, 동일한 범위를 실행 중 daemon에도 적용했다. 구문 검사 후 제한된 burst로 재측정했다. 서비스 재시작이나 clock step, upstream 인증 제거는 없었다. 최대 64초의 표본 갱신이 다음 daemon 시작에도 유지된다.

Pinky 두 대는 관제에서 기존 승인 주소의 SSH TCP 접속과 등록된 mDNS 이름 모두 응답하지 않았다. 전원·현장망 연결 확인을 사용자에게 요청한 상태이며, 연결됐다는 답이나 실제 응답이 오기 전에는 적용 완료로 처리하지 않는다. 모바일·MCU는 OS/펌웨어의 시간원 설정과 원본 clock domain을 장치별로 확인해야 한다. OMX의 시스템 시계는 해당 제어 호스트의 NTP를 따른다.

## 남은 수용과 운영 상태

PC의 공통 NTP 동기 동작은 복구됐지만 현재 보고 UTC 상한이 50ms보다 크므로 정밀도 검사는 HOLD다. 인터넷 시간원의 지연·불확실성을 줄이는 수용 증거 없이 기준을 낮추거나 통과로 표시하지 않는다. 물리 로봇 적용과 재부팅·망 단절 후 재동기도 남는다.

사용자는 기존 17개 점유 상태에서 이 수정용 워크트리 **한 개만** 일시 추가하는 예외를 명시 승인했다. 소스 검증·main 반영 뒤 이 슬롯을 정리한다. 첫 착지는 앞선 두 작업의 대기열로 3분 timeout이었다. 대기열을 우회하거나 다른 작업의 공간을 삭제하지 않았다.

CE: 미해결 — 전체 로봇 연결·50ms 정밀도·재부팅 수용은 아직 남는다. 이번 선택 한도 오류의 원인·해결·재발 방지는 코드 주석·회귀·운영 안내에 보존했으며 별도 해결 교훈 문서를 중복 생성하지 않는다.
