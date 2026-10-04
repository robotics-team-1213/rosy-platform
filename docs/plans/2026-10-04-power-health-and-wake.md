# 전원·배터리 health와 절전·복귀 개선

현재 소프트웨어 절전은 ACTIVE/IDLE/STANDBY다. STANDBY에서도 CORE API와 안전 감시는 유지하며, OS halt와 구별한다. 유휴 기본 기준은 600초 IDLE, 1800초 STANDBY이며 표본 주기는 20/5/2 Hz다. 로봇 비-IDLE와 정보 표시 hold는 절전을 막는다. LiDAR 모터 정지는 기존 벤치 승인 기본값을 유지하고 실제 모터 상태와 정책 의도를 구별한다.

저배터리 표본마다 wake를 호출하면 계속 ACTIVE가 된다. 경보 단계가 바뀔 때만 알리고 깨우도록 수정한다. 경보 표시·정지·deep 방전 sentinel의 기존 안전 경로는 유지한다. 잔량 경보가 같으면 유휴 절전이 가능하며 실제 부하 감소는 기기에서 측정해야 한다. 알 수 없는 배터리로 종료를 새로 결정하지 않는다.

Viewer `GET /api/v1/power/health`는 조회만 한다. 현재 전원 상태, 절전을 막는 사유, 가능한 최대 소프트웨어 절전 단계, 설정 기준, wake 출처와 배터리 표본 age/신선도·충전 확인·shutdown 요청 상태를 제공한다. 실측 전류·용량 없이 남은 시간을 추측하지 않는다. 기존 Operator `POST /api/v1/power/mode`, `POST /api/v1/power/wake`를 재사용하며 GET은 깨우지 않는다. 네트워크 wake는 OS가 실행 중일 때만 가능하다.

완전 종료 뒤 wake는 별도 하드웨어 검증 단계다. [Raspberry Pi 공식 RTC 문서](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/rtc.adoc)는 Pi 5 RTC 예약 wake를, [전원 버튼 문서](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/power-button.adoc)는 외부 순간 접점 연결을 설명한다. 그러나 Pinky의 전원 보드가 5V 공급을 차단하면 보드 RTC만으로 시스템을 다시 켤 수 있는지 확인해야 한다. 충전 감지·저전압 차단·예약 재기동을 독립 MCU/전원 회로가 담당하는 방식도 후보이며 이번 변경은 EEPROM·GPIO·OS halt·예약 wake를 활성화하지 않는다.

검증은 injected clock의 반복 경보·경보 상승·회복 후 재진입, 배터리 missing/stale, auth와 읽기 전용 API, 기존 wake/절전·배터리·정지 경로 회귀로 진행한다. 이후 안정된 전원에서 실제 소비 전류, 충전 전류, 표시와 센서의 절전, 복귀 시간, wakealarm과 외부 버튼을 각각 측정한다. 반복 재부팅 원인과 현재 충전 확인이 선행 조건이다. SOURCE/LOCAL 결과와 DEVICE/FIELD 수용을 구별한다.


검증 기록 (2026-10-04): 최종 전원·배터리·API·버전·문서와 core_features 크기 회귀 189 passed. 반복 경고는 절전을 허용하고 새 경고/critical/deep 변화는 기존 wake를 유지한다. 충전 표시에는 전압과 충전 확인의 각 age가 모두 5초 이내여야 한다. 정책 ceiling과 wake 처리기에는 실제 하드웨어 인증이 아니라는 basis를 명시한다.

독립 안전 검토: lane_api 검토자는 177 passed를 확인하고, 충전 신선도와 typed 공유 계약의 지적을 재검토하여 SOURCE 안전 GO로 판단했다. 이동·OS halt·EEPROM·GPIO·LiDAR 기본 정지 권한 추가가 없고 기존 critical 정지/deep sentinel은 유지된다. 실제 전류·외부 버튼·RTC와 현장 승인은 포함하지 않는다.

기준선 비교: clean base 767ab07ed에서도 dashboard 패키지 크기 verdict 누락 검사가 실패했다. 이 변경은 dashboard 또는 SIZE_VERDICTS를 수정하지 않는다. 소스 검사는 소비전력 절감량, 기기 적용 또는 완전 종료 후 깨우기를 입증하지 않는다.

공통 fast gate는 455 passed/2 skipped이며 초기 로그 형식·새 테스트 위치 오류를 수정한 재검사 6 passed. 남은 dashboard 크기 오류는 clean baseline에서 재현했다(known_failures 목록에는 등록되지 않아 비교 도구는 NEW로 표시). 새 순수 전원 테스트는 소유 모듈 services/test에 두고, 예외 목록이나 크기 예산을 늘리지 않았다. 최종 harness lint 0 errors/26 기존 경고.

사용자 후속 결정: 계속 시험하고 본체 전원을 켜둔 상황에 맞춰 정상 유휴 기준을 10분 IDLE/30분 STANDBY로 늘린다. warning은 60/300초, critical/deep은 30/120초로 단축하되 정상 설정보다 길어지지 않게 min을 취한다. 각 설정은 power YAML override가 가능하며 API effective_idle_after_s/effective_standby_after_s로 현재 적용 기준을 확인한다. 주행·정보 hold·disabled interlocks와 기존 배터리 정지/종료 정책은 유지한다. 정상으로 복귀하면 긴 기준을 다시 적용하며, 명시적 STANDBY 요청도 현재 유효 기준을 사용한다.

구조 재판정: 기존 core_features 정책 소유자 안의 네 기준과 유효 dwell 함수에 생산 코드 15줄을 추가한다. 패키지 verdict baseline만 12536에서 12551로 조정하고 기존 150 allowance, 파일별 제한, split 판단은 유지한다. 새 배포 단위나 GPIO/halt 경로는 없다. 최종 정책 변화는 독립 안전 검토 및 주입 시계 검사를 따른다.

후속 최종 검사: 전원/배터리/bridge·parser·API/계약·테스트 소유권·크기·로그 186 passed(7.46초). 저배터리 단축은 절전 가능한 로봇 IDLE에서만 적용된다. 실제 DEEP의 E-Stop으로 로봇이 비-IDLE이면 절전을 막는 기존 안전 interlock이 우선하며, 해제하지 않는다. deep sentinel 종료 조건은 기존 경로대로다.

후속 독립 안전 검토 lane_api: SOURCE GO, 관련 검사183개와 별도 경계 검증6개 통과. 각 경보·기존 더 짧은 기준의 min, 반복 DEEP 알림, 주행/EMERGENCY/정보 hold/disabled 인터록과 명시적 STANDBY의 유효 기준을 확인했다. 물리 wake나 소비전력 감소를 승인한 것은 아니다.
