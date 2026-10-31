# Games 조회 대기와 늦은 응답의 신선도 표시

2026-10-29, `fix/games-receipt-freshness`, base `db4b373f32`. runtime `fd770d8d36`, 최종 시험/캡처 `068aa03060`(이후 test-only). 서버 상태 enum·점수·위치·관측 source와 stop/account 경로는 바꾸지 않았다.

## 문제와 수정

이전 tick은 polling=true인 GET/JSON이 끝나지 않으면 다음 조회를 막고 마지막 fresh 화면을 유지했다. 호스트 age_s·stale_after_s에 브라우저 monotonic 경과를 더해 polling guard 앞에서 마지막 수신 정보를 delayed로 전환하고 GET과 JSON body 읽기에 기존 방식의5초 deadline을 적용했다. 실패 후 finally가 polling을 풀어 재조회를 이어간다. 첫 데이터가 없으면 과거 경기라고 주장하지 않는다.

첫 수정은50개 browser case가 통과했지만 독립 리뷰가 추가 P2를 찾았다. snapshot 생성 뒤2초 넘게 지연돼5초 deadline 전에 도착하면 receipt 시각만 새로 잡아 fresh로 되돌릴 수 있었다. 실제 headers/body를2.3초 늦게 보내는4개 RED로 이를 확인했다. 최종 구현은 요청 시작부터의 monotonic 경과를 age 상한에 포함하고 도착할 때 이미 오래된 응답을 delayed로 표시한다. UTC generated_at과 브라우저 시계를 빼지 않는다. 전송 지연으로 추정한 상태에는 정밀한 생성 시각을 주장하지 않는다.

fresh 문구만 있고 유효한 age/임계값이 없으면 unavailable로 처리한다. 이미 host delayed/unavailable인 정보를 fresh로 올리지 않는다. 마지막 점수·위치·단계는 보존하고, 같은 stale 전환을 매 tick 보조기기에 반복하지 않는다. stop 요청 접수와 실제 정지 확인의 구분, 정지 버튼과 스페이스 키, 계정 권한은 기존대로다.

## 원격 실행 근거

원본은 `C:/DevTemp/rosy-ui-standardization/`. 공식 원격 시험 PC에서 커밋 SHA의 실제 PreviewServer·Chromium을 실행했다. 로봇·CORE·실제 경기 호스트·실물 정지에 연결하지 않았다. handler는 동일 자산·계정 layout fixture를 사용하며 GET의 headers 또는 첫 JSON 바이트 뒤만 Event로 지연했다. fixture 정리는12초 상한을 두고, UI의5초 deadline 전에 완료되지 않는 응답을 검증했다. 신호·JSON body abort를 가짜 Promise로 대체하지 않았다.

| source | 로그 | 결과 |
|---|---|---|
| `88b086cfed` | games-hung-red/run-1.txt | headers/body 대기 × 과거 경기 유무 ×320/1280의8 실패 |
| `a41e780527` | games-hung-green/run-1.txt | 최초 수정50 passed/skip0. 아래 추가 리뷰 발견 전의 중간 증거 |
| `b857f58fc1` | games-late-red/run-1.txt | 늦게 완료된 응답이 fresh로 역전되는4 실패/54 deselected |
| `36d47919f3` | games-timing-red/run-1.txt | 시각 근거 없는 fresh 주장1 실패/60 deselected |
| `fd770d8d36` | games-age-green/run-1.txt | **전체 board browser61 passed/0 skipped**, 169.67s |
| `068aa03060` | games-age-captures/run-1.txt | 강화된 부분집합16 passed/45 deselected/skip0와18PNG |
| `068aa03060` | games-age-affected/run-1.txt | 공식 affected:641 passed/61 skipped/warnings48 |
| `068aa03060` | games-age-affected/run-2.txt | 연결된 overhead 회귀785 passed/skip0 |

모든 합격 로그는 known_failures NEW0/known0/flaky0이다. listed-but-not-failing 테마 시험은 이 변경의 수정 증거가 아니어서 baseline을 유지했다. browser61에16개가 포함되므로77개 고유 case로 합산하지 않는다. 영향 검사61 skip을 실행한 것으로 쓰지 않는다. FULL·전체 UI·CI 전체 통과 기록도 아니다.

실행 assertion은 이전 값이 없는 첫 오류, 기존 점수/phase/위치의 stale 표식·ARIA, headers/body timeout 후 polling 복구, 늦은 snapshot의 즉시 delayed, 시각 근거 없는 unavailable, 같은 계정의 정지 조작 유지와 fresh 복구를 포함한다. 기존 server-judged delay·알림 중복 방지·권한·정지 접수/실패·선언 폭·긴 ID 회귀도 그대로 통과했다. POST 자동 재전송이나 장치 행동을 추가하지 않았다.

## 화면과 한계

최종18장은 body 지연의 timeout/late × 과거 경기 유무 ×320×900/1280×800에서 delayed/disconnected/recovered를 보인다. 시험 전용 경로에서 `C:/DevTemp/rosy-ui-standardization/games-captures-final/`로 보존했다. logs8개·captures18개 hash는 인접 manifest에 있다. A(`/root/ui_design`) source 재검토와 독립 B(`/root/ui_evidence`)의18/18장 직접 검토에서 해당 변경의 P1/P2가 없었다. Root도 첫 오류320과 늦은 응답1280을 직접 확인했다.

이전 경기의 단계/점수/위치에 각각 마지막 값·현재 위치 아님을 표시하고 복구 때 해제한다. 첫 오류는 점수—/경기 정보 없음으로 구별한다. 두 폭의 정지 버튼과 키 안내가 보이고 긴 문구가 겹치지 않는다. body 정지 이미지는 headers 동작이나 더 짧은 모바일 화면·물리 정지를 증명하지 않는다. headers와390/480/600 등 기존 viewport 동작은 실행 assertion의 별도 근거다. stale 안내가 과거 위치 위를 덮는 것은 현재 위치 오인을 막는 기존 표현이다.

gate 변화 없음. DEVICE/FIELD·전체 G2/G3 HOLD는 그대로다. stop UI/HTTP fixture를 실제 전달·SAFE_STOP readback·경기 운용 GO로 쓰지 않는다. native 빌드·실물·배포·착지/push/merge와 전체 표준화 통합은 수행하지 않았다.

CE: 해당 없음 — receipt/요청 경과의 구분과 UTC를 비교하지 않는 이유는 최종 comment·실제 늦은 응답/본문 지연 회귀·이 검증 기록에서 복구할 수 있다. 최초50 통과만으로 충분하지 않았던 판단도 원본 RED와 함께 남겼으며 별도 중복 교훈은 만들지 않았다.
