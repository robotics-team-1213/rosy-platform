# OMX 구간 검수 저장 안정성·사용 흐름 검증

2026-10-21. 대상은 `/learning/omx`의 원본 확인 → 구간 결과 입력 → 검수 저장 → 선택 JSON 내려받기다. 실제 실물 녹화가 아닌, SYNTHETIC 표식이 있는 genuine LeRobot 0.4.4 파일을 격리된 review DB에 연결했다. 에이전트 입력은 사람의 파지 성공 정답이 아니다.

## 변경과 결정

[D-833 부록](../../adr/D-833-native-omx-grasp-segments.md)에 저장 snapshot·revision과 미저장 편집 보존, 원본 전체 시연과 저장된 구간 선택의 상태 구분을 기록했다. 원본·프레임은 먼저 보이고 결과 입력은 다음 단계다. 공용 `ui-button`·필드를 사용한다. API·인증·CSP·원본 outcome·device 실행 권한은 바꾸지 않았다.

## 저장·조회 경합의 RED/GREEN

명령은 모두 작업 브랜치의 커밋된 HEAD에서 공식 `tools/remote/remote_pytest.py`를 통해 실행했다. `ROSY_RUN_BROWSER_TESTS=1`을 명시했고 Chromium 테스트가 실제 실행됐다. 로그는 외부 `rosy-hybrid-ux-20261021` 작업 폴더에 보존한다.

| revision / 로그 | 확인 결과 |
|---|---|
| `0f6eb2ba74`, `save-red/run-1.txt` | RED: 실제 POST를 지연시킨 동안 저장 버튼이 활성 상태다. 1 failed, NEW 1. 처음 runner 출력은 Windows 문자 인코딩 오류로 끝났지만 원격 실패 로그가 남았다. 이후 UTF-8 출력으로 실행했다. |
| `6bfa333dd7`, `ux-red/run-1.txt` | RED: 원본 이미지가 첫 작업 화면 아래에 있다. 1 failed. |
| `397561b7ff`, `save-green-2/run-1.txt` | GREEN: 3 passed. 늦은 저장 응답 중 추가·삭제 보존, 다음 revision 저장·재조회, 미저장 새로고침 취소, 원본 decisions 불변을 확인했다. |
| `141a8650bf`, `refresh-red-3/run-1.txt` | RED: 오래된 GET snapshot이 이후 완료된 저장의 편집기를 교체한다. 1 failed. |
| `bd9df32739`, `refresh-green/run-1.txt` | GREEN: 3 passed, NEW/known/flaky 0. 저장 시작도 편집 세대를 갱신한다. 실제 별도 POST로 만든 버전 충돌 409에서도 로컬 입력을 유지하고, 명시적 버리기 후 최신 revision을 재조회한다. |
| `634000231b`, `mobile-green/run-1.txt` | 3 passed. 1440·390·320px, 키보드 프레임 확인, 44px 이상 누름 면과 원본 위치 회귀 검증. 뒤의 `a24e421a09`는 실제 긴 세트 이름 화면에서 상단 여백을 더 줄였다. |

저장 테스트의 frame reader만 32px 합성 카메라 fixture로 대체한다. 아래 실제 화면 검증은 대체하지 않은 LeRobot reader와 256×192 MP4를 사용했다. 독립 읽기 전용 검토에서 발견한 refresh/save 경합을 재현·수정했고 `bd9df32739`까지 중요 잔여 지적은 없었다.

## 실제 Edge 화면과 파일 내보내기

UI 실행 revision은 `a24e421a09aaae539c2ba79b94fab590fd99c051`이다. 외부 `walk-ux.py`는 설치된 Edge를 실제로 열어 작업했다. HTTP로 받은 JS·HTML·CSS가 이 revision의 작업 파일과 byte 단위로 같은지 확인했다. 어두운·밝은 두 테마 모두 아래 결과다.

| viewport | 수정 전 원본 위쪽 위치 | 수정 후 | page scrollWidth |
|---|---:|---:|---:|
| 1440×1000 | 830px | 350.39px | 1430px |
| 390×844 | 1907px | 394.39px | 380px |
| 320×568 | 2065px | 394.39px | 310px |

수정 전 검수 버튼 8개는 높이 25px였다. 수정 후 보이는 검수 버튼은 모두 공용 48px이며 모든 폭에서 가로 넘침이 없다. 원본은 창 높이 70% 안에서 시작한다. 상단·탐색 레일을 포함한 스크린샷을 직접 열어 확인했다. 사람 대상 사용성 실험은 수행하지 않았다.

`walk-ux.json` exit 0: 키보드 Enter로 프레임 확인, Space로 구간 추가, 저장 중 추가한 구간 보존과 내려받기 차단, 후속 저장·실제 JSON 다운로드, 새로고침 취소와 키보드 확인, native beforeunload 경고 취소 후 입력 보존, 명시적 버리기 후 저장 구간 재조회가 통과했다. JS page error는 0이다. 이탈 경고 취소는 탐색이 완료되지 않아 Edge의 reload 대기가 timeout일 수 있으므로 실제 beforeunload dialog 발생과 원래 입력 보존도 함께 확인했다.

다운로드한 JSON을 변경하지 않고 실제 `native_segments.py`로 새 출력에 내보냈다. 원본 36프레임 중 train `[2,6)` 4개·eval `[2,6)` 4개·test `[7,9)` 2개, 총 10프레임이다. 독립 원본 session/cycle을 사용했다. `native_cycle.validate_split`와 실제 LeRobot reader로 JSON/receipt 일치, state/action/source clock의 정확한 수치, 원본 frame 대응 이미지를 다시 확인했다. clock은 2^53보다 큰 int64 값이다. 이미지 평균 채널 오차는 8/255 이하다. 원본 디렉터리의 모든 파일 hash가 시작 시점과 같고 `decisions.json`도 바뀌지 않았다. `export-ux.json` exit 0이다.

보존 위치는 우산 폴더의 `artifacts/receipts/omx-grasp-ux-20261021/`다. RED/GREEN 로그, `walk-ux.py`, `serve-ux.py`, `live.py`, `verify-ux.py`, 선택 JSON, 화면·내보내기 결과 JSON과 스크린샷을 보존한다. 기존 1차 화면 검증의 동결 자료는 덮어쓰지 않았다. 최종 착지 로그와 SHA는 이 폴더의 후속 receipt로 보존한다.

`synthetic-ux.tar.gz`는 원본 LeRobot 파일, 실제 10프레임 출력, 일관된 SQLite backup, 선택 JSON, 사용한 UI 자산과 합성 교사 원본을 포함한다. 98,933 bytes, SHA-256 `f537c8e382519c33e9e1464807c76a68617ad9aefaff58ef8d018f926ce36218`. 보관 파일을 다시 열어 필수 항목과 JSON/receipt 일치를 확인했다.

### 공용 버튼 규칙 보완과 최종 화면 재확인

첫 착지 검사 `70ed9dd545`는 공용 `test_helper_created_buttons_name_their_kind`에서 실패했다. 동적 버튼 factory의 종류를 변수로 지정했기 때문이다. `4907175f24`는 주동작 `primary`와 기본 `quiet`를 분기에서 명시한다. 테스트나 허용 목록은 바꾸지 않았다. `button-green/run-1.txt`에서 공용 버튼 규칙·실제 OMX 브라우저·API가 34 passed로 통과했다.

첫 착지 검사의 별도 재실행은 수정된 HEAD를 읽어 `LOAD-FLAKY`로 출력했지만 원인은 소스 수정이다. flaky 증거로 사용하지 않는다. 관문은 검사 중 브랜치 SHA가 바뀌었음을 확인해 병합하지 않고 중단했다. 첫 회차의 아키텍처 267 passed, 영향 검사 2649 passed/283 skipped/1 failed, 명시적 브라우저 210 passed는 `land-red/`에 보존하고 수정 HEAD로 공식 착지를 다시 실행한다.

`4907175f2479d2541183e2844b2508fd06ecd1e2`의 실제 Edge 조작·두 테마·세 viewport·키보드·저장 중 편집·미저장 이탈 보호를 재실행해 exit 0, 동일 위치·48px 누름 면·page error 0을 확인했다. 최종 화면 JSON과 다운로드를 기존 10프레임 출력의 receipt·실제 reader와 다시 비교해 일치했고 원본 모든 파일 hash도 유지됐다. 후속 증거는 보존 폴더의 `final/`에 둔다. 최종 source·선택·출력·DB backup은 `synthetic-ux-final.tar.gz` (99,087 bytes, SHA-256 `154493896d6cbb8489ae21fcf660145dd9a60d352fc0d33d5c96c27dea5e2395`)로 별도 보관한다.

## 남은 수용 범위

실물 장치·전류 임계값·카메라/LLM 파지 판정, 학습 모델 성능·사람 간 일반화·데이터 절감 효과는 이번 UI 검증의 수용이 아니다. 탭 강제 종료·브라우저 충돌 후 임시 편집 복구는 제공하지 않는다. 원격 push·배포·정책 활성화는 실행하지 않는다.
