# D-856 중립 ARM 작업 HTTP 제안·승인

## 범위

API v1.307은 simulation에 설치된 물리 참조를 제안·조회하고 다른 named operator가 승인하는 입구다. `POST /api/fleet/arm-transfers/jobs`, principal별 request-key 조회, ID 조회와 `/admit`을 제공한다. 앱은 object/source/target·scope와 request key만 제출하며 설치 정책·자원·capability·grant·업무 완료를 지정하지 못한다. 설치하지 않은 경로는 503이다.

최종 소스는 commit `58f7cc7b14272115a7f9be790839c35d935b55ac`다. 승인 HTTP는 모든 참여 owner의 현재 capability를 기존 SDK로 읽고 기존 원장의 snapshot/CAS·두 사람·dispatch fence·claims 검사를 호출한다. SDK 조회는 SQLite writer transaction 밖이다. 기존 인증·감사와 present-Origin 검사를 적용하며 내부 설치 자료를 응답에서 제거한다. Foundation의 frozen closed DTO를 store와 HTTP가 공유한다. 예산이 있는 facade에서 분리한 FleetTaskStatus는 기존 클래스와 AST가 같으며 facade 재수출을 유지한다.

이 단계는 장치 submit/cancel/get dispatcher, prepared action/attempt, 관측 credential ingress, physical receipt/claim 종료와 Harbor ARM binding을 연결하지 않는다. READY는 실행 제출이나 구역이 비었다는 증거가 아니다. 장치 owner 권한과 legacy Cell 실행·완료 경로는 그대로다.

## 원격 시험

모든 pytest는 공식 remote runner로 고정 커밋에서 실행했다. 원본 실패를 최종 통과로 덮어쓰지 않는다.

| 소스·실행 | 결과 | 공식 known_failures 분류 |
| --- | --- | --- |
| 계약 RED `7f9ccacc2c`, `rosy-arm-job-http-red/run-1.txt` | 21 failed, 14 errors, skip 0 | 35 NEW: DTO/라우트가 없던 실패 |
| 구현 `b5c52bcfc1`, `rosy-arm-job-http-b5-focus/run-1.txt` | 1205 passed, 16 failed, skip 0 | 16 NEW |
| 보완 `58f7cc7b14`, `rosy-arm-job-http-origin-focus/run-1.txt` | 18 passed, skip 0 | 0 NEW |

로그 경로의 기준은 `C:/Users/SERIGGG/AppData/Local/Temp/`다. b5의 15건은 새 시험이 필수 자원 kind/id 없이 기존 TaskStore 함수를 호출한 오류다. 기존 Cell store의 공통 전체 claims 조회로 시험을 고쳤다. 나머지 1건에서 외부 Origin을 허용하는 누락을 확인했고, 기존 same_origin helper를 두 POST에 연결해 create/admit 모두 거절하도록 보완했다. 권한·검증·응답 동작 자체의 성공을 시험 helper 실패와 혼동하지 않는다.

전체 선택은 baseline commit `958d27562836e56743ba0d8eed421d0c8d53df6c`에서 최종 소스까지 계산했다. Foundation 변경으로 FULL이다. 원본 `rosy-arm-job-http-58-selection.json`을 보존하고 execution JSON은 metadata·mode·full_invocations를 유지하면서 local_invocations만 원본 full_invocations 전체 23개로 교체했다. `--skip`이나 추가 ignore 없이 `rosy-arm-job-http-58-full`에서 실행했으며 전체 runner exit 0, 23개 invocation 각각 exit 0·공식 known 0 NEW다. [전체 manifest](full-run-summary.json)에 exact targets·각 로그 summary/duration·공식 분류를 보존했다.

대표 묶음은 entry9 7398 passed/91 skipped, entry12 Fleet 6361 passed/336 skipped, entry21 root 9710 passed/1132 skipped다. 중복되는 suite 수치를 합산하지 않으며 skip은 실행·물리 수용 근거로 세지 않는다. 이 FULL은 schema6 HTTP 소스58의 검증이다. 뒤의 준비 원장7과 최초 전송 의도8 변경은 별도 고정 SHA·선택으로 검증하며 이 통과에 섞지 않는다.

## 검토와 한계

독립 `rosy_contract_reviewer`가 최종 58f7cc7b14의 DTO·app binding·HTTP·원장 호출·시험을 읽고 추가 material finding 없음으로 보고했다. 두 사람 identity, current capability와 transaction 순서, 미설치 503, present-Origin, 내부 자료 비노출과 legacy 경로를 확인한 소스 검토다. 시험 실행이나 실물 수용을 대신하지 않는다.

958d→58의 3개 커밋 size_range와 safety_review는 각각 exit 0이다. 이 단계의 해결 근거는 source·회귀시험·API 정본에 있으므로 별도 CE 교훈을 늘리지 않는다. 이전 G1 접촉 간격 실패의 원인은 여전히 미확정이며 현재 HTTP 시험이나 과거 strict 재통과를 원인 해결로 보지 않는다. 실물 실행·배포·push·merge는 하지 않았다.
